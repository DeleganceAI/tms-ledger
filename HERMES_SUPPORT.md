# tmsv2 × Hermes Agent — Deferred Proposal

**Status:** deferred integration proposal, outside the current build. There is no Hermes package, supported installation recipe, or Hermes-specific acceptance checklist in current scope. This document records possible client-side integration ideas; it does not add server implementation requirements.

## 1. Boundary

The ledger is agent-agnostic. A future Hermes integration would consume the same proposed MCP tools as any other client, without a fork or Hermes-specific server behavior. Hermes version details, configuration keys, approval behavior, scheduling facilities, and extension compatibility would need verification when that work is explicitly resumed. No compatibility with a particular Hermes release is claimed here.

Possible future client artifacts include intake and briefing skills and a memory-policy snippet. They are proposals, not shipped artifacts or current build deliverables. Packaging, commands, startup targets, diagnostics, read-only modes, scheduling, and catalog distribution are not specified here.

## 2. Current Storage Contract

`db/init.sql` is the authority for storage: PostgreSQL with pgvector, with four actual tables: `sources`, `observations`, `claims`, and `evidence`. Historical comments or triggers naming absent tables do not expand that contract.

- Sources identify where observations came from; `observations.source_id` is the required foreign key.
- Observations carry a URI and required `content_hash`; stored `content` is nullable. API examples may send content for the server to persist and hash.
- Claim text and observation hashes are nonunique. Matching hashes do not imply an existing row must be returned, and repeated intake is not guaranteed to be idempotent. An interrupted or uncertain write must not be treated as safe to retry without considering another append.
- Evidence comes from an observation and targets exactly one claim, evidence record, source, or observation. Relations are `SUPPORTS`, `REBUTS`, and `QUALIFIES`; `QUALIFIES` may target only claims. Evidence requires a nonblank `reason`; this is not a reason requirement on every foreign key.
- Timestamps are assigned by the database's `DEFAULT now()`, not supplied by the agent through the API.
- Observation and claim embeddings use the full **Qwen/Qwen3-Embedding-8B, 4096-dimensional** representation, without dimension reduction. `embedding` and `embedding_model` are paired nullable fields: both absent or both present.

**Unresolved implementation issue:** the SQL declares HNSW indexes over `halfvec(4096)` while documenting a 4,000-dimensional indexing ceiling. The 4,096-dimensional representation exceeds that ceiling; these index declarations are not a demonstrated working retrieval setup. The mismatch remains unresolved, not a reason to reduce embedding dimensions.

## 3. Proposed Shared MCP Surface

A future client would use only the shared tool surface:

| Role | Tools |
|---|---|
| Writes | `add_source`, `add_observation`, `add_claim`, `add_evidence` |
| Reads | `search_claims`, `get_evidence`, `get_claim_summary`, `get_observation`, `get_source`, `evaluate`, `what_if_retracted`, `diff` |

Collection queries (`search_claims`, `get_evidence`, `diff`) use `total_count`, `page`, `page_size`, and `items` envelopes. Singleton reads and verdicts return objects as illustrated in EXAMPLES.md, not collection envelopes.

`support.chains` counts standing supporting evidence records, not graph paths. `distinct_sources` counts distinct source IDs among those records. It does not establish independence or detect syndication. Two supporting evidence records from the same source count as two chains and one distinct source.

The SQL stores no belief status or standing result. Evaluation remains an application-layer concern. The effect of `SUPPORTS` targeting sources, observations, or evidence, cycle handling and status mapping, and the effect of `QUALIFIES` are unresolved evaluation rules. The noncyclic rebuttal sequence in EXAMPLES.md illustrates intended behavior, not a completed evaluator guaranteed by SQL. A future integration must not invent these rules in its client skills.

## 4. Possible Client Recipes

An intake recipe could find relevant existing claims, choose explicit IDs, append observations and evidence with specific reasons, and then query the resulting posture. Semantic matching is an agent judgment, not automatic merging or hash-based deduplication. Nothing in the storage contract guarantees that repeated writes reuse an existing ID.

A briefing recipe could use `search_claims`, `get_claim_summary`, `evaluate`, and `diff` to identify changed conclusions, surviving objections, and gaps in evidence. A schedule could invoke such a recipe only as separately approved integration work. There is no current event dispatch, watch-rule, notification, or per-append evaluation commitment here.

## 5. Proposed Memory Policy

> World claims should be retrieved from the ledger with their evidence and objections, not answered from a cached client memory. Store the habit of querying, not a detached copy of a verdict. Cite claim IDs and retain the context needed to check evidence applicability.

Client preferences and conversational continuity are separate from ledger claims. A future integration should preserve that distinction without reading or depending on Hermes's internal storage. The ledger remains in PostgreSQL, regardless of the client selected.
