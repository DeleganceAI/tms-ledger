# Paranoy

The code behind Paranoy (this repo, tms-ledger; the domain, MCP tool names and TMS_* settings keep the old name so connected agents keep working).


A number-free epistemic ledger for humans and AI agents: signed evidence, claims, links and contradictions, without a server deciding what to believe. Every record is a NIP-01-shaped event signed with its author's Nostr key ([EVENTS.md](EVENTS.md) is the spec, [PLAN.md](PLAN.md) the build plan). Collections are private to their members. Agents use the MCP endpoint; people use the web pages with a NIP-07 browser extension.

## The Discipline

- **No confidence scales.** No probabilities, weights, or ordered confidence labels. Numbers inside statements are ordinary content; retrieval distances are not confidence.
- **Keep interpretation with readers.** Humans and AI agents decide what is believed or contested and whether a contradiction is open or resolved. The ledger neither stores nor derives those conclusions.
- **Show the reasons.** Every link cites a grounding evidence document, quotes it verbatim, and gives a specific reason. Contradictions name at least two distinct claims and explain their incompatibility.
- **Preserve history.** Records are append-only: corrections add records and evidence, never edit, delete, retire, or automatically replace earlier assertions.
- **Keep provenance explicit.** Every record is a signed event: the author's key signed exactly these bytes. The server records when it received each one. Whether a key is a human or an agent is self-declared in its profile, not verified.

The server enforces exactly two mechanical things beyond structure: a link's quote must occur in the evidence it cites, and a thinking proof may only cite records that exist. Neither is a judgement about what the records show.

## Layout

| Path | What |
|---|---|
| [EVENTS.md](EVENTS.md), [TERMS.md](TERMS.md) | Event kinds, acceptance rules, access; the one upload-rights clause users sign. |
| [ACCOUNTS.md](ACCOUNTS.md) | Proposed: open sign-up, free-account limits, and accounts of a person, their Ledger key and their agents. |
| [db/init.sql](db/init.sql) | `events` (the only signed table), views `evidence`, `claims`, `links`, `contradictions`, `contradiction_claims`, `profiles`, `members`, `collection_roster`, `collection_admins`, `stewards`; `collections`, `embeddings`, `auth_seen`, `mcp_calls`. Reference and quote triggers, append-only. [db/migrate_collection_admin.sql](db/migrate_collection_admin.sql) applies the role views to a database created before them. |
| [db/verify.sql](db/verify.sql) | Database-side guards on unsigned stand-in events. Rolls back. |
| [tms/events.py](tms/events.py) | NIP-01 IDs, BIP-340 signing (`coincurve`), per-kind content rules, the `tms-sign` CLI. |
| [tms/ledger.py](tms/ledger.py) | `publish(events)`, member-scoped reads, retrieval, fetch, embeddings, proof check, the connection pool. |
| [tms/server.py](tms/server.py) | MCP tools and prompts; signed-request verification; stdio or HTTP. |
| [tms/web.py](tms/web.py), [tms/web.html](tms/web.html) | `/`, `/submit`, `/c/<slug>/members`, `/c/<slug>/export.jsonl`, `/login`. |
| [tms/office.html](tms/office.html), [tms/office.py](tms/office.py) | The office ([OFFICE.md](OFFICE.md)): the logged-out home page and `/office`, driven by `/office.json`, anonymous slices of real collections and the last hour's events, recomputed hourly. |
| [tms/ui.py](tms/ui.py), [tms/ui.html](tms/ui.html) | `/dashboard`, behind the login cookie, scoped to your collections. |
| [tms/chat.py](tms/chat.py), [tms/chat.js](tms/chat.js) | The admin chat popup on every page: a read-only tool-calling agent over one collection, on DeepInfra; nothing stored. |
| [tms/admin.py](tms/admin.py) | `/admin` for admins: admins, DeepInfra spend (embeddings and chat), users, database size, events per day. |
| [DOCS.md](DOCS.md) | The user and agent guide, served at `/docs` and `/docs.md`. |
| [docs/bots/](docs/bots/README.md) | Templates for bots that collect evidence, mine claims, link them, look for gaps, argue for rejects, and manage a ledger. |
| [test_events.py](test_events.py), [check/](check/) | IDs and signatures cross-checked against `nostr-tools`. |
| [test_smoke.py](test_smoke.py) | Every PLAN.md test, against a scratch database it recreates. |
| [smoke_live.py](smoke_live.py) | Open and signed checks against a running service. |
| [Dockerfile](Dockerfile), [.do/app.yaml](.do/app.yaml) | DigitalOcean App Platform. |

## Setup

PostgreSQL with pgvector, `uv`, `pdftotext` (poppler), and an OpenAI-compatible embeddings endpoint (Ollama locally, DeepInfra in the cloud).

```bash
docker run -d --name tmsv2-pg -p 5432:5432 -e POSTGRES_DB=tmsv2 -e POSTGRES_USER=tmsv2 -e POSTGRES_PASSWORD=tmsv2 pgvector/pgvector:pg18
```

```bash
PGPASSWORD=tmsv2 psql -h localhost -U tmsv2 -d tmsv2 -v ON_ERROR_STOP=1 -f db/init.sql
```

```bash
brew install ollama poppler && ollama pull qwen3-embedding:8b
```

```bash
uv sync
```

Checks. The smoke test drops and recreates `tmsv2_smoke` (it refuses any name not ending in `_smoke`) and fakes embeddings:

```bash
uv run python test_smoke.py
```

```bash
(cd check && npm install) && uv run python test_events.py
```

Environment:

| Variable | What |
|---|---|
| `DATABASE_URL` | Postgres URL (`TMS_DATABASE_URL` also read; default the local container). In the cloud, the PgBouncer pool. |
| `TMS_APPROVED` | npubs or hex pubkeys the operator approves: no free-account limits, and they may name stewards. |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET` | Cloudflare Turnstile on extension sign-up and on every email code request (interaction-only, so usually invisible). Unset, sign-up isn't checked for bots and the server logs a warning. |
| `TURNSTILE_HOSTNAMES` | Optional. Hostnames a Turnstile token may come from, comma-separated. Unset, the host the request came to. Tokens must also carry the right action (`signup` or `email`). |
| `TMS_CONTACT` | Who the free-account limit message tells people to email (default `TMS_CONTACT_EMAIL`, then dustin@delegance.ai). |
| `TMS_ADMINS` | Site admins: npubs or hex pubkeys that may open `/admin` and add or remove admins there (the `admins` table). Added admins can do everything else; everyone else gets a 404. |
| `TMS_SECRET` | HMAC key for login cookies. Required over HTTP. |
| `TMS_NSEC` | stdio only: your key; tool calls without a `request` are signed with it. |
| `TMS_SERVER_NSEC` | The server's own key, which signs snapshot events and nothing else. |
| `EMBED_URL`, `EMBED_MODEL`, `EMBED_API_KEY` | Default `http://localhost:11434/v1`, `qwen3-embedding:8b`. DeepInfra: `https://api.deepinfra.com/v1/openai`, `Qwen/Qwen3-Embedding-8B`. Must return 4096 dimensions. |
| `RESEND_API_KEY`, `TMS_EMAIL_FROM`, `TMS_KEY_SECRET` | Email sign-in ([tms/email_login.py](tms/email_login.py)). Codes go out through Resend from `TMS_EMAIL_FROM` (default `Paranoy <login@mail.paranoy.org>`). `TMS_KEY_SECRET` encrypts the keys held for email accounts: **if it is lost, those keys are lost**, so back it up. Without both, email sign-in returns 503. `TMS_EMAIL_DEV=1` prints codes to the log instead of emailing them (local only). |
| `CHAT_MODEL`, `CHAT_URL`, `CHAT_API_KEY` | The admin chat popup. Default `deepseek-ai/DeepSeek-V4.1-Flash` on `https://api.deepinfra.com/v1/openai`; the key defaults to `EMBED_API_KEY`. `CHAT_PRICE_IN_PER_MTOK` / `CHAT_PRICE_OUT_PER_MTOK` (0.20 / 0.60 USD) price it on `/admin`. |
| `EMBED_PRICE_PER_MTOK` | USD per million embedding tokens for the spend shown on `/admin` (default 0.01). Local endpoints are logged at $0. |

## Keys and signing

Bots generate and hold their own keys:

```bash
uv run tms-sign keygen
```

```bash
TMS_NSEC=nsec1... uv run tms-sign event 4702 '{"collection": "mcas", "text": "..."}'
```

```bash
TMS_NSEC=nsec1... uv run tms-sign request search_claims '{"collection": "mcas", "text": "DAO"}'
```

Any Nostr library works too: the envelope is NIP-01 with `tags: []` and a JSON object in `content`. Before its first write, a key signs the current terms (kind 4706, `{"version": "1", "sha256": "<sha256 of TERMS.md>"}`) and, ideally, a profile (kind 0, saying in `about` whether it is a human or an agent). The operator approves a key with `TMS_APPROVED`; a collection's owner adds members on `/c/<slug>/members` (or by publishing a kind 4705 event). The owner can name admins (kind 4710) who may change members and the topic, and stewards (kind 4711) who may open new collections the owner owns (kind 4712). A plain member cannot.

## MCP

Over HTTP the endpoint is `<base>/mcp` (streamable HTTP) and open: anyone can list tools. `publish(events)` takes signed events. Every other tool takes one `request` argument, a kind 4707 event signed for that call, with content `{"tool": "<tool name>", "args": {...}}`; the server takes the arguments only from there, accepts it within 60 seconds of its clock, and only once. Over stdio (this project's [.mcp.json](.mcp.json)), set `TMS_NSEC` and call tools with plain arguments.

| Tool | Does |
|---|---|
| `publish` | A batch of signed events, all or nothing. Evidence, claims and the links between them can share a batch. Retries are no-ops. |
| `fetch_url` | A URL's plain text and title (PDF, HTML, JATS XML), ready to sign as evidence. Stores nothing. |
| `list_collections` | Your collections, with owner, admins, your role, members and counts. |
| `list_members` | One collection's roster and whether you may change members or admins. |
| `list_delegations` | Stewards you have named, and approved keys who have named you. |
| `get_event` | One event by id; evidence text pages with `offset`/`max_chars`. |
| `search_claims` | Vector or keyword retrieval in a collection, links and contradiction ids inlined. |
| `list_claims` | Claims with link counts, sorted `unsupported`, `unchallenged`, `contested`, `links` or `recent`. |
| `get_links`, `list_evidence`, `search_contradictions` | Filtered reads. `list_evidence(ungrounded_only=true)` is the claims-pass worklist. |
| `check_proof` | Validate a thinking proof and return it as a tree. |

Prompts: `briefing` (answer from one collection with a checked proof) and `claims_pass` (turn ungrounded evidence into claims, links and contradictions).

## Web

`/connect` (and `/` when logged in): connect with a NIP-07 extension, show the profile fetched from Damus and Primal (stored once you agree), sign the terms, list your collections, sign up (Turnstile), create a collection (one for a free account), and name stewards who may create collections for you. `/submit`: sign one evidence document plus claims and links from it. `/c/<slug>/members`: an owner or an admin signs the member list; the owner also signs the admin list. `/c/<slug>/export.jsonl`: every event in the collection; each line verifies on its own. `/dashboard`: activity, browse, agents and sources, limited to your collections. `/office` (and `/` when logged out): bots replay the last hour on boards that show anonymous slices of real collections, with global totals and a **Sign up** link. `/docs`: the full guide for people and agents ([DOCS.md](DOCS.md)). `/admin`: operator page for `TMS_ADMINS`, including free accounts with **Lift limits**. No limits = `TMS_ADMINS` + `TMS_APPROVED` (env, for bootstrapping) + the `approvals` table that Lift limits writes, so it needs no redeploy. Logging in signs a `login` request and sets a 12-hour HttpOnly cookie; writes are always signed in the browser.

## Deploy (DigitalOcean)

1. Create a managed PostgreSQL cluster `tms-db` with database and user `tms`, then enable pgvector and apply the schema (as `doadmin`, on the direct connection, not the pool):

   ```bash
   psql "$DIRECT_URL" -c "CREATE EXTENSION IF NOT EXISTS vector" -v ON_ERROR_STOP=1 -f db/init.sql
   ```

   Then grant the app's user access, if it isn't `doadmin`: `GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO tms; GRANT UPDATE, DELETE ON embeddings, auth_seen, mcp_calls TO tms; GRANT UPDATE ON access_requests TO tms; GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO tms;`
2. Create a connection pool `tms-pool` in **transaction** mode on database `tms` (size around 10):

   ```bash
   doctl databases pool create <cluster-id> tms-pool --db tms --user tms --mode transaction --size 10
   ```

3. Install the DigitalOcean GitHub app on [DeleganceAI/tms-ledger](https://github.com/DeleganceAI/tms-ledger), then create the app. App Platform builds the `Dockerfile` and redeploys on every push to `main`:

   ```bash
   doctl apps create --spec .do/app.yaml
   ```

   Set `TMS_SECRET`, `TMS_APPROVED`, `TMS_ADMINS`, `TMS_SERVER_NSEC` and `EMBED_API_KEY` on the app, and add the app to the cluster's trusted sources.
   The app answers at https://tms.delegance.ai (the `domains` entry; DigitalOcean manages the zone) and at its `ondigitalocean.app` URL. Pushes to `main` redeploy only if the DigitalOcean GitHub app has access to the repo; otherwise run `doctl apps create-deployment <app-id>`.
4. Check it:

   ```bash
   TMS_NSEC=nsec1... uv run python smoke_live.py https://tms.delegance.ai
   ```

## Thinking proofs

A proof is the answering agent's argument standing on ledger records. It lives outside the ledger, saved as JSON next to the answer.

```json
{"question": "Is DAO deficiency the cause of histamine intolerance?",
 "steps": [
  {"id": "s1", "say": "Several reviews propose DAO deficiency as a mechanism.", "from": ["<claim event id>", "<link event id>"]},
  {"id": "s2", "say": "One review qualifies this: assays correlate poorly with symptoms.", "from": ["<link event id>"]},
  {"id": "s3", "say": "Nothing in the collection covers pediatric cases.", "from": [], "gap": true},
  {"id": "root", "say": "Proposed mechanism, not an established cause.", "from": ["s1", "s2", "s3"]}
 ]}
```

`check_proof` enforces three rules: every `from` is an event in this collection or an earlier step; exactly one root; every step has a ledger event in its ancestry or is marked `gap`. A gap is the agent saying out loud that it is speaking without the ledger.
