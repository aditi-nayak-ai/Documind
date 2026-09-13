# DocuMind

A full-stack RAG application that lets you upload a PDF, get an instant AI-generated summary and key facts, and chat with the document using natural language — with per-account authentication so each user's documents are private.

**Live demo:** [documind-murex.vercel.app](https://documind-murex.vercel.app)

## How it works
Register/Login (JWT auth)
→ PDF Upload
→ Text extraction (pypdf)
→ Word-safe chunking with overlap (500 char windows)
→ Embedding each chunk (gemini-embedding-001, 3072 dimensions)
→ Stored in pgvector (Neon PostgreSQL), scoped to the uploading user

→ User Question
→ Embed question (gemini-embedding-001)
→ Cosine similarity search → top 3 chunks retrieved
→ Chunks + question sent to gemini-3.6-flash
→ Answer returned to chat UI

Every document is tied to the account that uploaded it — another user cannot read, query, or discover it, even with the correct document ID.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite |
| Backend | FastAPI, Python 3.11 |
| Auth | JWT (PyJWT) + bcrypt password hashing |
| Embeddings | Gemini Embedding API (`gemini-embedding-001`, 3072-dim) |
| LLM | Google Gemini (`gemini-3.6-flash`) |
| Vector store | PostgreSQL + pgvector (Neon), HNSW index via `halfvec` cast |
| Deployment | Render (backend), Vercel (frontend) |
| CI/CD | GitHub Actions — tests + lint gated on every push, real pgvector service container |
| Testing | pytest, 62 tests, 80%+ coverage, integration tests against real Postgres (not mocked) |

## Testing & CI/CD

This isn't just a working script — it's built and verified the way a team project would be:

- **62 automated tests** covering PDF chunking edge cases, quota/error classification, real database integration (pgvector cosine search, HNSW indexing, user-scoped access control), and full API request/response cycles
- Database tests run against **real pgvector**, not a mock — catching issues (dimension limits, index behavior, SQL correctness) a mocked layer would miss
- **Cross-user isolation is explicitly tested**: two accounts upload documents, and the test asserts one user gets a clean 404 trying to access the other's document by ID
- CI (`.github/workflows/ci.yml`) spins up a `pgvector/pgvector:pg16` service container, runs the full suite, then gates linting (`ruff`) on tests passing
- Structured JSON logging with per-request correlation IDs, plus `/health` (real DB connectivity check) and `/stats` (operational metrics) endpoints for observability

## Project structure
Documind/
├── backend/
│ ├── app/
│ │ ├── api.py # FastAPI routes: auth, /ingest, /query, /document, /health, /stats
│ │ ├── auth.py # JWT issuing/verification, bcrypt hashing, get_current_user dependency
│ │ ├── rag_service.py # Orchestration: load_pdf, ask — the actual RAG pipeline
│ │ ├── pdf_extraction.py # Text extraction + word-safe chunking (pure functions)
│ │ ├── embeddings.py # Gemini embedding calls, batch/per-chunk fallback
│ │ ├── llm.py # Gemini text generation
│ │ ├── gemini_client.py # Shared client, quota/transient-error classification, retry logic
│ │ ├── exceptions.py # QuotaError, TransientServerError, ExtractionError
│ │ ├── database.py # SQLAlchemy engine, pgvector queries, user-scoped document access
│ │ ├── config.py # Centralized typed settings (pydantic-settings)
│ │ ├── logging_config.py # Structured JSON logging with request-ID correlation
│ │ ├── metrics.py # In-memory operational counters
│ │ └── chat_engine.py # Backward-compatible facade over the above
│ ├── tests/ # 62 tests: unit, integration (real pgvector), API-level
│ └── requirements.txt
└── frontend/
├── src/
│ ├── App.jsx
│ ├── AuthContext.jsx # Auth state, token storage, 401 handling
│ ├── api.js # Shared axios instance with auth interceptor
│ └── components/
│ ├── AuthPage.jsx
│ ├── UploadZone.jsx
│ ├── SummaryPanel.jsx
│ ├── FactsPanel.jsx
│ └── ChatWindow.jsx
└── vite.config.js

## Local setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL instance with the `pgvector` extension (a Neon free-tier database works)
- Google AI Studio API key

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # includes test dependencies
uvicorn app.api:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Running tests locally
```bash
cd backend
pytest   # requires a Postgres instance with pgvector — see tests/conftest.py
```

## Environment variables

**Backend** — set in Render's dashboard or a local `.env` file (never commit this):
**Backend** — set in Render's dashboard or a local `.env` file (never commit this):

DATABASE_URL=postgresql://...
GEMINI_API_KEY=...
JWT_SECRET_KEY=... # generate with: python -c "import secrets; print(secrets.token_hex(32))"
ALLOWED_ORIGINS=https://your-frontend.vercel.app


**Frontend** — set in Vercel's dashboard or a local `.env.local` file:

VITE_BACKEND_URL=https://your-render-service.onrender.com


## API endpoints

| Method | Endpoint | Auth required | Description |
|---|---|---|---|
| POST | `/auth/register` | No | Create an account, returns a JWT |
| POST | `/auth/login` | No | Log in, returns a JWT |
| GET | `/auth/me` | Yes | Current user's info |
| POST | `/ingest` | Yes | Upload a PDF. Returns summary, facts, chunk count |
| POST | `/query` | Yes | Ask a question about a document you own |
| GET | `/document/{doc_id}` | Yes | Retrieve a document's saved summary/facts |
| GET | `/health` | No | Server + database connectivity status |
| GET | `/stats` | No | Operational metrics (request/error counts) |

### Example

```bash
# Register
curl -X POST https://your-backend.onrender.com/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "a-real-password-8plus"}'
# → {"access_token": "...", "token_type": "bearer"}

# Upload (requires the token from above)
curl -X POST https://your-backend.onrender.com/ingest \
  -H "Authorization: Bearer <token>" \
  -F "file=@document.pdf"

# Query
curl -X POST https://your-backend.onrender.com/query \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the main argument?", "doc_id": "<doc_id-from-ingest-response>"}'
```

## Screenshots

**Login**
![Login](./screenshots/login.png)

**Upload a PDF**
![Upload](./screenshots/upload.png)

**Chat**
![Chat](./screenshots/chat.png)

## Known limitations

- **Text-based PDFs only** — extraction uses `pypdf`'s text layer; scanned or image-only PDFs (no embedded text) are rejected outright with a clear error, rather than silently returning garbage. No OCR is implemented yet.
- **Tables lose their structure** — text inside tables is extracted, but row/column relationships aren't preserved, so table data can appear jumbled to the LLM.
- **Summary/facts are based on the first ~15,000 characters** of longer documents (chat, however, searches the full document via embeddings regardless of length) — the response explicitly flags this when it applies.
- **Gemini's free tier** enforces both per-minute and daily quotas. Per-minute limits are retried automatically with backoff; daily limits and transient 503 (Google infra overload) errors degrade gracefully — chunks stay indexed and chat keeps working even if summary/fact generation fails, and a later re-upload automatically retries just the summary/facts if the earlier attempt failed.
- **Render's free tier** spins the backend down after 15 minutes of inactivity; the first request after that takes 30-60 seconds to cold-start.
