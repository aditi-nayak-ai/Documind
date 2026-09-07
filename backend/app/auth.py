"""Stateless JWT auth.

Deliberately simple: bcrypt password hashing, a signed JWT carrying the
user id, and one FastAPI dependency (get_current_user) that routes
requiring auth depend on. No session store, no refresh tokens, no
revocation list -- a logout is purely client-side (drop the token; see
frontend/src/AuthContext.jsx's logout comment). That tradeoff means a
stolen token stays valid until it expires (jwt_expire_minutes in
config.py) with no way to force-invalidate it server-side; if that ever
matters for this project, the fix is a server-side revocation store
(e.g. a denylist of token IDs in Redis/Postgres checked on every
request), not a change to this file's basic shape.

get_current_user raises HTTPException(401) for every failure mode --
missing header, malformed token, expired token, forged signature, or a
token for a user that no longer exists -- and never any other status.
The frontend's axios interceptor (api.js) depends on that: any 401 means
"drop the token and show the login screen," and that's only safe to do
unconditionally if 401 is never used here to mean something else.
"""

import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.database import get_user_by_id

_bearer_scheme = HTTPBearer(auto_error=False)


def _require_secret_key() -> str:
    if not settings.jwt_secret_key:
        # Fails loudly at first use rather than silently signing/verifying
        # tokens with an empty (guaranteed-guessable) key. See MIGRATION.md
        # for the required JWT_SECRET_KEY environment variable.
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set it as an environment variable before starting the server."
        )
    return settings.jwt_secret_key


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, _require_secret_key(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Raises jwt exceptions on any failure -- expired, malformed, bad
    signature. Callers (get_current_user below) are responsible for
    turning those into the single HTTPException(401) this module
    guarantees; this function itself doesn't touch HTTP concerns."""
    return jwt.decode(token, _require_secret_key(), algorithms=[settings.jwt_algorithm])


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008 -- FastAPI's documented DI pattern
):
    """FastAPI dependency. Add `current_user=Depends(get_current_user)` to
    any route that must be authenticated. Returns the user dict from
    database.get_user_by_id on success; always raises HTTPException(401)
    on failure, never any other status (see module docstring for why
    that guarantee matters to the frontend)."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = get_user_by_id(int(payload["sub"]))
    if user is None:
        # Token is validly signed but the user it names no longer exists
        # (deleted account, etc.) -- still a 401, per this module's
        # single-failure-status guarantee, not a 404.
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user
