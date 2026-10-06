# EXAMPLES — Every MCP Call, One Session

An illustrative end-to-end session for the proposed MCP surface, using the four-table PostgreSQL + pgvector storage contract in `db/init.sql`: `sources`, `observations`, `claims`, and `evidence`. Explicit IDs are used throughout; the server does not perform semantic reference matching.

**Storage versus evaluation:** the writes below follow the SQL vocabulary, but the read results illustrate intended noncyclic rebuttal propagation, not an implemented evaluator or semantics guaranteed by SQL. `SUPPORTS` targeting sources, observations, or evidence, cycle handling and status mapping, and the effect of `QUALIFIES` remain unresolved. `QUALIFIES` may only target claims in storage. Statuses and `standing` are computed, not stored.

All `asserted_at` values below illustrate the database's `DEFAULT now()` at insertion time; agents do not supply them through the API. IDs and shortened hashes are illustrative. Observation `content` is nullable in SQL, although this intake example supplies it. Claim text and observation hashes are nonunique: these writes do not promise deduplication or idempotency. Claim and observation embeddings, when present, use full Qwen/Qwen3-Embedding-8B vectors (4096 dimensions), with `embedding` and `embedding_model` either both null or both present. Retrieval indexing is an unresolved implementation issue: the SQL's `halfvec(4096)` HNSW declarations exceed its documented 4,000-dimensional ceiling; no dimension reduction is proposed here.

Timeline:

- **Oct 1** — Reuters article (`o1`) supports claim `c1` via two pieces of evidence (`e1`, `e2`) → believed
- **Oct 2** — blog post (`o2`) rebuts the claim (`e3`) → contested
- **Oct 3** — forensic analysis (`o3`) rebuts the blog post (`e4`) → believed
- **Oct 4, 14:20** — all queries run "now"

---

## Writes

### 1. `add_source`

```json
// request
{ "name": "Reuters", "uri": "https://reuters.com" }

// response
{ "id": "s1", "name": "Reuters", "uri": "https://reuters.com",
  "asserted_at": "2026-10-01T09:00:00Z" }
```

### 2. `add_observation`

Caller sends raw `content`; the server persists it and derives `content_hash`.

```json
// request
{ "source_id": "s1",
  "uri": "https://reuters.com/2026/09/30/tesseralia-lays-off-staff",
  "content": "SAN FRANCISCO, Sept 30 — Tesseralia is cutting 15% of its workforce…" }

// response
{ "id": "o1", "source_id": "s1",
  "uri": "https://reuters.com/2026/09/30/tesseralia-lays-off-staff",
  "content_hash": "sha256:9f3a…",
  "asserted_at": "2026-10-01T09:00:30Z" }
```

`source_id` is the ID returned by `add_source`, stored as `observations.source_id`. No implicit source matching.

### 3. `add_claim`

```json
// request
{ "text": "Tesseralia laid off 15% of its staff in September 2026" }

// response
{ "id": "c1", "text": "Tesseralia laid off 15% of its staff in September 2026",
  "asserted_at": "2026-10-01T09:01:00Z" }
```

### 4. `add_evidence`

`target_id` identifies an existing claim, evidence record, source, or observation. The proposed API maps this explicit ID to SQL's `target_kind` and exactly one matching `target_*_id` column. `SUPPORTS` and `REBUTS` may target any of those kinds; `QUALIFIES` only claims. A nonblank `reason` is required on evidence, not on every foreign-key relationship.

```json
// request
{ "from_observation_id": "o1", "target_id": "c1",
  "relation": "SUPPORTS",
  "reason": "Article quotes an internal memo dated 2026-09-20 announcing a 15% staff reduction" }

// response
{ "id": "e1", "relation": "SUPPORTS", "target_id": "c1",
  "from_observation_id": "o1",
  "reason": "Article quotes an internal memo dated 2026-09-20 announcing a 15% staff reduction",
  "asserted_at": "2026-10-01T09:02:00Z" }
```

### 5. `add_evidence` — second supporting record

```json
// request
{ "from_observation_id": "o1", "target_id": "c1", "relation": "SUPPORTS",
  "reason": "Two employees confirmed the layoffs on the record" }

// response
{ "id": "e2", "from_observation_id": "o1", "target_id": "c1",
  "relation": "SUPPORTS", "reason": "Two employees confirmed the layoffs on the record",
  "asserted_at": "2026-10-01T09:03:00Z" }
```

### 6. `add_source` — blog

```json
// request
{ "name": "Example Blog", "uri": "https://example.org" }

// response
{ "id": "s2", "name": "Example Blog", "uri": "https://example.org",
  "asserted_at": "2026-10-02T10:55:00Z" }
```

### 7. `add_observation` — blog post

```json
// request
{ "source_id": "s2", "uri": "https://example.org/memo-dispute",
  "content": "The memo is fake: its metadata contains anomalies…" }

// response
{ "id": "o2", "source_id": "s2", "uri": "https://example.org/memo-dispute",
  "content_hash": "sha256:2b4c…", "asserted_at": "2026-10-02T10:56:00Z" }
```

### 8. `add_evidence` — rebuttal of the claim

```json
// request
{ "from_observation_id": "o2", "target_id": "c1", "relation": "REBUTS",
  "reason": "Blog post claims the memo is fake, citing metadata anomalies" }

// response
{ "id": "e3", "from_observation_id": "o2", "target_id": "c1", "relation": "REBUTS",
  "reason": "Blog post claims the memo is fake, citing metadata anomalies",
  "asserted_at": "2026-10-02T11:00:00Z" }
```

### 9. `add_source` — forensic analyst

```json
// request
{ "name": "Example Forensics", "uri": "https://forensics.example.org" }

// response
{ "id": "s3", "name": "Example Forensics", "uri": "https://forensics.example.org",
  "asserted_at": "2026-10-03T15:20:00Z" }
```

### 10. `add_observation` — forensic analysis

```json
// request
{ "source_id": "s3", "uri": "https://forensics.example.org/memo-analysis",
  "content": "The original memo PDF is authentic; the cited metadata is consistent with export…" }

// response
{ "id": "o3", "source_id": "s3", "uri": "https://forensics.example.org/memo-analysis",
  "content_hash": "sha256:3c5d…", "asserted_at": "2026-10-03T15:25:00Z" }
```

### 11. `add_evidence` — rebuttal of the blog post

```json
// request
{ "from_observation_id": "o3", "target_id": "o2", "relation": "REBUTS",
  "reason": "Forensic analysis authenticates the memo PDF and explains the metadata anomalies" }

// response
{ "id": "e4", "from_observation_id": "o3", "target_id": "o2", "relation": "REBUTS",
  "reason": "Forensic analysis authenticates the memo PDF and explains the metadata anomalies",
  "asserted_at": "2026-10-03T15:30:00Z" }
```

### 12. `add_claim` — a separately recorded statement

```json
// request
{ "text": "Tesseralia has cut 15% of its workforce" }

// response
{ "id": "c2", "text": "Tesseralia has cut 15% of its workforce",
  "asserted_at": "2026-10-04T14:08:00Z" }
```

Similar wording does not merge claims or transfer evidence. No evidence in this session targets `c2`.

---

## Queries

Collection queries (`search_claims`, `get_evidence`, `diff`) return `total_count`, `page`, `page_size`, and `items`. Singleton reads (`get_claim_summary`, `get_observation`, `get_source`) and verdicts (`evaluate`, `what_if_retracted`) return objects, as shown below.

### 13. `search_claims`

**The front door.** Counts arrive before content: a `summary` block with per-status counts, then items ordered believed-first.

```json
// request: "what do we believe about Tesseralia layoffs?"
{ "text": "Tesseralia layoffs", "page_size": 10 }

// response
{ "total_count": 2, "page": 1, "page_size": 10,
  "summary": { "believed": 1, "contested": 0, "unresolved": 1, "disbelieved": 0 },
  "items": [
    { "id": "c1",
      "text": "Tesseralia laid off 15% of its staff in September 2026",
      "status": "believed",
      "supporting": 2, "rebutting": 1, "qualifying": 0,
      "asserted_at": "2026-10-01T09:01:00Z" },
    { "id": "c2",
      "text": "Tesseralia has cut 15% of its workforce",
      "status": "unresolved",
      "supporting": 0, "rebutting": 0, "qualifying": 0,
      "asserted_at": "2026-10-04T14:08:00Z" } ] }
```

`c2` has no evidence of its own and is shown as `unresolved`; semantic similarity does not transfer `c1`'s support. The `supporting`, `rebutting`, and `qualifying` counts above are total evidence records, not standing counts. Counts, no reasons — an agent sees the recorded rebuttal on `c1` and drills in.

**Cold start** — no topic in mind, "what claims do we even have?":

```json
// request
{ "page_size": 10 }

// response
{ "total_count": 2, "page": 1, "page_size": 10,
  "summary": { "believed": 1, "contested": 0, "unresolved": 1, "disbelieved": 0 },
  "items": [ "…claims, most recent first…" ] }
```

**Neighborhood wandering** — land on one claim, fan out to its semantic neighbors:

```json
// request: "what else is near c1?"
{ "similar_to": "c1", "page_size": 10 }
```

The exploration lifestyle: search text → read the summary → paginate or filter by status → `similar_to` to wander — all counts-first, drilling only where it matters.

### 14. `get_claim_summary`

The metadata tier: evidence posture of one claim, without grounds, reasons, or expanded evidence records.

```json
// request
{ "claim_id": "c1" }

// response
{ "claim_id": "c1",
  "text": "Tesseralia laid off 15% of its staff in September 2026",
  "status": "believed",
  "supporting":   { "total": 2, "standing": 2 },
  "rebutting":    { "total": 1, "standing": 0 },
  "qualifying":   { "total": 0, "standing": 0 },
  "chains": 2,
  "distinct_sources": 1 }
```

One glance tells the story: two standing supporting evidence records, one distinct source ID, no standing objections in this intended evaluation.

### 15. `get_evidence`

```json
// request: "why is this believed if something rebuts it?"
{ "target_id": "c1", "relation": "REBUTS", "page_size": 10 }

// response
{ "total_count": 1, "page": 1, "page_size": 10,
  "items": [
    { "id": "e3", "relation": "REBUTS",
      "reason": "Blog post claims the memo is fake, citing metadata anomalies",
      "from_observation_id": "o2",
      "standing": false } ] }
```

One hop by default; `depth: 2` would include `e4` (which rebuts `o2`, the document `e3` comes from).

### 16. `get_observation`

Drill-down — search results never carry document payloads.

```json
// request
{ "id": "o1" }

// response
{ "id": "o1", "source_id": "s1",
  "uri": "https://reuters.com/2026/09/30/tesseralia-lays-off-staff",
  "content": "SAN FRANCISCO, Sept 30 — Tesseralia is cutting 15% of its workforce…",
  "content_hash": "sha256:9f3a…",
  "asserted_at": "2026-10-01T09:00:30Z" }
```

### 17. `get_source`

```json
// request
{ "id": "s2" }

// response
{ "id": "s2", "name": "Example Blog", "uri": "https://example.org",
  "observation_count": 1,
  "asserted_at": "2026-10-02T10:55:00Z" }
```

### 18. `evaluate`

```json
// request
{ "claim_id": "c1" }

// response
{ "claim_id": "c1",
  "claim_text": "Tesseralia laid off 15% of its staff in September 2026",
  "status": "believed",
  "support": { "chains": 2, "distinct_sources": 1 },
  "grounds": [
    { "evidence_id": "e1",
      "reason": "Article quotes an internal memo dated 2026-09-20 announcing a 15% staff reduction",
      "from_observation_id": "o1", "from_source": "Reuters" },
    { "evidence_id": "e2",
      "reason": "Two employees confirmed the layoffs on the record",
      "from_observation_id": "o1", "from_source": "Reuters" }
  ],
  "surviving_objections": [],
  "collapse_conditions": [
    { "retract": "o1", "flips_to": "unresolved" },
    { "retract": "o3", "flips_to": "contested" },
    { "retract": "e4", "flips_to": "contested" }
  ],
  "computed_at": "2026-10-04T14:20:00Z",
  "as_of": "2026-10-04T14:20:00Z" }
```

`support.chains: 2` counts the standing supporting evidence records `e1` and `e2`, not paths through the graph. `distinct_sources: 1` counts distinct source IDs among those records: both are grounded in the Reuters observation. This is not a claim of verified independence and does not detect syndication.

### 19. `what_if_retracted`

```json
// request: "what if the forensics get challenged?"
{ "node_id": "o3" }

// response
{ "retracted": "o3",
  "flips": [
    { "id": "c1", "from": "believed", "to": "contested" } ] }
```

In this intended noncyclic evaluation, hypothetically excluding the forensic analysis makes its rebuttal of the blog unavailable, so the blog's rebuttal of `c1` stands again. This is a read-only hypothetical, not a deletion from the ledger.

### 20. `diff`

```json
// request
{ "query": "Tesseralia",
  "as_of_a": "2026-10-01T00:00:00Z",
  "as_of_b": "2026-10-04T14:20:00Z" }

// response
{ "total_count": 2, "page": 1, "page_size": 10,
  "items": [
    { "claim_id": "c1",
      "status_a": null,
      "status_b": "believed",
      "flips": [
        { "at": "2026-10-01T09:02:00Z", "to": "believed",
          "via": "e1: Article quotes an internal memo dated 2026-09-20…" },
        { "at": "2026-10-02T11:00:00Z", "to": "contested",
          "via": "e3: Blog post claims the memo is fake, citing metadata anomalies" },
        { "at": "2026-10-03T15:30:00Z", "to": "believed",
          "via": "e4: Forensic analysis authenticates the memo PDF and explains the metadata anomalies" } ] },
    { "claim_id": "c2",
      "status_a": null,
      "status_b": "unresolved",
      "flips": [] } ] }
```

`status_a: null` = the claim did not exist yet. The flip timeline illustrates intended evaluation at each evidence arrival, not a SQL-defined fixpoint algorithm. `c2` was added during the interval but has no evidence-driven transitions; its final posture is shown without inventing an evidence event.

---

## The Exploration Recipe (agent-side, documented here — not in the server)

The read lifestyle — an agent orienting itself in the ledger:

1. **Orient:** `search_claims` with your topic. Read the `summary` block first — it shows the shape of the belief landscape before any content.
2. **Cold start:** No topic in mind? Call `search_claims` with nothing — the whole world state, most recent first.
3. **Wander:** Land on an interesting claim? `similar_to` it. Topics are points in embedding space; neighborhoods are how you find what you didn't think to ask for.
4. **Assess the posture:** `get_claim_summary` — status and counts, nothing heavy.
5. **Read the evidence:** `get_evidence`, one hop at a time; you control the depth.
6. **Get the verdict:** `evaluate` — grounds, surviving objections, collapse conditions.
7. **Stress-test:** `what_if_retracted` on keystone evidence; `diff` to reconcile after new observations arrive.
8. **Act only with the trace in hand:** a belief is only as good as its grounds are checkable and its collapse conditions are acceptable.

## The Intake Recipe (agent-side, documented here — not in the server)

1. `add_observation` the document; `add_source` first if the source is new.
2. Extract candidate claims from the content.
3. `search_claims` for each candidate — *judge* whether a match is truly the same claim.
4. Existing claim fits → use its ID. Otherwise → `add_claim`. This choice belongs to the agent; repeated text is allowed and does not trigger automatic merging.
5. `add_evidence` for each claim the document grounds, with a specific, checkable `reason`.
6. `get_claim_summary` or `evaluate` to confirm the resulting posture.

**Deliberately absent from the server:** semantic matching, claim merging, automatic source registration, and interpretation of document content. Semantic retrieval can surface candidates; the agent chooses explicit IDs and records its reasons. The evaluator determines evidence applicability from the recorded relationships, not from the meaning of the text.
