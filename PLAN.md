# Signed-events build plan (draft)

Implements [EVENTS.md](EVENTS.md). Target: DigitalOcean App Platform plus DO managed PostgreSQL, for a handful of users. Nothing is migrated: the cloud database starts empty, and agents re-upload.

## Deployment shape

| Piece | Where |
|---|---|
| `tms` service (MCP + web + dashboard, one process) | App Platform web service, built from a `Dockerfile` (needs `poppler-utils` for `pdftotext`) |
| Database | DO managed PostgreSQL with `vector`, reached through a DO connection pool |
| Embeddings | DeepInfra `Qwen/Qwen3-Embedding-8B` (OpenAI-compatible); Ollama stays as the local option |
| Daily snapshot | App Platform scheduled job, same image |

Environment variables: `DATABASE_URL` (the pool's URL), `TMS_SERVER_NSEC` (signs snapshots), `TMS_SECRET` (HMAC for cookies), `EMBED_URL`, `EMBED_API_KEY`, `TMS_CREATORS` (pubkeys allowed to create collections), `TMS_SNAPSHOT_RECIPIENT` (age public key).

## Auth (proposal, see open question 1)

Every request carries proof of a key:

- **Bots and MCP:** each HTTP request carries `Authorization: Nostr <base64 auth event>`, an event of kind 4707 whose content is `{"url", "method", "body_sha256"}`. The server checks that:
  - the signature is valid;
  - `created_at` is within 60 seconds of server time;
  - the URL, method and body hash match the request;
  - the event ID hasn't been seen before. The `auth_seen` table has the ID as its primary key, so a replay fails on insert, and rows older than 2 minutes are cleaned up.

  Binding the body hash means a captured header can't be reused with a different request, and the seen-ID check stops it being reused with the same one.
- **Browser:** signing every page load or every click would mean an extension prompt each time. Instead, the browser signs one auth event for `POST /login` and gets back a signed HttpOnly cookie, valid for 12 hours and holding an HMAC of the pubkey and expiry. Writes are still signed one event at a time.
- This replaces the challenge-based `login` event in EVENTS.md once agreed.
- **Writes** are signed record by record whatever the transport, so the auth layer only decides who can **read**.
- **stdio** (local Claude Code) takes its pubkey from `TMS_NSEC`, signs locally, and sees only that key's collections.

## Database access

- `psycopg_pool.ConnectionPool` in the app (min 1, max 10 per instance), pointed at a DO PgBouncer pool in **transaction mode**.
- `prepare_threshold=None`, because server-side prepared statements break under transaction pooling.
- No session state is used anywhere: every batch runs inside one transaction, and there is no `SET` outside `SET LOCAL`, no `LISTEN`, and no advisory locks.
- The scheduled job and the local tools go through the same pool.

## Storage (once)

- `events` is the only table that stores anything signed: `id`, `pubkey`, `kind`, `created_at`, `content`, `sig`, `received_at`, `collection`.
- `evidence`, `claims`, `links`, `contradictions` and `contradiction_claims` are views over `events`.
- `collections` (`slug`, `owner`) is written by the first event that uses a slug.
- `embeddings` (`event_id`, `vector`, `model`) holds derived data and isn't signed.
- Expression indexes cover full-text search and lookups by collection, kind and reference.
- Operational tables, which aren't ledger data and are allowed to change: `mcp_calls`, `auth_seen`.

## Phases

Each phase is committed locally after its check passes.

1. **Signing core.** `tms/events.py`:
   - NIP-01 serialization and event ID;
   - BIP-340 signing and verification with `coincurve`;
   - per-kind content validation;
   - the `tms-sign` CLI.

   Check: event IDs and signatures match `nostr-tools` on Unicode and control characters.
2. **Schema.** A new `db/init.sql` with the tables and views above, append-only triggers on `events`, and the quote check on link inserts. A new `db/verify.sql`.
3. **Ledger.**
   - `publish(events)` applies all acceptance rules in one transaction, then embeds the claims through DeepInfra.
   - Reads are limited to the caller's collections.
   - `check_proof` looks records up by event ID.
   - The connection pool moves in here.
4. **Server.**
   - Tools: `publish`, `fetch_url` and the renamed reads.
   - The auth middleware above.
   - `/login`, which sets the cookie.
   - Rewritten `claims_pass` and `briefing` prompts.
   - `mcp_calls` logs the pubkey.
5. **Web.**
   - `/`: connect, fetch the profile from Damus and Primal, sign the terms if needed.
   - `/submit`.
   - `/c/<slug>/members` (owner only).
   - `/c/<slug>/export.jsonl`.
6. **Dashboard, served.**
   - It moves to `/dashboard` behind the login cookie.
   - Every query is filtered to the viewer's collections, including `mcp_calls` rows by collection. Calls with no collection are shown only to the key that made them.
   - The Sources tab groups evidence by its `source` field instead of the dropped table.
7. **Deploy.**
   - The `Dockerfile` and an app spec (`.do/app.yaml`) with the service and the job.
   - Setup: enable `vector` and create the pool.
   - A smoke test against the live URL.
8. **Snapshot job.** Export every event as JSONL (embeddings excluded), encrypt it with `age` to `TMS_SNAPSHOT_RECIPIENT`, upload it to Filecoin, and publish a `snapshot` event. The server holds only the public key, so it can't read its own backups; you keep the private key offline.

**Tests** (`test_smoke.py`, run against a local Postgres):
- a signed batch is accepted;
- a bad quote rolls back the whole batch;
- a tampered signature is rejected;
- a non-member write is rejected;
- a write from a key that hasn't signed the terms is rejected;
- a duplicate ID is a no-op;
- a replayed auth header is rejected;
- a stale auth header is rejected;
- an auth header whose body hash doesn't match is rejected.

## Open questions

1. **Can the bots' MCP clients sign each request?** Per-request signing needs code that adds a fresh header to every HTTP request. Hosted MCP connectors, and most MCP clients including Claude Code, send fixed headers only. If any bot is in that position, it also needs the login token, and then the header becomes a bearer token that expires.
2. **Who can create collections?** Anyone who signs the terms, or only the keys in `TMS_CREATORS`? Default: `TMS_CREATORS`, since a new user would otherwise be able to create collections without limit.
3. **Filecoin provider:** Storacha or Lighthouse? Either needs an account.
