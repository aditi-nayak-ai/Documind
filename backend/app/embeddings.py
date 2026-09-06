from google.genai import errors as genai_errors

from app.gemini_client import call_with_retry, classify_quota_error, get_client

EMBED_BATCH_SIZE = 20  # chunks per embed_content call; keeps request size modest
                        # since each chunk is already capped at 500 chars


def embed_one(text: str) -> list:
    client = get_client()

    def call():
        try:
            response = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text,
            )
            return response.embeddings[0].values
        except genai_errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise classify_quota_error(e)
            raise

    return call_with_retry(call)


def embed_batch(texts: list) -> list:
    """Embed multiple chunks in one API call instead of one call per chunk.

    The Gemini SDK is documented to accept a list of strings and return
    one embedding per string, but there are unresolved reports of it
    instead collapsing the list into a single embedding. Rather than
    trust either behavior blindly, this checks that the response
    actually has one embedding per input text before using it -- if the
    count doesn't match, it falls back to embedding the batch one at a
    time so chunks and vectors never get silently mismatched.
    """
    client = get_client()

    def call():
        try:
            response = client.models.embed_content(
                model="gemini-embedding-001",
                contents=texts,
            )
            return response.embeddings
        except genai_errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise classify_quota_error(e)
            raise

    embeddings = call_with_retry(call)

    if not embeddings or len(embeddings) != len(texts):
        print(
            f"WARN: batch embed returned {len(embeddings) if embeddings else 0} "
            f"embeddings for {len(texts)} inputs — falling back to per-chunk calls."
        )
        return [embed_one(t) for t in texts]

    return [e.values for e in embeddings]
