import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.chat_engine import ChatEngine, QuotaError
from app.database import init_db
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="DocuMind API", lifespan=lifespan)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# This app has no real per-user auth — a public SPA can't hold a secret,
# so a client-side API key (the old VITE_APP_API_KEY setup) only ever
# protected against people who didn't open devtools. Instead:
#   - CORS is locked to the actual frontend origins, so arbitrary sites
#     can't call this API from a victim's browser.
#   - Rate limiting (below) bounds cost/abuse from direct callers
#     (curl, Postman, scripts) that CORS can't stop, since CORS is a
#     browser-enforced rule only.
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173"
    ).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

chat = ChatEngine()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


class QueryRequest(BaseModel):
    question: str
    doc_id: str


@app.get("/")
def root():
    return {"message": "DocuMind API is running."}


@app.get("/health")
def health():
    return {"status": "ok"}


UPLOAD_READ_CHUNK_BYTES = 1024 * 1024  # 1 MB


@app.post("/ingest")
@limiter.limit("5/minute")
async def ingest_pdf(request: Request, file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")

    # Fast path: reject up front if the client told the truth about size.
    declared_size = request.headers.get("content-length")
    if declared_size and int(declared_size) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {MAX_UPLOAD_BYTES // (1024*1024)} MB."
        )

    # Real enforcement: read in bounded chunks and abort the instant the
    # cap is crossed, instead of calling file.read() with no limit and
    # checking size only after the whole upload is already buffered in
    # memory. Content-Length can be absent or wrong (chunked transfer
    # encoding, a lying client), so this is the check that actually
    # bounds memory use per request.
    buffer = bytearray()
    while True:
        piece = await file.read(UPLOAD_READ_CHUNK_BYTES)
        if not piece:
            break
        buffer.extend(piece)
        if len(buffer) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max size is {MAX_UPLOAD_BYTES // (1024*1024)} MB."
            )
    contents = bytes(buffer)

    try:
        result = chat.load_pdf(contents, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except QuotaError as e:
        wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — please try again later."
        raise HTTPException(status_code=429, detail=f"Gemini API quota exceeded. {wait_note}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

    reused = result.get("reused", False)
    partial = result.get("partial", False)
    if reused:
        message = "Document already indexed — reused existing data."
    elif partial:
        message = f"PDF partially processed — {result.get('chunks', 0)} of the document's chunks were indexed before the embedding quota was reached."
    else:
        message = "PDF processed successfully."

    return {
        "message": message,
        "doc_id": result["doc_id"],
        "filename": result["filename"],
        "summary": result["summary"],
        "facts": result["facts"] if isinstance(result["facts"], list) else json.loads(result["facts"]),
        "chunks": result.get("chunks", result.get("chunk_count", 0)),
        "reused": reused,
        "partial": partial,
        "summary_truncated": result.get("summary_truncated", False),
    }


@app.post("/query")
@limiter.limit("15/minute")
async def query(request: Request, body: QueryRequest):
    try:
        answer = chat.ask(body.question, body.doc_id)
    except QuotaError as e:
        wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — please try again later."
        raise HTTPException(status_code=429, detail=f"Gemini API quota reached. {wait_note}")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to answer the question.")
    return {"answer": answer}


@app.get("/document/{doc_id}")
@limiter.limit("30/minute")
def get_document_route(request: Request, doc_id: str):
    doc = chat.get_document_info(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["facts"] = json.loads(doc["facts"])
    return doc
