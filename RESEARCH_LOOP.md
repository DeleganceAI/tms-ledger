# Research Loop — Discussion Notes

2026-10-06. A condensed historical record, not a verbatim transcript or an implementation specification.

## Current decision: a ledger, not an evaluator

The later simplification supersedes earlier assistant proposals for assessments, run/session metadata, research-motivation fields, trace tools and server evaluation. Those proposals are **not active v1 requirements**. [V1.md](V1.md) describes the current proposal; [db/init.sql](db/init.sql) defines storage.

The ledger preserves authored sources, observations, claims, contradiction findings and evidence. Authorship uses registry IDs and database timestamps; registry entries are operational identities, not authenticated or verified identities. Findings atomically name at least two distinct claims and explain why they cannot all hold together. Membership is frozen; changing it requires a new finding. Later evidence can challenge the finding itself or its member claims without deleting history or automatically changing anything else.

Humans and AI readers decide what to believe, whether claims are contested, and whether contradictions are open or resolved. There are no server verdicts, automatic propagation, or stored resolution policies. The research loop describes how readers can use the ledger, not a workflow the server executes:

```text
inspect claims and evidence → append a contradiction finding → research externally
    → append a new observation → append grounded evidence → reader interprets
```

## Words worth preserving

The user described the lifecycle:

> first there are some claims, then an agent argues for a contradiction, and then another agent uses that contradiction to go find new observations, which then the evidence agent uses to add support/rebut for claims, which then eventually affect the contradiction.

And the purpose:

> ideally, i'd love for this system to show a kind of 'system wide thinking trace' over all the observations, evidence, claims, contradictions over time and ideally future states are ones where contradictions get resolved through new evidence.

The user explicitly endorsed this distinction:

> The contradiction records remain append-only, preserving what prompted the investigation.
> The set of open contradictions can shrink as findings are addressed.

These quotations preserve the historical aim. Under the current decision, “open” and “resolved” describe downstream interpretations; they are not ledger statuses. The original finding preserves its members and incompatibility reason, but no field records that it caused a later research action.

## What remains useful from the discussion

A claim asserts something about the world. A contradiction finding records a reasoned incompatibility to investigate; it does not identify which member is wrong. Not every pair of member claims must conflict.

Readers may distinguish two outcomes:

- **Disagreement addressed:** new evidence gives grounds to reject or qualify a member claim.
- **Finding corrected:** the incompatibility argument was mistaken—for example, the statements concern different timeframes, so neither member claim necessarily needs correction.

These are reader conclusions, not separate assessment records. A correction can be explained by observation-grounded evidence targeting the contradiction. Merely adding that evidence does not deactivate earlier evidence or resolve anything automatically.

The original assistant discussion suggested authored assessments, derived open-work views, research-motivation links and a paginated trace. Those mechanisms were dropped in favor of retrieving the existing records. Consumers follow contradiction memberships and evidence links, with reasons, authors and timestamps, to inspect an evidence trail. This is neither a causal workflow log nor a reconstruction of an agent's private reasoning, and it cannot establish why research was commissioned.

Success for follow-up research remains finding and adding a **new, related observation**, not necessarily resolving disagreement. Briefing is the primary consumer: it interprets the accumulated evidence for a human or AI user. Scheduling, assignments and work queues remain outside the ledger. See [ROLES.md](ROLES.md) for all six roles and [EXAMPLES.md](EXAMPLES.md) for a short investigation.
