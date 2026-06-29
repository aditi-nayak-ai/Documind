import os
import json
import uuid
from pypdf import PdfReader
from google import genai
from google.genai import errors as genai_errors
from app.database import insert_chunk, search_chunks, save_document, get_document, clear_document

_client = None

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
        response = self.client.models.embed_content(
            model="gemini-embedding-001",
            contents=text
        )
        return response.embeddings[0].values

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

    def load_pdf(self, file, filename: str) -> dict:
        doc_id = str(uuid.uuid4())

        reader = PdfReader(file, strict=False)
        full_text = "".join(page.extract_text() or "" for page in reader.pages)

        chunks = self._chunk_text(full_text)
        clear_document(doc_id)
        for chunk in chunks:
            embedding = self._embed(chunk)
            insert_chunk(chunk, embedding, doc_id)

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

        save_document(doc_id, filename, summary, json.dumps(facts))
        return {"doc_id": doc_id, "filename": filename, "summary": summary, "facts": facts, "chunks": len(chunks)}

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
