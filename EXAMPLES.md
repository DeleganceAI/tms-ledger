# EXAMPLES — Every MCP Call, One Session

One end-to-end session against the V1.md §10 dataset, consistent with the v1 schema (no `source_type`, no `doc_type`, explicit node IDs everywhere — the server never resolves references).

Timeline:

- **Oct 1** — Reuters article (`o1`) supports claim `c1` via two pieces of evidence (`e1`, `e2`) → believed
- **Oct 2** — blog post (`o2`) attacks it (`e3`) → contested
- **Oct 3** — forensic analysis (`o3`) attacks the blog post (`e4`) → believed
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

`source_id` is the node ID returned by `add_source` — it creates the `PUBLISHED` edge. No implicit source matching, ever.

### 3. `add_claim`

```json
// request
{ "text": "Tesseralia laid off 15% of its staff in September 2026" }

// response
{ "id": "c1", "text": "Tesseralia laid off 15% of its staff in September 2026",
  "asserted_at": "2026-10-01T09:01:00Z" }
```

### 4. `add_evidence`

`target_id` may be any node — claims, evidence, sources, observations are all addressable.

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

A second `add_evidence` follows immediately (`e2`, also from `o1`): *"Two employees confirmed the layoffs on the record."*

### 5. `assert_same_as`

On Oct 4, another agent reads a tweet and extracts a differently-worded claim. It adds the claim, searches, judges it co-referent, and asserts identity — *the judgment lives with the agent, not the server.*

```json
// request
{ "claim_id_a": "c2", "claim_id_b": "c1",
  "reason": "Both state a 15% workforce cut at Tesseralia; identical event, timeframe, and magnitude" }

// response
{ "edge": "SAME_AS", "claim_id_a": "c2", "claim_id_b": "c1",
  "reason": "Both state a 15% workforce cut at Tesseralia; identical event, timeframe, and magnitude",
  "asserted_at": "2026-10-04T14:10:00Z" }
```

### 6. `mark_duplicate_of`

A news aggregator republishes the forensic analysis verbatim.

```json
// request
{ "observation_id": "o4", "duplicate_of_id": "o3",
  "reason": "Syndicated copy — identical content, same hash" }

// response
{ "edge": "DUPLICATE_OF", "observation_id": "o4", "duplicate_of_id": "o3",
  "reason": "Syndicated copy — identical content, same hash",
  "asserted_at": "2026-10-04T14:12:00Z" }
```

`independent_sources` in verdicts respects this edge — syndication is never mistaken for corroboration.

### 7. `mark_supersedes`

Reuters replaces its article with a corrected version.

```json
// request
{ "observation_id": "o5", "supersedes_id": "o1" }

// response
{ "edge": "SUPERSEDES", "observation_id": "o5", "supersedes_id": "o1",
  "asserted_at": "2026-10-04T14:15:00Z" }
```

Recorded as bookkeeping. v1 evaluation does not consult `SUPERSEDES` — agents can see the edge and reason about it themselves.

---

## Queries

Every query returns the same envelope: `total_count`, `page`, `page_size`, `items`.

### 8. `search_claims`

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

Note `c2`: it is `SAME_AS` `c1` (call #5), yet its own status is `unresolved` — identity is *asserted*, not merged. An agent reading both plus the `SAME_AS` edge reconciles them in its own head. Counts, no reasons — an agent sees the unexpected rebuttal on `c1` and drills in.

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

### 9. `get_claim_summary`

The metadata tier: evidence posture of one claim, without grounds, reasons, or chains.

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
  "independent_sources": 1 }
```

One glance tells the story: two chains, one source, no standing objections.

### 10. `get_evidence`

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

### 11. `get_observation`

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

### 12. `get_source`

```json
// request
{ "id": "s2" }

// response
{ "id": "s2", "name": "Example Blog", "uri": "https://example.org",
  "observation_count": 1,
  "asserted_at": "2026-10-02T10:55:00Z" }
```

### 13. `evaluate`

```json
// request
{ "claim_id": "c1" }

// response
{ "claim_id": "c1",
  "claim_text": "Tesseralia laid off 15% of its staff in September 2026",
  "status": "believed",
  "support": { "chains": 2, "independent_sources": 1 },
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

`chains: 2`, `independent_sources: 1` — both chains ground in the same Reuters article. The system never calls that "two pieces of evidence."

### 14. `what_if_retracted`

```json
// request: "what if the forensics get challenged?"
{ "node_id": "o3" }

// response
{ "retracted": "o3",
  "flips": [
    { "id": "c1", "from": "believed", "to": "contested" } ] }
```

Kill the forensic analysis → its rebuttal of the blog dies with it → the blog's attack on `c1` stands again.

### 15. `diff`

```json
// request
{ "query": "Tesseralia",
  "as_of_a": "2026-10-01T00:00:00Z",
  "as_of_b": "2026-10-04T14:20:00Z" }

// response
{ "total_count": 1, "page": 1, "page_size": 10,
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
          "via": "e4: Independent forensic analysis authenticates the memo PDF" } ] } ] }
```

`status_a: null` = the claim did not exist yet. The flip timeline is the fixpoint replayed per evidence arrival.

---

## The Intake Recipe (agent-side, documented here — not in the server)

1. `add_observation` the document; `add_source` first if the source is new.
2. Extract candidate claims from the content.
3. `search_claims` for each candidate — *judge* whether a match is truly the same claim.
4. Same claim → skip, or `assert_same_as` if wording differs meaningfully. New → `add_claim`.
5. `add_evidence` for each claim the document grounds, with a specific, checkable `reason`.
6. `get_claim_summary` or `evaluate` to confirm the resulting posture.

**Deliberately absent from the server:** matching, co-reference, relevance ranking, auto-registration. If an operation requires judgment about meaning, it is a step in this recipe — composed by the agent, never hidden in a tool.
