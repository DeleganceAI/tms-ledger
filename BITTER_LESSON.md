# The Bitter Lesson Applied to Knowledge Graphs

In 2019, Rich Sutton wrote [*The Bitter Lesson*](https://www.cs.utexas.edu/~eunsol/courses/data/bitter_lesson.pdf): general methods that scale with computation have repeatedly overtaken systems built around human knowledge of a domain. Search and learning keep improving after hand-built solutions plateau.

For an evidence ledger, we take that as a reason to keep interpretations revisable. Preserve what was said and what it was based on, so better readers can reconsider the conclusions.

The distinction matters. As [*The bitter lesson selects production methods, not representational forms*](https://zby.github.io/commonplace/notes/the-bitter-lesson-selects-production-methods-not-representational/) argues, a graph can be learned, and a text system can be manually curated. Sutton's lesson does not rule out graphs. Our choice concerns which judgments the ledger treats as authoritative.

## Every schema is a theory of the world

Designing a knowledge graph means deciding which distinctions the database will recognize. Some decisions look like bookkeeping until a research question depends on them.

Suppose two papers report that model A outperforms model B. One compares single-sample accuracy; the other gives A a larger inference budget. A third paper uses a different benchmark version. Resolving the model names does not resolve what “outperforms” means. If an edge drops those conditions, every query using the edge inherits the omission.

A richer schema can represent all those conditions. For repeated comparisons under a stable protocol, explicit fields may be exactly what you want. The cost appears when the question changes: a new comparison needs a distinction the schema never recorded, or an entity merge concealed a difference that now matters. Keeping the sources and the reasons for each interpretation lets a reader revisit those decisions.

Probabilities have the same dependence on context. A confidence of 0.8 needs context: what proposition it concerns, what evidence it conditions on, and how it was estimated. TMS has no universal confidence field because contributions across a research collection need not share any of those. A reader can compute a task-specific estimate; the ledger preserves the material needed to inspect it.

## The general method is reading

Language models give us another way to use the collection: retrieve the relevant records, read their qualifications, compare the cited passages, and examine apparent contradictions. A more capable reader can revisit an earlier interpretation without changing what the original contributor wrote.

So the ledger keeps what readers need:

- what was claimed, in the contributor's words;
- the submitted source text, with the quoted passage and reason for citing it;
- which key signed the contribution, and when the server received it;
- which claims someone thinks cannot all hold, and why.

Claims and links already contain interpretation. We preserve those judgments as attributed contributions, alongside the evidence offered for them. A later reader can disagree without erasing the earlier reasoning.

[*Computed Evidence over Asserted Truth*](https://aaronsb.github.io/knowledge-graph-system/explanation/computed-evidence/) makes a related case for retaining conflicting evidence so judgments can be recomputed. Kappa Graph describes computed grounding scores and reorganizable ontologies. TMS leaves those computations to readers and applications; the shared idea is to preserve enough evidence to reconsider a conclusion.

Definitions change, benchmarks change, and readers change. The same collection can support a comparison by accuracy today and by inference budget tomorrow. Derived graphs can help with either task. Keeping their assumptions traceable to the source records makes those graphs easier to revise.

## So the schema is as small as we could make it

Four kinds of record carry the research:

| Record | What it holds |
|---|---|
| **Evidence** | Submitted document text and its source metadata. |
| **Claim** | A statement in its author's words, with a stable ID others can refer to. |
| **Link** | Evidence offered to support, rebut, or qualify a target, with a quote and a reason. |
| **Contradiction** | Two or more claims and a contributor's reason they cannot all hold. |

Signatures, profiles, membership, and terms provide the surrounding infrastructure. The content schema stays small enough that a contribution can enter without agreement on a domain ontology.

### What this is not

- **No entities.** Claims mention their subjects in plain text; the ledger defines no canonical domain entities.
- **No probabilities.** No probability, weight, or confidence fields. Numbers in claims are content; retrieval scores are not belief estimates.
- **No merging.** Distinct claim records stay distinct, even when their text matches.
- **No domain relation vocabulary.** Links use supports, rebuts, or qualifies, with a reason in plain text.
- **No statuses.** Nothing is marked true, false, verified, debunked, open, or resolved.
- **No propagation.** Rebutting one record does not automatically invalidate another.
- **No source reliability field.** A judgment about a source is another claim that can be supported or disputed.
- **No domain time model.** A claim's timeframe belongs in its text; record timestamps track provenance.
- **No edits.** Corrections add records. The earlier contribution remains available for inspection.

## What we do enforce

Three checks keep contributions inspectable:

1. **Signatures.** Event content is bound to the signing key, without establishing the signer's real-world identity.
2. **Structure and membership.** Records have valid fields and references, and collection operations require membership.
3. **Quotes.** The quoted passage occurs in the submitted evidence after normalization. Matching a quote does not establish that the passage supports the claim.

Preservation is only the starting point. Readers can miss evidence or reason badly, and submitted text can omit information from the original document. Whether the small schema improves accuracy or reduces total cost remains an empirical question. We are choosing to keep the evidence and earlier judgments available as reading methods improve.

## Think we can go smaller?

If you can remove a record kind, field, or rule while keeping what readers need to check a claim against its sources, we want to hear the argument. The same goes for cases where stronger structure earns its cost. Email **{{CONTACT_EMAIL}}**.
