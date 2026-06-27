import io
import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.chat_engine import ChatEngine

app = FastAPI(title="DocuMind API")

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

@app.post("/ingest")
async def ingest_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")
    contents = await file.read()
    result = chat.load_pdf(io.BytesIO(contents), file.filename)
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
def get_document(filename: str):
    doc = chat.get_document_info(filename)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    import json
    doc["facts"] = json.loads(doc["facts"])
    return doc
