# Roles and Success

The [proposed MCP interface](V1.md) serves six workflows, not a fixed set of bots. Humans and AI agents can perform any role and contribute any record type. Roles are responsibilities, not permissions or trust rankings. The ledger stores assertions and relationships; downstream readers do all interpretation.

| Role | Responsibility | Successful outcome | Minimum access |
|---|---|---|---|
| **Observation intake** | Gather material around a topic or question; inspect existing records and judge relevance. | A **new, relevant observation is added** with content and provenance. Detecting a duplicate is a valid no-write outcome, not a new intake success. | Observation vector/keyword search, source search and URI/hash filters, exact document reads, source/observation writes. |
| **Claims and evidence** | Identify claims and explain how observations support, rebut, or qualify them. | A specific claim is created or reused and connected to a grounding observation by evidence with a checkable reason. | Claim search, original observations, existing evidence, claim/evidence writes. |
| **Contradiction discovery** | Distinguish genuine incompatibility from differences in scope, time, or meaning. | An explicit, authored finding names **at least two distinct claims** and explains why they cannot all hold together; not every pair must conflict. | Claim search and exact reads, original observations, evidence, contradiction creation/search/reads. |
| **Reviewer** | Check contributions for misreadings, unsupported inferences, and incorrect links. | A mistake is documented with checkable grounds through appended evidence targeting the relevant record. | Exact records, author IDs/timestamps, reasons, preserved observations, and observation/evidence writes. |
| **Follow-up researcher** | Investigate a contradiction or unanswered question using further information. | A **new, related observation is found and added** with provenance. Evidence explains its bearing where justified; resolving disagreement is not required. | Existing claims, contradictions, evidence and observations; observation search/writes and evidence writes. External research happens outside the ledger. |
| **Briefing / synthesis** | Help an end human or AI user understand a subject or answer a question. | A useful answer cites records, explains support and disagreement, and identifies remaining uncertainty as the reader's interpretation. No write is required. | Search and exact reads of claims, contradictions, evidence, authors, sources and original observations. |

Briefing is the primary consumer experience. No role must manufacture a discovery: finding no relevant material, contradiction, or mistake is an honest outcome.

## Authorship and provenance

Every source, observation, claim, contradiction and evidence record requires an `author_id` referencing the authors registry and a database-supplied `asserted_at` timestamp. The registry records a name and kind (`human` or `agent`); `add_author` creates an operational identity, not a login or guarantee of verified identity. Reads expose attribution, with author and time filters where applicable.

Authors are distinct from sources: the person entering an article is its ledger author; the publisher is its source. Attribution supports accountability, not correctness. Preserve observation content for audit. SQL permits missing content, which readers must treat as unavailable rather than reconstructing or assuming it was inspected.

## Retrieval and research handoffs

Search → inspect → append → read. Retrieval supplies candidates, not judgments. Claim and observation text searches offer selectable exact cosine retrieval over paired Qwen/Qwen3-Embedding-8B 4096-dimensional embeddings or PostgreSQL keyword/text retrieval. Records without embeddings remain available through other reads. Neither method proves relevance, duplication, truth, or exhaustive coverage; distances are not confidence scores. Matching text or hashes does not merge records or make writes idempotent.

Contradiction membership is complete and immutable: `add_contradiction` atomically records the finding and at least two distinct claim IDs. Changing membership requires a new finding. Evidence always cites a grounding observation and a specific reason; `SUPPORTS` and `REBUTS` can target a claim, evidence record, source, observation, or contradiction. `QUALIFIES` is claims-only. Reviewers can reuse an existing grounding observation or first add an observation documenting their findings. Further evidence does not delete or automatically deactivate earlier records, nor propagate between a contradiction and its member claims.

Handoffs may cite retrieved record IDs. Memberships, evidence links, authors and timestamps let readers browse an evidence trail; they do not record a causal workflow or why research was commissioned. Scheduling and assignments remain outside the ledger. Whether a claim is believed or contested, or a contradiction is open or resolved, is entirely the downstream human or AI reader's conclusion—not a server verdict. See [EXAMPLES.md](EXAMPLES.md) for a short investigation.
