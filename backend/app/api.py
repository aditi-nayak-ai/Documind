import time
import traceback
import uuid
from contextlib import asynccontextmanager
 
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
 
from app.auth import (
    _DUMMY_PASSWORD_HASH,
    create_access_token,
    get_current_user,
    hash_password,
    normalize_email,
    verify_password,
)
from app.chat_engine import ChatEngine, QuotaError, TransientServerError
from app.config import settings, validate_settings_or_raise
from app.database import (
    check_connection,
    create_user,
    get_ingest_count,
    get_user_by_email,
    increment_token_version,
    increment_user_usage,
    init_db,
)
from app.logging_config import request_id_ctx, setup_logging
from app.metrics import metrics
from app.rag_service import failure_flags, normalize_facts
 
logger = setup_logging("documind")
 
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_settings_or_raise()  # e.g. a missing/too-short JWT secret -- fail at startup, not at the first login
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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
chat = ChatEngine()
 
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
 
 
class QueryRequest(BaseModel):
    question: str
    doc_id: str
 
 
class RegisterRequest(BaseModel):
    email: EmailStr
    # min_length=8 here is what produces the pydantic 422 validation error
    # AuthPage.jsx already knows how to render (see its "Array.isArray(detail)"
    # handling) -- keep this in sync with the message in MIGRATION.md's
    # example curl command if it ever changes.
    password: str = Field(min_length=8)
 
 
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
 
 
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
 
 
@app.post("/auth/register", response_model=TokenResponse)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest):
    email = normalize_email(body.email)
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = create_user(email, hash_password(body.password))
    token = create_access_token(user["id"], user["email"], user["token_version"])
    return TokenResponse(access_token=token)
 
 
@app.post("/auth/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest):
    user = get_user_by_email(normalize_email(body.email))
    # Identical error for "no such email" and "wrong password" -- AND now
    # identical timing too. verify_password() (bcrypt) always runs, even
    # for an unknown email, against a dummy hash. Previously `not user or
    # not verify_password(...)` short-circuited on `or` and skipped the
    # (deliberately slow) bcrypt call entirely for unknown emails, which
    # made that response measurably faster and let an attacker enumerate
    # registered emails by timing alone, despite the identical error text.
    password_hash = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(body.password, password_hash)
    if not user or not password_ok:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token = create_access_token(user["id"], user["email"], user["token_version"])
    return TokenResponse(access_token=token)
 
 
@app.post("/auth/logout", status_code=204)
def logout(current_user=Depends(get_current_user)):  # noqa: B008 -- FastAPI's documented DI pattern
    """Server-side revocation, not just "the client throws its token away".
    Bumps the user's token_version, which immediately invalidates the
    token used to call this endpoint -- and every other outstanding token
    for this user, since revocation here is per-user, not per-token (see
    app/auth.py's module docstring for why). A stolen or leaked token can
    now actually be killed instead of staying valid for the rest of its
    7-day life with no way to stop it."""
    increment_token_version(current_user["id"])
    return Response(status_code=204)
 
 
@app.get("/auth/me")
def me(current_user=Depends(get_current_user)):  # noqa: B008 -- FastAPI's documented DI pattern, same rationale as File(...) elsewhere in this file
    return {"id": current_user["id"], "email": current_user["email"]}
 
 
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
def ingest_pdf(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 -- File(...) as a default is FastAPI's documented dependency-injection pattern, not a mutable-default bug
    current_user=Depends(get_current_user),  # noqa: B008 -- FastAPI's documented DI pattern
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")
 
    # A lifetime cap independent of any IP-based rate limiting. slowapi's
    # 5/minute limit above only throttles a burst; it does nothing to stop
    # one account slowly draining the shared Gemini quota over hours or
    # days, and it keys on the request's IP, which is not fully trustworthy
    # here (see app/auth.py's docstring on Render's X-Forwarded-For
    # behavior). user_id comes from a verified JWT and can't be spoofed.
    if get_ingest_count(current_user["id"]) >= settings.max_ingests_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"You've reached the limit of {settings.max_ingests_per_user} document uploads for this account.",
        )
 
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
        piece = file.file.read(UPLOAD_READ_CHUNK_BYTES)
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
        result = chat.load_pdf(contents, file.filename, user_id=current_user["id"])
    except ValueError as e:
        metrics.increment("ingests_failed_total")
        raise HTTPException(status_code=422, detail=str(e))
    except QuotaError as e:
        metrics.increment("ingests_failed_total")
        metrics.increment("quota_errors_total")
        wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — please try again later."
        raise HTTPException(status_code=429, detail=f"Gemini API quota exceeded. {wait_note}")
    except TransientServerError:
        metrics.increment("ingests_failed_total")
        raise HTTPException(status_code=503, detail="Gemini's servers are temporarily overloaded. Please try again shortly.")
    except Exception as e:  # noqa: BLE001 -- deliberate top-level boundary: any unexpected failure here still needs to become a clean 500 instead of an unhandled crash
        metrics.increment("ingests_failed_total")
        # Full detail goes to the server log only. The client used to get
        # f"Unexpected error: {e!s}" verbatim -- a corrupt PDF or a pypdf
        # internals error could leak file paths, library internals, or
        # other implementation detail to whoever uploaded the file.
        logger.error("Unexpected error in /ingest", extra={"error": str(e), "traceback": traceback.format_exc()})
        raise HTTPException(status_code=500, detail="Something went wrong while processing this file. Please try again.")
 
    metrics.increment("ingests_total")
    metrics.record_duration("ingest_ms", round((time.monotonic() - ingest_start) * 1000, 1))
    increment_user_usage(current_user["id"], "ingests")
 
    reused = result.get("reused", False)
    partial = result.get("partial", False)
    facts = normalize_facts(result["facts"])
    summary_failed, facts_failed = failure_flags(result["summary"], facts)
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
        "facts": facts,
        "chunks": result.get("chunks", result.get("chunk_count", 0)),
        "reused": reused,
        "partial": partial,
        "summary_truncated": result.get("summary_truncated", False),
        "summary_failed": summary_failed,
        "facts_failed": facts_failed,
    }
 
 
@app.post("/query")
@limiter.limit("15/minute")
def query(request: Request, body: QueryRequest, current_user=Depends(get_current_user)):  # noqa: B008 -- FastAPI's documented DI pattern
    # Ownership check happens here, once, before ask() ever touches
    # document_chunks -- see the docstring on database.search_chunks for
    # why that function itself doesn't re-check user_id.
    if not chat.get_document_info(body.doc_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Document not found.")
 
    query_start = time.monotonic()
    try:
        answer = chat.ask(body.question, body.doc_id)
    except QuotaError as e:
        metrics.increment("queries_failed_total")
        metrics.increment("quota_errors_total")
        wait_note = "Please wait a minute and try again." if not e.is_daily else "Quota resets daily — please try again later."
        raise HTTPException(status_code=429, detail=f"Gemini API quota reached. {wait_note}")
    except TransientServerError:
        metrics.increment("queries_failed_total")
        raise HTTPException(status_code=503, detail="Gemini's servers are temporarily overloaded. Please try again shortly.")
    except Exception as e:  # noqa: BLE001 -- same rationale as /ingest above: convert any unexpected failure into a clean 500 rather than letting it crash unhandled
        metrics.increment("queries_failed_total")
        logger.error("Unexpected error in /query", extra={"error": str(e), "traceback": traceback.format_exc()})
        raise HTTPException(status_code=500, detail="Failed to answer the question.")
 
    metrics.increment("queries_total")
    metrics.record_duration("query_ms", round((time.monotonic() - query_start) * 1000, 1))
    increment_user_usage(current_user["id"], "queries")
    return {"answer": answer}
 
 
@app.get("/document/{doc_id}")
@limiter.limit("30/minute")
def get_document_route(request: Request, doc_id: str, current_user=Depends(get_current_user)):  # noqa: B008 -- FastAPI's documented DI pattern
    doc = chat.get_document_info(doc_id, current_user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["summary_failed"], doc["facts_failed"] = failure_flags(doc["summary"], doc["facts"])
    doc["facts"] = normalize_facts(doc["facts"])
    return doc
 
 
@app.delete("/document/{doc_id}", status_code=204)
@limiter.limit("30/minute")
def delete_document_route(request: Request, doc_id: str, current_user=Depends(get_current_user)):  # noqa: B008 -- FastAPI's documented DI pattern
    if not chat.delete_document(doc_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Document not found.")
    return Response(status_code=204)
