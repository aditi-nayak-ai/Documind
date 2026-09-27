from google.genai import errors as genai_errors
 
from app.gemini_client import call_with_retry, classify_gemini_error, get_client
 
 
def generate(prompt: str) -> str:
    client = get_client()
 
    def call():
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
            )
            return response.text
        except genai_errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise classify_gemini_error(e)
            raise
        except genai_errors.ServerError as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                raise classify_gemini_error(e)
            raise
 
    return call_with_retry(call)
 
 
def generate_stream(prompt: str):
    """Same call as generate(), but yields text pieces as they arrive
    instead of waiting for the full response. No retry wrapper here --
    once the first chunk has been sent to the client, the response has
    already started, so a mid-stream failure can't be silently retried
    the way a pre-stream one can. The caller (rag_service.ask_stream)
    is responsible for handling an error that surfaces after streaming
    has begun.
    """
    client = get_client()
    try:
        for chunk in client.models.generate_content_stream(
            model="gemini-3.6-flash",
            contents=prompt,
        ):
            if chunk.text:
                yield chunk.text
    except genai_errors.ClientError as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            raise classify_gemini_error(e)
        raise
    except genai_errors.ServerError as e:
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            raise classify_gemini_error(e)
        raise
