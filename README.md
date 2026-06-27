# DocuMind — AI Document Intelligence

Upload any PDF and instantly get a summary, key facts, and a chat interface to ask questions about your document.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, Tailwind CSS |
| Backend | FastAPI, Python 3.11 |
| Vector DB | PostgreSQL + pgvector |
| Embeddings | Sentence Transformers (all-MiniLM-L6-v2) |
| LLM | Google Gemini 1.5 Flash |
| Deployment | Render (backend), Vercel (frontend) |
| CI/CD | GitHub Actions |

## Features

- PDF upload with drag and drop
- Automatic summarization
- Key fact extraction
- Chat interface with RAG-based question answering
- Persistent vector storage with pgvector

## Architecture

PDF → Text Extraction → Chunking → Sentence Transformer Embeddings → pgvector storage
Question → Embed → pgvector similarity search → Top 3 chunks → Gemini generation → Answer

## Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.api:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Environment Variables
Backend (Render):
- `DATABASE_URL` — PostgreSQL connection string
- `GEMINI_API_KEY` — Google AI Studio key

Frontend (Vercel):
- `VITE_BACKEND_URL` — Render backend URL
