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
