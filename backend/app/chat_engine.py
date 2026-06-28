import os
import json
from pypdf import PdfReader
from google import genai
from app.database import insert_chunk, search_chunks, save_document, get_document, clear_document

_client = None


def get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client


class ChatEngine:
    def __init__(self):
        self.client = get_client()

    def _embed(self, text: str) -> list:
        response = self.client.models.embed_content(
            model="text-embedding-004",
            contents=text
        )
        return response.embeddings[0].values

    def _chunk_text(self, text: str, chunk_size: int = 500) -> list:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current = ""
        for para in paragraphs:
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
        response = self.client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        return response.text

    def load_pdf(self, file, filename: str) -> dict:
        reader = PdfReader(file, strict=False)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() or ""

        chunks = self._chunk_text(full_text)
        clear_document(filename)

        for chunk in chunks:
            embedding = self._embed(chunk)
            insert_chunk(chunk, embedding, filename)

        summary = self._generate(
            "Summarize this document in 3-4 sentences. Be concise and clear.\n\n"
            "Document:\n" + full_text[:3000] + "\n\nSummary:"
        )

        facts_raw = self._generate(
            "Extract key facts from this document. Return a JSON array of strings.\n"
            "Each string is one key fact, date, name, or important number.\n"
            "Return ONLY the JSON array, nothing else.\n\n"
            "Document:\n" + full_text[:3000] + "\n\nFacts:"
        )

        try:
            facts_clean = facts_raw.strip().replace("```json", "").replace("```", "").strip()
            facts = json.loads(facts_clean)
        except Exception:
            facts = [facts_raw]

        save_document(filename, summary, json.dumps(facts))
        return {"summary": summary, "facts": facts, "chunks": len(chunks)}

    def ask(self, question: str, filename: str) -> str:
        query_embedding = self._embed(question)
        relevant_chunks = search_chunks(query_embedding, filename, top_k=3)
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

    def get_document_info(self, filename: str) -> dict:
        return get_document(filename)
