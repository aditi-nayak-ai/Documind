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


class QueryRequest(BaseModel):
    question: str
    filename: str


@app.get("/")
def root():
    return {"message": "DocuMind API is running."}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/models")
def list_models():
    models = [m.name for m in chat.client.models.list()]
    return {"models": models}

@app.post("/ingest")
async def ingest_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")
    contents = await file.read()
    try:
        result = chat.load_pdf(io.BytesIO(contents), file.filename)
    except RuntimeError as e:
        if "QUOTA_EXCEEDED" in str(e):
            raise HTTPException(
                status_code=429,
                detail="Gemini API quota exceeded. Please try again later or contact the administrator."
            )
        raise HTTPException(status_code=500, detail="Failed to process document.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

    return {
        "message": "PDF processed successfully.",
        "filename": file.filename,
        "summary": result["summary"],
        "facts": result["facts"],
        "chunks": result["chunks"]
    }

@app.post("/query")
def query(request: QueryRequest):
    answer = chat.ask(request.question, request.filename)
    return {"answer": answer}


@app.get("/document/{filename}")
def get_document_route(filename: str):
    doc = chat.get_document_info(filename)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["facts"] = json.loads(doc["facts"])
    return doc
