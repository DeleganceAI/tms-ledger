# tmsv2

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
| [db/init.sql](db/init.sql) | `events` (the only signed table), views `evidence`, `claims`, `links`, `contradictions`, `contradiction_claims`, `profiles`, `members`; `collections`, `embeddings`, `auth_seen`, `mcp_calls`. Reference and quote triggers, append-only. |
| [db/verify.sql](db/verify.sql) | Database-side guards on unsigned stand-in events. Rolls back. |
| [tms/events.py](tms/events.py) | NIP-01 IDs, BIP-340 signing (`coincurve`), per-kind content rules, the `tms-sign` CLI. |
| [tms/ledger.py](tms/ledger.py) | `publish(events)`, member-scoped reads, retrieval, fetch, embeddings, proof check, the connection pool. |
| [tms/server.py](tms/server.py) | MCP tools and prompts; signed-request verification; stdio or HTTP. |
| [tms/web.py](tms/web.py), [tms/web.html](tms/web.html) | `/`, `/submit`, `/c/<slug>/members`, `/c/<slug>/export.jsonl`, `/login`. |
| [tms/ui.py](tms/ui.py), [tms/ui.html](tms/ui.html) | `/dashboard`, behind the login cookie, scoped to your collections. |
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
| `TMS_APPROVED` | npubs or hex pubkeys the operator approves. Only they create collections. |
| `TMS_SECRET` | HMAC key for login cookies. Required over HTTP. |
| `TMS_NSEC` | stdio only: your key; tool calls without a `request` are signed with it. |
| `TMS_SERVER_NSEC` | The server's own key, which signs snapshot events and nothing else. |
| `EMBED_URL`, `EMBED_MODEL`, `EMBED_API_KEY` | Default `http://localhost:11434/v1`, `qwen3-embedding:8b`. DeepInfra: `https://api.deepinfra.com/v1/openai`, `Qwen/Qwen3-Embedding-8B`. Must return 4096 dimensions. |

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

Any Nostr library works too: the envelope is NIP-01 with `tags: []` and a JSON object in `content`. Before its first write, a key signs the current terms (kind 4706, `{"version": "1", "sha256": "<sha256 of TERMS.md>"}`) and, ideally, a profile (kind 0, saying in `about` whether it is a human or an agent). The operator approves a key with `TMS_APPROVED`; a collection's owner adds members on `/c/<slug>/members` (or by publishing a kind 4705 event).

## MCP

Over HTTP the endpoint is `<base>/mcp` (streamable HTTP) and open: anyone can list tools. `publish(events)` takes signed events. Every other tool takes one `request` argument, a kind 4707 event signed for that call, with content `{"tool": "<tool name>", "args": {...}}`; the server takes the arguments only from there, accepts it within 60 seconds of its clock, and only once. Over stdio (this project's [.mcp.json](.mcp.json)), set `TMS_NSEC` and call tools with plain arguments.

| Tool | Does |
|---|---|
| `publish` | A batch of signed events, all or nothing. Evidence, claims and the links between them can share a batch. Retries are no-ops. |
| `fetch_url` | A URL's plain text and title (PDF, HTML, JATS XML), ready to sign as evidence. Stores nothing. |
| `list_collections` | Your collections, with owner, members and counts. |
| `get_event` | One event by id; evidence text pages with `offset`/`max_chars`. |
| `search_claims` | Vector or keyword retrieval in a collection, links and contradiction ids inlined. |
| `list_claims` | Claims with link counts, sorted `unsupported`, `unchallenged`, `contested`, `links` or `recent`. |
| `get_links`, `list_evidence`, `search_contradictions` | Filtered reads. `list_evidence(ungrounded_only=true)` is the claims-pass worklist. |
| `check_proof` | Validate a thinking proof and return it as a tree. |

Prompts: `briefing` (answer from one collection with a checked proof) and `claims_pass` (turn ungrounded evidence into claims, links and contradictions).

## Web

`/`: connect with a NIP-07 extension, show the profile fetched from Damus and Primal (stored once you agree), sign the terms, list your collections, create one (approved keys). `/submit`: sign one evidence document plus claims and links from it. `/c/<slug>/members`: owner only. `/c/<slug>/export.jsonl`: every event in the collection; each line verifies on its own. `/dashboard`: activity, browse, agents and sources, limited to your collections. Logging in signs a `login` request and sets a 12-hour HttpOnly cookie; writes are always signed in the browser.

## Deploy (DigitalOcean)

1. Create a managed PostgreSQL cluster `tms-db` with database and user `tms`, then enable pgvector and apply the schema (as `doadmin`, on the direct connection, not the pool):

   ```bash
   psql "$DIRECT_URL" -c "CREATE EXTENSION IF NOT EXISTS vector" -v ON_ERROR_STOP=1 -f db/init.sql
   ```

   Then grant the app's user access, if it isn't `doadmin`: `GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO tms; GRANT UPDATE, DELETE ON embeddings, auth_seen, mcp_calls TO tms; GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO tms;`
2. Create a connection pool `tms-pool` in **transaction** mode on database `tms` (size around 10):

   ```bash
   doctl databases pool create <cluster-id> tms-pool --db tms --user tms --mode transaction --size 10
   ```

3. Build and push the image, then create the app:

   ```bash
   docker buildx build --platform linux/amd64 -t registry.digitalocean.com/<registry>/tms:latest --push .
   ```

   ```bash
   doctl apps create --spec .do/app.yaml
   ```

   Set `TMS_SECRET`, `TMS_APPROVED`, `TMS_SERVER_NSEC` and `EMBED_API_KEY` on the app, and add the app to the cluster's trusted sources.
4. Check it:

   ```bash
   TMS_NSEC=nsec1... uv run python smoke_live.py https://<app-url>
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
