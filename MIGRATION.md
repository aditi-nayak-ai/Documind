# Migrating your live database to the auth-enabled schema

You already have `Documind-main` deployed against a real Neon Postgres
database with real rows in `documents` / `document_chunks`. This update
adds authentication, and every document now needs an owner (`user_id`).
Read this before you deploy — it changes what's reachable through the API.

## What happens automatically

`init_db()` runs on every app startup (see `app/database.py`) and is
written to be safe against a database that already has data:

- `CREATE TABLE IF NOT EXISTS users ...` — new, empty until people register.
- `ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id INTEGER
  REFERENCES users(id)` — added as **nullable**. Existing rows get
  `user_id = NULL`. Nothing is deleted, nothing errors.
- `CREATE TABLE IF NOT EXISTS user_usage ...` — new, empty.

So the deploy itself won't crash and won't destroy data. The part that
needs your decision is below.

## What actually changes for your existing documents

Every route that touches a document now filters `WHERE user_id =
:current_user_id` in the SQL itself. A row with `user_id = NULL` matches
**no** authenticated user's id — `NULL = 5` is `NULL`, not `true`, in SQL.
So immediately after this deploys, every document you uploaded before
this update becomes invisible through `/document/{doc_id}` and
unqueryable through `/query`, for every account, including one you
register yourself.

This is the safe default, not a bug: the alternative (leaving old rows
readable by anyone) would mean the first thing this migration does is
fail to actually protect anything. Orphaning them is deliberate. The
rows and their embedded chunks are still in Postgres — just unreachable
via the API until you re-upload or backfill (below).

## Option A — do nothing (recommended if these were demo/test uploads)

Deploy, register a real account, re-upload the PDFs you care about. The
orphaned rows sit in Neon until you clean them up (query at the bottom).

## Option B — backfill old documents to a specific account

Do this only after registering the account through `/auth/register`,
since the backfill needs a real `users.id` to point at.

1. Deploy this update. Confirm `GET /health` returns 200.
2. Register the account you want to own the old documents:
```bash
   curl -X POST https://your-backend.onrender.com/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email": "you@example.com", "password": "a-real-password-8plus-chars"}'
```
3. In Neon's SQL editor (or `psql`):
```sql
   SELECT id, email FROM users WHERE email = 'you@example.com';
   UPDATE documents SET user_id = 1 WHERE user_id IS NULL;  -- use the real id
```
4. Verify by hitting `/document/{doc_id}` for an old doc_id with that
   account's token — should now return 200 instead of 404.

**Caveat**: this assigns ALL orphaned documents to ONE account. There's
no way to reconstruct per-user ownership that was never captured
pre-auth — check `documents.filename` / `created_at` in Neon first if
that distinction matters to you.

## Optional cleanup — deleting orphaned rows

```sql
SELECT doc_id, filename, created_at FROM documents WHERE user_id IS NULL;  -- preview first

DELETE FROM document_chunks
  WHERE document_name IN (SELECT doc_id FROM documents WHERE user_id IS NULL);
DELETE FROM documents WHERE user_id IS NULL;
```

## Required new environment variable

Add to Render's environment variables for the backend service:

```
JWT_SECRET_KEY=<generate one>
```

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

If unset, `app/auth.py` raises a `RuntimeError` on the first
login/register attempt rather than silently signing tokens with a
guessable key.

Optional, with defaults if skipped (`app/config.py`):
