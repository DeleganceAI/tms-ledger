# Signed-events build plan (draft)

Implements [EVENTS.md](EVENTS.md). Target: DigitalOcean App Platform plus DO managed PostgreSQL, for a handful of users. Nothing is migrated: the cloud database starts empty, and agents re-upload.

## Deployment shape

| Piece | Where |
|---|---|
| `tms` service (MCP + web + dashboard, one process) | App Platform web service, built from a `Dockerfile` (needs `poppler-utils` for `pdftotext`) |
| Database | DO managed PostgreSQL with `vector`, reached through a DO connection pool |
| Embeddings | DeepInfra `Qwen/Qwen3-Embedding-8B` (OpenAI-compatible); Ollama stays as the local option |
| Daily snapshot | App Platform scheduled job, same image |

Environment variables: `DATABASE_URL` (the pool's URL), `TMS_SERVER_NSEC` (signs snapshots), `TMS_SECRET` (HMAC for cookies), `EMBED_URL`, `EMBED_API_KEY`, `TMS_APPROVED` (pubkeys the operator approves; they can also create collections), `TMS_SNAPSHOT_RECIPIENT` (age public key).

## Auth

Specified in EVENTS.md sections 3, 4 (`request`) and 6.

- **MCP endpoint is open.** Anyone can list the tools, and there's no shared `TMS_TOKEN`.
- **Writes:** `publish(events)` takes signed events, which are their own proof.
- **Other tools:** each takes one `request` argument, a kind-4707 event with content `{tool, args}`, signed fresh for each call. The server checks that:
  - the signature verifies;
  - `tool` matches the tool being called;
  - `created_at` is within 60 seconds;
  - the `id` is new. It's inserted into `auth_seen` (primary key, rows older than 2 minutes cleaned up), so a replay fails.

  It then reads the args from the signed content. Because it's a tool argument, this works with any MCP client.
- **Who gets in:** pubkeys in `TMS_APPROVED`, plus any member of any collection. Owners add members without operator approval. Only approved pubkeys create collections.
- **Browser:** signs one `request` with `tool: "login"` and gets a signed HttpOnly cookie, valid for 12 hours, holding an HMAC of the pubkey and expiry. Writes are still signed one event at a time.
- **stdio** (local Claude Code): if `request` is omitted, the server signs it with `TMS_NSEC`, so local use needs no signing step.

## Database access

- `psycopg_pool.ConnectionPool` in the app (min 1, max 10 per instance), pointed at a DO PgBouncer pool in **transaction mode**.
- `prepare_threshold=None`, because server-side prepared statements break under transaction pooling.
- No session state is used anywhere: every batch runs inside one transaction, and there is no `SET` outside `SET LOCAL`, no `LISTEN`, and no advisory locks.
- The scheduled job and the local tools go through the same pool.

## Storage (once)

- `events` is the only table that stores anything signed: `id`, `pubkey`, `kind`, `created_at`, `content`, `sig`, `received_at`, `collection`.
- `evidence`, `claims`, `links`, `contradictions` and `contradiction_claims` are views over `events`.
- `collections` (`slug`, `owner`) is written by the first event that uses a slug.
- `index_entries` (`event_id`, `kind`, `model`, `dimensions`, `vector`) holds derived indexes and isn't signed. `kind = 'embedding'` is the first kind. The ledger tables have no embedding columns.
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
   - Request verification as above.
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
- a replayed request is rejected;
- a stale request is rejected;
- a request signed for one tool and sent to another is rejected;
- an unapproved non-member gets nothing;
- a member added by an owner gets in without approval.

## Open questions

1. **Filecoin provider:** Storacha or Lighthouse? Either needs an account. Decided at the end, in phase 8; nothing before it depends on this.
