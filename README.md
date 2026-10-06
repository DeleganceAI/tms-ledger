# tmsv2

Number-free truth maintenance system.

An epistemic ledger of text-based statements — claims, observations, sources, and evidence — with an intended MCP interface for agents to query belief states and their provenance.

## The Discipline

1. **No confidence numbers or degrees.** No probabilities, weights, scores, or ordered confidence labels. Numbers inside opaque claim text and descriptive record counts are not confidence inputs.
2. **Never aggregate confidence.** Evaluation follows evidence relationships, not weighted summation.
3. **Show disagreement.** Report support and surviving objections rather than smoothing conflict into a score. Cycle handling and status mapping remain explicit evaluator decisions, not settled SQL behavior.
4. **Claims are opaque text.** Identity, classifications, and statements about sources can be claims with evidence. Agents interpret them; the ledger does not parse them, merge identities, or redirect references.
5. **Ground evidence.** Every evidence record references an observation and carries a nonblank reason. This is not a reason requirement on every foreign key.
6. **Append-only.** Corrections are new records and grounded evidence, never mutations or automatic version replacement. Beliefs and evidence standing are derived, not stored.
7. **Keep projections separate.** External layers may compute scores in their own stores. Outputs written back are opaque claims with evidence, never new confidence fields or numeric inputs to the evaluator.

## Storage and Current Scope

[db/init.sql](db/init.sql) is the authoritative **PostgreSQL + pgvector** storage contract. There are exactly four tables:

| Table | Purpose |
|---|---|
| `sources` | Source name and optional URI. |
| `observations` | Document URI, nullable content, nonunique content hash, and required `source_id` foreign key. |
| `claims` | Nonempty opaque claim text; repeated text is allowed. |
| `evidence` | A grounding observation, relation, exactly one typed target foreign key, and a required nonblank reason. |

All records have a text primary key and `asserted_at`, supplied by the database's `DEFAULT now()` rather than agent write arguments. Evidence relations are `SUPPORTS`, `REBUTS`, and `QUALIFIES`; targets may be claims, evidence, sources, or observations, except that `QUALIFIES` targets claims only.

Claims and observations have paired nullable `embedding` / `embedding_model` fields. The selected model is **`Qwen/Qwen3-Embedding-8B`**, using the full **4096 dimensions**, without dimension reduction. No content-hash deduplication or idempotency requirement is imposed. There are no identity-link, document-dependence, or document-version tables or tools. No Hermes package is part of the current build.

The intended MCP surface has four writes: `add_source`, `add_observation`, `add_claim`, and `add_evidence`. Read tools cover search, evidence traversal, record lookup, claim summaries, evaluation, hypothetical retraction, and historical differences. Collection queries use pagination envelopes; singleton reads and verdicts return objects.

Verdicts report `support.chains` as the count of standing supporting evidence records and `support.distinct_sources` as the count of distinct source IDs behind those records. These counts do not establish independent reporting or rule out syndication, and are not confidence scores.

## Unresolved Implementation and Evaluation Decisions

The design is not a claim that the SQL alone supplies a working evaluator or MCP server:

- **Embedding indexes:** SQL declares HNSW indexes over `halfvec(4096)`, exceeding its documented **4000-dimensional** halfvec index ceiling. Full embedding storage and successful indexed retrieval are different claims; this index incompatibility is unresolved.
- **Initialization:** stale trigger declarations reference absent tables. They are an initialization issue, not features to restore. The current script must not be presented as successfully runnable without resolving its issues.
- **Evaluation:** SQL stores relationships but does not settle standing and provenance propagation, `SUPPORTS` semantics for sources/observations/evidence, cycle handling and status mapping, the effect of `QUALIFIES`, or hypothetical retraction dependencies. These need an explicit application contract.

Full design and read surface: [V1.md](V1.md). Tool examples: [EXAMPLES.md](EXAMPLES.md).
