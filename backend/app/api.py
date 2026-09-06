import json
import time
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.chat_engine import ChatEngine, QuotaError
from app.config import settings
from app.database import check_connection, init_db
from app.logging_config import request_id_ctx, setup_logging
from app.metrics import metrics

logger = setup_logging("documind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="DocuMind API", lifespan=lifespan)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Assigns a request ID to every incoming request, makes it available
    to every log line emitted while handling that request (via the
    contextvar in logging_config.py), returns it as a response header so
    a client-reported issue can be matched to server logs, and logs a
    start/end line with method/path/status/duration for basic request
    tracing without a full APM tool.
    """
    incoming_id = request.headers.get("x-request-id")
    request_id = incoming_id or str(uuid.uuid4())
    token = request_id_ctx.set(request_id)
    start = time.monotonic()
    try:
        logger.info("request started", extra={"method": request.method, "path": request.url.path})
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_ctx.reset(token)


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
ALLOWED_ORIGINS = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]

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
    """Checks actual DB connectivity, not just that the FastAPI process
    is alive -- a crashed/unreachable Postgres should surface as an
    unhealthy service (so Render/an uptime monitor can page on it),
    not a silent 200 that only means 'the HTTP server thread is up.'
    """
    db_ok = check_connection()
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={"status": "ok" if db_ok else "unhealthy", "database": "connected" if db_ok else "unreachable"},
    )


@app.get("/stats")
def stats():
    """Basic operational metrics -- request counts, failure counts, quota
    error counts, average latencies. In-memory only (see app/metrics.py
    for why that's an acceptable tradeoff for a single-instance
    deployment); intended for a quick operational glance or for pointing
    to in an interview, not a substitute for a real metrics backend at
    higher scale."""
    return metrics.snapshot()


UPLOAD_READ_CHUNK_BYTES = 1024 * 1024  # 1 MB


@app.post("/ingest")
@limiter.limit("5/minute")
async def ingest_pdf(request: Request, file: UploadFile = File(...)):  # noqa: B008 -- File(...) as a default is FastAPI's documented dependency-injection pattern, not a mutable-default bug
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

    ingest_start = time.monotonic()
    try:
        result = chat.load_pdf(contents, file.filename)
    except ValueError as e:
        metrics.increment("ingests_failed_total")
        raise HTTPException(status_code=422, detail=str(e))
    except QuotaError as e:
        metrics.increment("ingests_failed_total")
        metrics.increment("quota_errors_total")
        wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — please try again later."
        raise HTTPException(status_code=429, detail=f"Gemini API quota exceeded. {wait_note}")
    except Exception as e:  # noqa: BLE001 -- deliberate top-level boundary: any unexpected failure here still needs to become a clean 500 instead of an unhandled crash
        metrics.increment("ingests_failed_total")
        # Log the full traceback server-side so Render's logs show the real
        # cause — previously only "500 Internal Server Error" showed up
        # with nothing to debug from. The client still just gets str(e).
        logger.error("Unexpected error in /ingest", extra={"error": str(e), "traceback": traceback.format_exc()})
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e!s}")

    metrics.increment("ingests_total")
    metrics.record_duration("ingest_ms", round((time.monotonic() - ingest_start) * 1000, 1))

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
    query_start = time.monotonic()
    try:
        answer = chat.ask(body.question, body.doc_id)
    except QuotaError as e:
        metrics.increment("queries_failed_total")
        metrics.increment("quota_errors_total")
        wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — please try again later."
        raise HTTPException(status_code=429, detail=f"Gemini API quota reached. {wait_note}")
    except Exception as e:  # noqa: BLE001 -- same rationale as /ingest above: convert any unexpected failure into a clean 500 rather than letting it crash unhandled
        metrics.increment("queries_failed_total")
        logger.error("Unexpected error in /query", extra={"error": str(e), "traceback": traceback.format_exc()})
        raise HTTPException(status_code=500, detail="Failed to answer the question.")

    metrics.increment("queries_total")
    metrics.record_duration("query_ms", round((time.monotonic() - query_start) * 1000, 1))
    return {"answer": answer}


@app.get("/document/{doc_id}")
@limiter.limit("30/minute")
def get_document_route(request: Request, doc_id: str):
    doc = chat.get_document_info(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["facts"] = json.loads(doc["facts"])
    return doc
