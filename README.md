# tmsv2

Number-free truth maintenance system.

An epistemic ledger of text-based statements: claims, observations, sources, and

evidence — served to agents over MCP as belief states with full provenance.

## The Discipline

1. **No numbers, no degrees.** No probabilities, likelihoods, weights, scores,
   or ordered labels ("weak/moderate/strong" is `{33%, 66%, 100%}` in a trench coat).
2. **Never aggregate.** Conflicts are resolved by graph topology, not weighted summation.
3. **Contested is an answer.** Cycles and stalemates are surfaced, never numerically smoothed.
4. **Everything is a claim** — sources, verdicts, identity, independence — all attackable by evidence.
5. **Provenance or it didn't happen.** Every edge carries a reason and a source observation.
6. **Append-only.** Never edit; supersede or correct via edges. Beliefs are derived, never stored.
7. **Numbers may be computed *from* the graph by external layers, never stored *in* it.**
   (e.g., a Bayesian layer may read the graph and derive scores out-of-band; it writes back
   only claims that *quote* numbers, which are then attackable like everything else.)

Full design: [V1.md](V1.md)
