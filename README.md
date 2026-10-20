# tmsv2

A number-free epistemic ledger for humans and AI agents: record claims, observations, sources, explicit contradiction findings, and grounded evidence without a server deciding what to believe. An MCP server is the only write and read path; any agent that speaks MCP can contribute, and the agent you chat with answers questions from the ledger with an inspectable thinking proof.

## The Discipline

- **No confidence scales.** No probabilities, weights, or ordered confidence labels. Numbers inside statements are ordinary content; retrieval distances are not confidence.
- **Keep interpretation with readers.** Humans and AI agents decide what is believed or contested and whether a contradiction is open or resolved. The ledger neither stores nor derives those conclusions.
- **Show the reasons.** Every evidence record cites a grounding observation, quotes it verbatim, and gives a specific reason. Contradictions name at least two distinct claims and explain their incompatibility.
- **Preserve history.** Records are append-only: corrections add records and evidence, never edit, delete, retire, or automatically replace earlier assertions.
- **Keep provenance explicit.** Each source, observation, claim, contradiction, and evidence record identifies its registered human or agent author and database-supplied assertion time. Authors are not document sources or verified identities.

The server enforces exactly two mechanical things beyond structure: an evidence quote must occur in the observation it cites, and a thinking proof may only cite records that exist. Neither is a judgement about what the records show.

## Layout

| Path | What |
|---|---|
| [db/init.sql](db/init.sql) | PostgreSQL + pgvector schema: authors, collections, sources, observations, claims, contradictions, evidence. Append-only triggers, frozen contradiction membership, quote check. |
| [db/verify.sql](db/verify.sql) | Schema invariants and an append/research/correction scenario. Rolls back. |
| [tms/ledger.py](tms/ledger.py) | Appends, reads, retrieval, fetch, embeddings, proof check. Plain functions over a psycopg connection. |
| [tms/server.py](tms/server.py) | The MCP tools and prompts; stdio or bearer-token HTTP. Logs every call. |
| [tms/ui.py](tms/ui.py), [tms/ui.html](tms/ui.html) | Local dashboard: activity view, browse view, record drawer. |
| [test_smoke.py](test_smoke.py) | End-to-end check against a live database and Ollama. Rolls back. |
| [proofs/](proofs/) | Where the briefing agent saves thinking proofs. |
| [V1.md](V1.md), [ROLES.md](ROLES.md), [EXAMPLES.md](EXAMPLES.md) | Design, contributor roles, a worked example. |

## Setup

PostgreSQL with pgvector, Ollama for embeddings, `uv` for Python, `pdftotext` (poppler) for PDFs.

```bash
docker run -d --name tmsv2-pg -p 5432:5432 -e POSTGRES_DB=tmsv2 -e POSTGRES_USER=tmsv2 -e POSTGRES_PASSWORD=tmsv2 pgvector/pgvector:pg18
```

```bash
PGPASSWORD=tmsv2 psql -h localhost -U tmsv2 -d tmsv2 -v ON_ERROR_STOP=1 -f db/init.sql
```

```bash
PGPASSWORD=tmsv2 psql -h localhost -U tmsv2 -d tmsv2 -v ON_ERROR_STOP=1 -f db/verify.sql
```

```bash
brew install ollama poppler
```

Start Ollama (`ollama serve`, or `brew services start ollama`), then:

```bash
ollama pull qwen3-embedding:8b
```

```bash
uv sync
```

Smoke test (everything it writes rolls back; needs Ollama running):

```bash
uv run python test_smoke.py
```

Environment: `TMS_DATABASE_URL` (default `postgresql://tmsv2:tmsv2@localhost:5432/tmsv2`), `OLLAMA_HOST` (default `http://localhost:11434`), `TMS_EMBED_MODEL` (default `qwen3-embedding:8b`, must return 4096 dimensions), `TMS_COLLECTION` (default collection when a tool call omits one), `TMS_TOKEN` (required for HTTP).

## Asking questions (Claude Code)

[.mcp.json](.mcp.json) registers the server over stdio for this project. In a Claude Code session here:

1. `/mcp__tms__briefing` with the collection name loads the briefing discipline: retrieve, build a thinking proof, `check_proof`, answer with citations, save the proof under `proofs/`.
2. `/mcp__tms__claims_pass` with the collection name turns documents that no evidence cites yet into claims, quoted evidence and contradiction findings.

Set `TMS_COLLECTION` in `.mcp.json` to pin a session to one collection.

## Remote agents (Grok bots and friends)

Serve over HTTP behind a bearer token, then put a tunnel in front:

```bash
TMS_TOKEN="$(openssl rand -hex 32)" uv run tms-server --http --port 8765
```

```bash
cloudflared tunnel --url http://localhost:8765
```

Configure the agent with the tunnel URL plus `/mcp` as a streamable-HTTP MCP server and `Authorization: Bearer <TMS_TOKEN>`. A quick tunnel gives a random hostname per run; a named tunnel on your own domain is the stable version. Each bot registers once with `add_author` (kind `agent`) and passes its own `author_id` on every write. Pin bots to a collection by telling them which one; the server does not infer it.

`TMS_COLLECTION=mcas` on the server makes `mcas` the default collection for calls that omit one. The token lives in a gitignored `.env` (`export TMS_TOKEN=...`), so `source .env` before starting the server.

Instructions to give an intake agent, verbatim:

> You have an MCP server named `tms`, an append-only evidence ledger. Register yourself once with `add_author` (id `grok-<yourname>`, kind `agent`) and pass that `author_id` on every write. For each document, paper or post you have collected: call `search_sources` for the publisher, site or account; if absent, `add_source`. Then `add_observation` with `collection="mcas"`, the `source_id`, the original `uri`, and the complete text as `content` (not a summary; if you only have a URL, pass it and leave `content` empty so the server fetches it, and if that fails, fetch the text yourself and pass it). Do not add claims or evidence unless asked. Record each returned observation id. Finding that a document is already present is a fine outcome; do not add it twice.

## Watching activity

```bash
uv run tms-ui
```

Opens a local dashboard at http://127.0.0.1:8780 with two tabs. **Activity**: record counts, calls and records per minute for the last hour, every MCP call so far by tool and by agent (reads included), and live feeds of recent records and calls. **Browse**: any record kind with a text filter, collection filter and paging; claims show a supports / qualifies / rebuts bar with counts and can be sorted by most evidence or most contested, and a semantic checkbox searches claim embeddings through the local Ollama model. Clicking a record opens a drawer where every linked id is clickable, so you can walk claim → evidence → observation → source. The server logs each request to the `mcp_calls` table, which is operational telemetry outside the ledger and safe to truncate. The dashboard binds to localhost only and has no auth; never put it behind the tunnel.

## Tools

| Tool | Does |
|---|---|
| `add_author`, `add_collection`, `list_collections` | Identities and collections. Both ids are slugs you choose. |
| `add_source`, `search_sources` | Where material comes from. Global across collections. |
| `add_observation` | Preserve a document in a collection. Pass full text, or just a URL and the server fetches it (PDF, HTML, JATS XML). Sites that block bots: fetch elsewhere, pass the text. Optional `title`; otherwise derived from the document. |
| `add_claim` | One statement, embedded on write for vector search. |
| `add_evidence` | Observation bears on a target with SUPPORTS, REBUTS or QUALIFIES, a verbatim `quote` (rejected if absent from the observation) and a reason. |
| `add_contradiction` | Two or more claim ids that cannot all hold, with the reason. Membership is frozen. |
| `get_record` | Exact read of any kind; observations page through content. |
| `search_claims` | Vector or keyword retrieval in a collection, with each claim's evidence and contradiction ids inlined. |
| `get_evidence`, `list_observations`, `search_contradictions` | Filtered reads. `list_observations(ungrounded_only=true)` is the claims-pass worklist. |
| `list_claims` | Claims with evidence counts, sorted `unsupported`, `unchallenged`, `contested`, `evidence` or `recent`: the follow-up research worklist. |
| `check_proof` | Validate a thinking proof and return it as an inspectable tree. |

Results come back as JSON in the response's text content (no structured content). Observations carry a `title` (passed to `add_observation` or derived from the document) that `list_observations`, `get_record` and `check_proof` trees show.

## Thinking proofs

A proof is the answering agent's argument standing on ledger records. It lives outside the ledger, saved as JSON next to the answer.

```json
{"question": "Is DAO deficiency the cause of histamine intolerance?",
 "steps": [
  {"id": "s1", "say": "Several reviews propose DAO deficiency as a mechanism.", "from": ["c_8f2a1b3c4d", "e_11c0aa9b8c"]},
  {"id": "s2", "say": "One review qualifies this: assays correlate poorly with symptoms.", "from": ["e_9e41d2f0a1"]},
  {"id": "s3", "say": "Nothing in the collection covers pediatric cases.", "from": [], "gap": true},
  {"id": "root", "say": "Proposed mechanism, not an established cause.", "from": ["s1", "s2", "s3"]}
 ]}
```

`check_proof` enforces three rules: every `from` is a record in this collection or an earlier step; exactly one root; every step has a ledger record in its ancestry or is marked `gap`. A gap is the agent saying out loud that it is speaking without the ledger.
