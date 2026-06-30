
import os
import json
import uuid
from pypdf import PdfReader
from google import genai
from google.genai import errors as genai_errors
from app.database import insert_chunk, search_chunks, save_document, get_document, get_document_by_filename
 
_client = None
 
MIN_EXTRACTED_CHARS = 100
 
 
def get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options={"api_version": "v1"}
        )
    return _client
 
 
class ChatEngine:
    def __init__(self):
        self.client = get_client()
 
    def _embed(self, text: str) -> list:
        try:
            response = self.client.models.embed_content(
                model="gemini-embedding-001",
                contents=text
            )
            return response.embeddings[0].values
        except genai_errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise RuntimeError("QUOTA_EXCEEDED")
            raise
 
    def _chunk_text(self, text: str, chunk_size: int = 500) -> list:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current = ""
        for para in paragraphs:
            if len(para) > chunk_size:
                # paragraph alone exceeds chunk_size — flush what we have,
                # then hard-split the paragraph itself instead of letting
                # it through as one oversized chunk
                if current:
                    chunks.append(current.strip())
                    current = ""
                for i in range(0, len(para), chunk_size):
                    chunks.append(para[i:i + chunk_size].strip())
                continue
            if len(current) + len(para) <= chunk_size:
                current += " " + para
            else:
                if current:
                    chunks.append(current.strip())
                current = para
        if current:
            chunks.append(current.strip())
        return chunks
 
    def _generate(self, prompt: str) -> str:
        try:
            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            return response.text
        except genai_errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise RuntimeError("QUOTA_EXCEEDED")
            raise
 
    def load_pdf(self, file, filename: str, force_reingest: bool = False) -> dict:
        # --- Dedup check: this is what actually saves quota, not session frequency ---
        # Re-uploading the same filename re-embeds every chunk and re-runs both
        # generation calls for no reason if we already have it indexed.
        if not force_reingest:
            existing = get_document_by_filename(filename)
            if existing:
                existing["reused"] = True
                return existing
 
        reader = PdfReader(file, strict=False)
        full_text = "".join(page.extract_text() or "" for page in reader.pages)
 
        # --- Empty/scanned PDF guard ---
        # pypdf returns "" silently for image-only or scanned PDFs. Without this
        # check the pipeline indexes near-nothing and reports 200 OK, and chat
        # later returns garbage with no indication of why.
        if len(full_text.strip()) < MIN_EXTRACTED_CHARS:
            raise ValueError(
                "Could not extract readable text from this PDF. "
                "It may be a scanned or image-only document — try a text-based PDF instead."
            )
 
        doc_id = str(uuid.uuid4())
        chunks = self._chunk_text(full_text)
 
        embedded_count = 0
        try:
            for chunk in chunks:
                embedding = self._embed(chunk)
                insert_chunk(chunk, embedding, doc_id)
                embedded_count += 1
        except RuntimeError as e:
            if "QUOTA_EXCEEDED" in str(e):
                if embedded_count == 0:
                    # Nothing was embedded — fail the whole upload cleanly.
                    raise RuntimeError("QUOTA_EXCEEDED") from e
                # Partial success: keep what embedded, tell the truth about the rest.
                # Document is searchable but incomplete — surfaced via the
                # 'partial' flag rather than pretending it's fully indexed.
                summary = (
                    f"Document partially indexed ({embedded_count}/{len(chunks)} chunks) — "
                    "Gemini embedding quota was reached mid-upload. Chat will only search "
                    "the indexed portion until you re-upload."
                )
                facts = ["Key facts unavailable — quota limit reached during indexing."]
                save_document(doc_id, filename, summary, json.dumps(facts), chunk_count=embedded_count)
                return {
                    "doc_id": doc_id,
                    "filename": filename,
                    "summary": summary,
                    "facts": facts,
                    "chunks": embedded_count,
                    "reused": False,
                    "partial": True,
                }
            raise
 
        # Embeddings are saved. Generation failures below are non-fatal.
        try:
            summary = self._generate(
                "Summarize this document in 3-4 sentences. Be concise and clear.\n\n"
                "Document:\n" + full_text[:3000] + "\n\nSummary:"
            )
        except RuntimeError as e:
            if "QUOTA_EXCEEDED" in str(e):
                summary = "Summary unavailable — Gemini quota limit reached. Your document has been indexed and chat will work once quota resets."
            else:
                raise
 
        try:
            facts_raw = self._generate(
                "Extract key facts from this document. Return a JSON array of strings.\n"
                "Each string is one key fact, date, name, or important number.\n"
                "Return ONLY the JSON array, nothing else.\n\n"
                "Document:\n" + full_text[:3000] + "\n\nFacts:"
            )
            facts_clean = facts_raw.strip().replace("```json", "").replace("```", "").strip()
            facts = json.loads(facts_clean)
        except RuntimeError as e:
            if "QUOTA_EXCEEDED" in str(e):
                facts = ["Key facts unavailable — Gemini quota limit reached."]
            else:
                raise
        except Exception:
            facts = [facts_raw]
 
        save_document(doc_id, filename, summary, json.dumps(facts), chunk_count=len(chunks))
        return {
            "doc_id": doc_id,
            "filename": filename,
            "summary": summary,
            "facts": facts,
            "chunks": len(chunks),
            "reused": False,
        }
 
    def ask(self, question: str, doc_id: str) -> str:
        query_embedding = self._embed(question)
        relevant_chunks = search_chunks(query_embedding, doc_id, top_k=3)
        if not relevant_chunks:
            return "No relevant content found for this document."
        context = "\n\n".join(relevant_chunks)
        prompt = (
            "You are a helpful assistant. Answer the question based only on the context below.\n"
            "Be specific and concise.\n\n"
            "Context:\n" + context + "\n\n"
            "Question: " + question + "\n\nAnswer:"
        )
        return self._generate(prompt)
 
    def get_document_info(self, doc_id: str) -> dict:
        return get_document(doc_id)
