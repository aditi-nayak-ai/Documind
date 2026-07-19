import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.chat_engine import ChatEngine, QuotaError
from app.database import init_db
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="DocuMind API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

chat = ChatEngine()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def verify_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("APP_API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")


class QueryRequest(BaseModel):
    question: str
    doc_id: str


@app.get("/")
def root():
    return {"message": "DocuMind API is running."}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest", dependencies=[Depends(verify_key)])
async def ingest_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {MAX_UPLOAD_BYTES // (1024*1024)} MB."
        )
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
    }


@app.post("/query", dependencies=[Depends(verify_key)])
async def query(request: QueryRequest):
    try:
        answer = chat.ask(request.question, request.doc_id)
    except QuotaError as e:
        wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — please try again later."
        raise HTTPException(status_code=429, detail=f"Gemini API quota reached. {wait_note}")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to answer the question.")
    return {"answer": answer}


@app.get("/document/{doc_id}")
def get_document_route(doc_id: str):
    doc = chat.get_document_info(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["facts"] = json.loads(doc["facts"])
    return doc
