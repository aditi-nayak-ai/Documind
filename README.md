# DocuMind

A full-stack RAG application that lets you upload any PDF, get an instant AI-generated summary and key facts, and chat with the document using natural language.

Live demo: [documind-murex.vercel.app](https://documind-murex.vercel.app)

---

## How it works

```
PDF Upload
  → Text extraction (pypdf)
  → Paragraph chunking (500 char windows)
  → Embedding each chunk (gemini-embedding-001, 3072 dimensions)
  → Stored in pgvector (Neon PostgreSQL)

User Question
  → Embed question (gemini-embedding-001)
  → Cosine similarity search → top 3 chunks retrieved
  → Chunks + question sent to gemini-2.0-flash
  → Answer returned to chat UI
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS |
| Backend | FastAPI, Python 3.11 |
| Embeddings | Gemini Embedding API (`gemini-embedding-001`, 3072-dim) |
| LLM | Google Gemini (`gemini-2.0-flash`) |
| Vector store | PostgreSQL + pgvector (Neon) |
| Deployment | Render (backend), Vercel (frontend) |
| CI/CD | GitHub Actions |

---

## Project structure

```
Documind/
├── backend/
│   ├── app/
│   │   ├── api.py          # FastAPI routes: /ingest, /query
│   │   ├── chat_engine.py  # PDF parsing, chunking, embedding, RAG
│   │   └── database.py     # SQLAlchemy engine, pgvector queries
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   └── components/
    │       ├── UploadZone.jsx
    │       ├── SummaryPanel.jsx
    │       ├── FactsPanel.jsx
    │       └── ChatWindow.jsx
    └── tailwind.config.js
```

---

## Local setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL instance with pgvector extension enabled (or a Neon free-tier database)
- Google AI Studio API key

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.api:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Environment variables

Backend — set in Render dashboard or a local `.env` file (never commit this):

```
DATABASE_URL=postgresql://...
GEMINI_API_KEY=...
```

Frontend — set in Vercel dashboard or a local `.env.local` file:

```
VITE_BACKEND_URL=https://your-render-service.onrender.com
```

---

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/ingest` | Upload a PDF. Returns summary, facts, chunk count. |
| POST | `/query` | Ask a question. Requires `question` and `filename` in body. |

### Example

```bash
# Upload
curl -X POST https://your-backend.onrender.com/ingest \
  -F "file=@document.pdf"

# Query
curl -X POST https://your-backend.onrender.com/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the main argument?", "filename": "document.pdf"}'
```

---

### Screenshot 
### LogIn :
<img width="1920" height="1080" alt="Login" src="https://github.com/user-attachments/assets/b80ed6ff-2499-42b8-ab76-86f60d7ea021" />

### Upload A PDF :
<img width="1920" height="1080" alt="Upload A PDF" src="https://github.com/user-attachments/assets/9e15fbf2-5551-49dc-99ee-650f7dd1b182" />

### CHAT :
<img width="1920" height="1080" alt="CHAT" src="https://github.com/user-attachments/assets/1f0f0f43-4e6e-49bb-96be-fa69d4885f86" />

## Known limitations

- Gemini free tier enforces a daily request quota. Summary and fact extraction will return a fallback message when the quota is exhausted; chunk indexing and chat remain functional.
- Render free tier spins down after 15 minutes of inactivity. First request after a cold start takes 30–60 seconds.
- PDF text extraction requires selectable text. Scanned image-only PDFs will produce empty or partial results.
