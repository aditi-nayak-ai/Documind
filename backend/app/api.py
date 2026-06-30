
import io
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.chat_engine import ChatEngine
from app.database import init_db
 
 
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
 
 
class QueryRequest(BaseModel):
    question: str
    doc_id: str
 
 
@app.get("/")
def root():
    return {"message": "DocuMind API is running."}
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
 
 
# NOTE: the old /models endpoint was removed. It exposed the full list of
# models available to this Gemini API key with no auth — unnecessary
# reconnaissance surface for anyone who finds the URL.
 
 
@app.post("/ingest")
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
        result = chat.load_pdf(io.BytesIO(contents), file.filename)
    except ValueError as e:
        # Empty / scanned / image-only PDF — extraction produced near-nothing.
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        if "QUOTA_EXCEEDED" in str(e):
            raise HTTPException(
                status_code=429,
                detail="Gemini API quota exceeded. Please try again later or contact the administrator."
            )
        raise HTTPException(status_code=500, detail="Failed to process document.")
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
 
 
@app.post("/query")
async def query(request: QueryRequest):
    try:
        answer = chat.ask(request.question, request.doc_id)
    except RuntimeError as e:
        if "QUOTA_EXCEEDED" in str(e):
            raise HTTPException(
                status_code=429,
                detail="Gemini API quota reached. Please wait a minute and try again."
            )
        raise HTTPException(status_code=500, detail="Failed to answer the question.")
    return {"answer": answer}
 
 
@app.get("/document/{doc_id}")
def get_document_route(doc_id: str):
    doc = chat.get_document_info(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["facts"] = json.loads(doc["facts"])
    return doc
 
