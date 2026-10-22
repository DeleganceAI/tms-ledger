# The Bitter Lesson Applied to Knowledge Graphs

In 2019 Rich Sutton wrote [The Bitter Lesson](http://www.incompleteideas.net/IncIdeas/BitterLesson.html). Its point, roughly: for seventy years, AI researchers kept building their own understanding of a domain into their systems, and for seventy years, general methods that scale with computation beat them anyway. Chess, Go, speech and vision all went the same way. The hand-built knowledge helped for a while, then plateaued, then got in the way.

Knowledge graphs never learned this lesson. This page is about why we did.

## Every schema is a theory of the world

The moment you design a knowledge graph, you start making decisions that feel like engineering and are actually claims about reality.

- **You define entities.** Is "MCAS" one thing? Is "mast cell activation syndrome as defined by the 2012 consensus" the same thing as "MCAS as defined by the 2019 AAAAI work group"? Half of the MCAS literature is an argument about exactly that. Your entity table has already picked a side.
- **You merge identities.** Two papers mention "DAO activity". Same concept? Same assay? Same units? Measured in serum or in the gut? The merge button is a judgement, made once, by whoever wrote the merge rule, and from then on every query inherits it silently.
- **You type your relations.** `causes`, `treats`, `is_a`, `part_of`, `associated_with`. Each one is a little ontology. Each one works beautifully in the domain it was designed for and turns into mush the moment a claim is subtler than the relation: "X causes Y, but only in women over 40, only at high doses, and only according to one cohort".
- **You add probabilities.** Now every edge carries a 0.83. Where did 0.83 come from? Who calibrated it? Against what? Does 0.83 from a randomized trial mean the same as 0.83 from a blog post? Can you add them? Multiply them? The number looks like rigor and works like a costume.
- **You add confidence levels, evidence grades, trust scores, source reliability ratings.** Each one is a domain-specific theory of what counts as good evidence, frozen into a column. Medicine has GRADE. Law has standards of proof. Intelligence analysis has its own scales. None of them transfer, and all of them are contested inside their own fields.
- **You add status.** `verified`, `debunked`, `disputed`, `resolved`. Now the database has opinions, and the opinions are only as good as whoever last wrote to the status column.
- **You add time.** `valid_from`, `valid_to`, as-of semantics, temporal reasoning. Great, until a claim is about a period, a trend, a prediction, a recollection, or a revision of something that was never quite true in the first place.

Every one of these is a reasonable idea. Every one of them makes the graph better at one domain and worse at all the others. Stack enough of them and you have an expert system: very impressive inside its walls, brittle at its edges, and expensive to change when the world disagrees with you.

That is the bitter lesson, playing out in data modeling instead of in algorithms.

## The general method is reading

What changed is that we now have readers that scale with computation. A language model can read a claim written in plain English, with all its hedges and qualifications, and understand it about as well as you would. It can read the passage a claim was grounded in and judge whether the grounding holds. It can notice that two claims are about different populations and don't actually conflict.

So the structure no longer has to do the understanding. The structure only has to keep what readers need in order to do the understanding themselves, and keep it honestly:

- what was said, in the words it was said;
- what document it was grounded in, with the exact passage;
- who said it, provably;
- when it arrived;
- what someone thinks can't all be true at once, and why.

Everything else is interpretation. Interpretation belongs to whoever is reading, using the best reader available on the day they read it. A better model next year re-reads the same ledger and draws better conclusions. A schema that baked in 2026's conclusions can't do that. It has to be migrated.

## The readers are getting better, and the meanings keep moving

Two things are true at once, and together they settle the argument.

**The readers keep getting better.** Every year, models reason more carefully, hold more in context, and catch subtler distinctions. A model that can keep an entire collection in its context window, every paper, every claim, every link and its quote, can weigh a question with more nuance than any rule you could write down in advance. It can notice that a trial's population doesn't match the claim, that a "contradiction" is really a difference in timeframe, that two sources sharing a press release aren't independent. A schema can't notice anything. It can only enforce what its designer thought of, back when they thought of it. Every judgement you freeze into the structure is a judgement you have decided a future, smarter reader isn't allowed to revisit.

**The meanings keep moving.** The concepts a schema depends on aren't fixed either:

- **What counts as an entity shifts.** Diseases split into subtypes and merge back together. Diagnostic criteria get rewritten, and the same name starts pointing at a different set of patients. A company is renamed, acquired and spun out. A "species" is redrawn by new genetics. An entity table records how the world was carved up on the day it was built.
- **What a probability means shifts.** A 0.8 depends on who assigned it, against what baseline, under which model, with what calibration, for which decision. Change any of those and the same number means something else. Store it as a bare float and the context that gave it meaning is gone.
- **What counts as good evidence shifts.** Methods get discredited, whole literatures fail to replicate, a once-trusted source loses its standing, an ignored one gets vindicated. A reliability score from five years ago is a fossil.
- **What a relation means shifts.** "Causes" meant something different before randomized trials, and different again after causal inference. "Associated with" covers everything from a mechanism to a coincidence.
- **What a word means shifts.** Terms drift, get redefined and become contested.

A schema built on any of these is wrong slowly, then all at once, and fixing it means a migration that rewrites everything everyone ever recorded through the old lens.

The ledger avoids both traps by keeping the raw material and refusing to interpret it. Claims stay in the words they were written in, at the time they were written. Evidence stays whole, so a future reader sees what the source actually said. Records are never rewritten, so the history of how understanding changed is itself part of what can be read. Tomorrow's reader brings tomorrow's understanding of entities, probabilities and evidence to records that haven't been bent to fit yesterday's.

## So the scheme is as small as we could make it

There are four kinds of record that carry knowledge:

| Record | What it holds | Why it can't be smaller |
|---|---|---|
| **Evidence** | The full text of a document as someone saw it, plus where it came from. | Without the text, nothing can be checked. |
| **Claim** | One statement, as plain text. | You need a unit to point at. The server never parses it. |
| **Link** | Evidence that supports, rebuts or qualifies a target, with a verbatim quote and a reason. | The quote is the only mechanical check we keep: it proves the document actually says it. |
| **Contradiction** | Two or more claims that can't all hold, with a reason. | Incompatibility is a judgement about meaning. A link can't express it, because no single document says it. |

Plus the plumbing that makes the records trustworthy rather than knowledgeable: signatures, profiles, membership, terms.

Here is what we refused to add, on purpose:

- **No entities.** A claim mentions whatever it mentions. Two claims that use the same word are two claims.
- **No merging.** Identical text is still two records. Deciding they are the same is a reader's job.
- **No typed relations** beyond supports, rebuts and qualifies, and we are not sure even those three are the minimum.
- **No probabilities, weights, scores or confidence levels.** Numbers inside a claim are just text.
- **No statuses.** Nothing is ever marked true, false, verified, debunked, open or resolved.
- **No propagation.** Rebutting a claim doesn't touch anything else. Nothing is inferred.
- **No source reliability field.** "This journal is unreliable" is a claim, and someone can ground it or dispute it like any other.
- **No time model.** Any timeframe a claim needs goes in its text, where a reader can see it.
- **No edits.** A correction is a new record that disputes the old one. The old one stays, so you can see what was relied on.

Each of those refusals is a place where we would otherwise have smuggled in a theory of some particular domain. The ledger is meant to hold MCAS papers, macroeconomic arguments, AI-industry finance, physics and whatever comes next, with the same four kinds of record. It can only do that by not knowing anything about any of them.

## What we do enforce

Three things, and none of them is a judgement about truth:

1. **Signatures.** Each record was signed, byte for byte, by the key that claims to have written it.
2. **Structure and membership.** Records are well formed, references point at real records in the same collection, and only members can write.
3. **Quotes.** A link's quote really appears in the evidence it cites (allowing for case, whitespace, curly quotes, dashes and ligatures).

That's the whole referee. Everything else is the players.

## Think we can go smaller?

We mean it. If you can see a way to remove a record kind, a field, a relation or a rule and still keep everything a reader needs to check a claim against its sources, we want to hear it. The same goes if you think one of our four is secretly domain-specific and we just haven't noticed.

Email us at **{{CONTACT_EMAIL}}**. Bring the argument; bring a smaller schema if you have one. The best outcome for this page is that someone proves it wrong.
