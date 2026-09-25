"""JWT auth with server-side session revocation.
 
bcrypt password hashing, a signed JWT carrying the user id, and one
FastAPI dependency (get_current_user) that routes requiring auth depend
on. Revocation is version-based, not a per-token denylist: users.token_
version increments on logout (database.increment_token_version), and
every JWT embeds the token_version that was current when it was issued
(the "tv" claim). get_current_user rejects any token whose "tv" doesn't
match the user's current token_version in the database -- so logout (or
any future "log out everywhere" action) invalidates that token, and every
other outstanding token for that user, immediately, without needing to
store or look up individual token IDs. The tradeoff: there's no way to
revoke a single device's session while leaving others logged in, since
there's no per-device/per-token identity being tracked, only a per-user
counter. If that ever matters, the fix is a real session table (one row
per issued token, with device info) rather than a change to this file's
basic shape.
 
get_current_user raises HTTPException(401) for every failure mode --
missing header, malformed token, expired token, forged signature, a
revoked token (stale token_version), or a token for a user that no longer
exists -- and never any other status. The frontend's axios interceptor
(api.js) depends on that: any 401 means "drop the token and show the
login screen," and that's only safe to do unconditionally if 401 is never
used here to mean something else.
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
 
 
# A real bcrypt hash of an arbitrary fixed string, used only to give
# login() something to hash-and-compare against when the email doesn't
# exist. bcrypt is deliberately slow (that's what makes it useful against
# offline cracking), so skipping it for unknown emails -- as `not user or
# not verify_password(...)` used to do, since `or` short-circuits -- made
# an unknown-email response measurably faster than a wrong-password one.
# That timing gap is enough to enumerate which emails are registered, even
# though the error text is identical either way. Comparing against this
# constant keeps both cases doing the same bcrypt work.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"not-a-real-password-just-for-timing", bcrypt.gensalt()).decode("utf-8")
 
 
def normalize_email(email: str) -> str:
    """Case-fold and trim an email before it touches the database or a
    password check. Without this, "User@Example.com" and
    "user@example.com" register as two different accounts, and a login
    attempt with different casing than the one used at registration fails
    even with the correct password."""
    return email.strip().lower()
 
 
def create_access_token(user_id: int, email: str, token_version: int = 0) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "tv": token_version,
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
 
 
def get_current_user(
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
    # payload.get(..., 0) rather than payload["tv"]: a token issued in the
    # few seconds before this check was deployed won't carry a "tv" claim
    # at all. Treating that as 0 matches token_version's DEFAULT 0 column,
    # so an in-flight token from just before a deploy isn't force-logged-out
    # by the deploy itself -- only an actual logout (increment_token_version)
    # invalidates it.
    if payload.get("tv", 0) != user["token_version"]:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user
