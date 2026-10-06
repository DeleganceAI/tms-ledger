# tmsv2

A number-free epistemic ledger for humans and AI agents: record claims, observations, sources, explicit contradiction findings, and grounded evidence without a server deciding what to believe.

## The Discipline

- **No confidence scales.** No probabilities, weights, or ordered confidence labels. Numbers inside statements are ordinary content; retrieval distances are not confidence.
- **Keep interpretation with readers.** Humans and AI agents decide what is believed or contested and whether a contradiction is open or resolved. The ledger neither stores nor derives those conclusions.
- **Show the reasons.** Every evidence record cites a grounding observation and a specific reason. Contradictions name at least two distinct claims and explain their incompatibility.
- **Preserve history.** Records are append-only: corrections add records and evidence, never edit, delete, retire, or automatically replace earlier assertions.
- **Keep provenance explicit.** Each source, observation, claim, contradiction, and evidence record identifies its registered human or agent author and database-supplied assertion time. Authors are not document sources or verified identities.

## Current Scope

[db/init.sql](db/init.sql) defines the PostgreSQL + pgvector schema: an authors registry, five authored content types, and contradiction membership links. Claims and observations can carry full 4096-dimensional `Qwen/Qwen3-Embedding-8B` vectors for exact cosine retrieval; PostgreSQL keyword/text retrieval is a complementary option. Neither method proves relevance, duplication, or truth.

Run [db/verify.sql](db/verify.sql) with `psql` after initializing the schema to check its invariants and an append/research/correction scenario.

The **MCP interface is proposed, not implemented**. It offers append tools, exact record reads, and filtered, paginated searches—not evaluation, belief summaries, or automatic contradiction resolution. Readers inspect raw records, reasons, and provenance and form their own conclusions.

- [V1.md](V1.md): short design and proposed MCP surface.
- [ROLES.md](ROLES.md): contributor and reader responsibilities.
- [EXAMPLES.md](EXAMPLES.md): ledger-writing and reading examples.
- [RESEARCH_LOOP.md](RESEARCH_LOOP.md): historical research-loop discussion, not additional implementation requirements.
