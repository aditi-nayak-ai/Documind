import os
import json
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from google import genai
from app.database import init_db, insert_chunk, search_chunks, save_document, get_document, clear_document

embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

class ChatEngine:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        init_db()

    def _embed(self, text: str) -> list:
        arr = embedding_model.encode(text, normalize_embeddings=True)
        return arr.tolist()

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
            model="gemini-1.5-flash",
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

        summary = self._generate(f"""
Summarize this document in 3-4 sentences. Be concise and clear.

Document:
{full_text[:3000]}

Summary:""")

        facts_raw = self._generate(f"""
Extract key facts from this document. Return a JSON array of strings.
Each string is one key fact, date, name, or important number.
Return ONLY the JSON array, nothing else.

Document:
{full_text[:3000]}

Facts:""")

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
        prompt = f"""You are a helpful assistant. Answer the question based only on the context below.
Be specific and concise.

Context:
{context}

Question: {question}

Answer:"""
        return self._generate(prompt)

    def get_document_info(self, filename: str) -> dict:
        return get_document(filename)
