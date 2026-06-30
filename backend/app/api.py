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
    return {
        "message": "Document already indexed — reused existing data." if reused else "PDF processed successfully.",
        "doc_id": result["doc_id"],
        "filename": result["filename"],
        "summary": result["summary"],
        "facts": result["facts"] if isinstance(result["facts"], list) else json.loads(result["facts"]),
        "chunks": result.get("chunks", result.get("chunk_count", 0)),
        "reused": reused,
    }


@app.post("/query")
async def query(request: QueryRequest):
    answer = chat.ask(request.question, request.doc_id)
    return {"answer": answer}


@app.get("/document/{doc_id}")
def get_document_route(doc_id: str):
    doc = chat.get_document_info(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["facts"] = json.loads(doc["facts"])
    return doc
