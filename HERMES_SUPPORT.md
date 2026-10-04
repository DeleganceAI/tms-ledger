# tmsv2 × Hermes Agent

**Status:** design notes, 2026-10-04. Hermes Agent moves fast (v0.21.5 as of this writing, pre-1.0, ~6 minors in the last 4 months) — treat every version fact below as *as-of*, and re-verify before relying on it.

tmsv2 is agent-agnostic by design: MCP is the only contract, and any capable MCP client should work. Hermes Agent (Nous Research) is the **first-class reference integration** — the agent we optimize for, document for, and test against. This document says what "first-class" costs, and why each requirement exists.

---

## 0. The Posture: Add, Don't Fork

We integrate with Hermes. We do not modify it, and we do not couple to it.

- **The ledger is the product.** The agent is a disposable client, replaced whenever a better one ships. Defensibility lives in the ledger and the version-controlled skills — artifacts that survive agent churn, not in agent-specific code.
- **Every layer we'd want to touch is already an extension surface:** MCP servers, skills, SOUL.md, cron prompts. A fork would buy tighter coupling at the cost of re-merging an aggressively moving upstream for zero functional gain.
- **No Hermes-specific code paths in the server.** If the server works in Hermes because it works *everywhere*, the MCP spec is doing its job.

## 1. Why Hermes (and not the others)

The comparison set was OpenClaw, Hermes Agent, and ZeroClaw. Hermes won on four grounds specific to tmsv2:

1. **Its memory model doesn't fight the ledger.** Hermes keeps small, curated memory files (`MEMORY.md`, `USER.md`, ~2,200 / 1,375 chars) plus a searchable SQLite store. It does not feed whole transcripts back into context. This is the opposite of a problem for us — it forces the correct discipline: *the ledger is the memory; the agent queries, it doesn't cache.*
2. **Cron runs in fresh, self-contained sessions.** Scheduled work starts cold, with no conversational context. Again a feature: the brief is the prompt plus ledger queries, nothing else. (The rest of the trigger story — event-driven, semantic flips — is the long-term plan; see §6.)
3. **Python.** Same language as the DSPy/GEPA optimization stack. Not needed for black-box optimization, but it collapses friction the day we want to instrument the loop.
4. **SKILL.md compatibility.** Hermes and OpenClaw share the AgentSkills format, and both ship migration tooling. Our skills are portable artifacts, which keeps the agent swappable.

Hermes is pre-1.0 and churning hard. Everything above is a reason to integrate *shallowly*, never deeply.

## 2. What We Ship

The integration is a package, not a server:

| Artifact | Role |
|---|---|
| `tmsv2` MCP server (stdio) | The tools. Mechanical, per V1 §7. |
| `skills/tms-intake/SKILL.md` | *When* to ingest, *how* to judge co-reference, evidence, reasons. |
| `skills/tms-brief/SKILL.md` | The daily brief recipe: `diff` → tensions → fragile beliefs → gaps. |
| SOUL.md snippet | The memory firewall (§5). |

**The server provides tools. The skills say when to use them.** (The emerging ecosystem convention — the pattern You.com ships for Hermes.) Skills and tool descriptions are co-dependent and must be versioned together.

## 3. Design Principles

**Principle 1 — First contact is instant.**
Hermes spawns stdio servers at startup; `hermes mcp test tmsv2` is how users first touch us. Boot time is UX. Target: the entire config entry is `uvx tmsv2`, connect-and-list happens in under a second, everything heavy (embeddings, DB pool) is lazy-initialized. Ship a `tmsv2 doctor` subcommand (Neo4j reachable, migrations current, embeddings configured) — Hermes users are trained to expect self-diagnostics.

**Principle 2 — Annotations are the trust ladder.**
Hermes gates approvals on MCP tool annotations. Get them right and users get the correct trust gradient out of the box: Browsing is free; writing to the ledger requires approval.

| tmsv2 tool | `readOnlyHint` | `destructiveHint` |
|---|---|---|
| `search_claims`, `get_evidence`, `get_claim_summary`, `get_observation`, `get_source`, `evaluate`, `what_if_retracted`, `diff` | `true` | `false` |
| `add_source`, `add_observation`, `add_claim`, `add_evidence`, `assert_same_as`, `mark_duplicate_of`, `mark_supersedes` | `false` | `true` |

Also support `TMSV2_READ_ONLY=1` — the cautious-adopter trust ladder. A read-only tmsv2 is still a useful tmsv2.

**Principle 3 — Every call is safe to abandon, and every call is safe to retry.**
Two Hermes behaviors make this mandatory rather than polite: It interrupts in-progress work when the user sends a new message, and cron sessions start with no memory of anything. Therefore:

- An intake run abandoned halfway is just a shorter ledger — never a corrupt one. (Append-only buys us this; protect it.)
- Re-running intake must be idempotent. **New requirement on the server:** An append carrying an already-seen `(source, content_hash)` pair is a no-op that returns the existing observation ID — not a duplicate. Retries and at-least-once delivery become free.
- Never batch semantically separate writes behind one tool call.

**Principle 4 — Design for the cold agent.**
Hermes's memory is *tiny* and curated. The worst failure mode for tmsv2 is the agent caching a world claim in `MEMORY.md` and answering from stale memory forever. The V1 front door already does the rest of the work — counts-first results, status facets, `search_claims` with no arguments = the whole world state — so a fresh session with zero context can orient itself in one call. Keep that property when tempted to add state.

**Principle 5 — Skills are part of the product.**
The skills are not documentation garnish; they are the recipe layer V1 promised ("recipes live in prose, not in the server"). Consequences: ship them in-repo; version them with the server; write the brief skill to be fully self-contained, because cron kills context by design. (Note Hermes's guardrail: cron sessions cannot create further cron jobs.)

**Principle 6 — Keyless and local by default.**
Hermes scrubs environment variables containing `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`, or `AUTH` before running agent-written code. Good for security — which means the server must own its configuration and never rely on the agent to relay secrets. Compute embeddings server-side with a pinned local model by default (the `embedding_model` discipline requires pinning anyway), with API fallback behind config. Ship `tmsv2 load-demo` to seed the V1 §10 dataset, so a new user sees a believed/contested world in their first sixty seconds.

**Principle 7 — Spec-clean beats convenient.**
Hermes is at 0.21.x; `mcpServers` vs `mcp_servers` mistakes happen; schemas churn. Pin our MCP SDK version, couple to nothing Hermes-specific, and stay portable to OpenClaw and ZeroClaw. The long-term distribution win is the **Nous curated MCP catalog** (reviewed manifest, prompted credentials, automatic tool checklist) — the difference between "works with Hermes" and "discoverable in Hermes." Everything in this document is roughly its review criteria anyway.

## 4. Installation Reference

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  tmsv2:
    command: uvx
    args: ["--project", "/path/to/tmsv2", "tmsv2"]
```

```text
hermes mcp test tmsv2     # connect, list tools, exit 0/1
hermes tools list         # confirm registration
/reload-mcp               # from chat, after config changes
```

The running gateway also watches `config.yaml` and hot-reloads MCP changes within about a minute. Gotcha for anyone copying from Claude Code docs: the key is `mcp_servers` (underscore). Hermes ships `hermes import-agent claude-code` precisely because of that mistake.

## 5. The Memory Firewall

The one thing the SOUL.md snippet must establish, and the skill files must reinforce:

> **World facts live in the tmsv2 ledger — never in your memory files.** Store the *habit* of querying the ledger, never its contents. Before asserting a fact to the user, search the ledger and cite claim IDs. New documents go through the intake skill, never paraphrased from memory.

This is a deliberate separation of categories: Hermes's memory is the agent's *relationship with you* (preferences, projects, operational continuity). The ledger is the *state of the world*, with provenance, attackable and re-derivable. Conflating them would make world state hostage to a fast-moving agent's schema churn.

## 6. Cron Today, Triggers Tomorrow

The daily brief is the only time-based trigger we ship, because a digest is a *read* of world state, not a *reaction* to change. The long-term architecture is event-driven, and the ledger already provides the semantics:

```
dumb fetchers (pollers, quarantined)  →  append observations
                                        ↓ every append re-evaluates the affected subgraph
status flips (the only events that matter)
                                        ↓
watch rules ("tell me when status(X) changes", "when independent_sources(X) increases")
                                        ↓
agent tasks / notifications
```

Polling is quarantined to the dumbest layer. The write path is the event stream; `diff` is the change-data-capture mechanism; `content_hash` idempotency makes at-least-once delivery safe. Hermes's webhook platform is the dispatch surface. The daily brief is what *nothing happened* looks like.

## 7. Non-Goals

- **No fork.** If a need ever seems to require one, re-read §0.
- **No reading Hermes's internal state.** Its SQLite, its schemas, its memory files are rental equipment. Our state lives in Neo4j.
- **No Hermes-only behavior.** If a feature only works in Hermes, that's a bug in our server or a missing MCP feature — file it as one or the other.

## 8. Adoption Checklist

Order matters; each step is independently useful.

- [ ] FastMCP server, V1 §7 surface, stub Neo4j layer — boots in <1s
- [ ] Tool annotations per §3; `hermes mcp test` passes clean
- [ ] Append idempotency: `(source, content_hash)` no-op dedup
- [ ] `tmsv2 doctor` + `tmsv2 load-demo`
- [ ] `skills/tms-intake/SKILL.md` + `skills/tms-brief/SKILL.md`, self-contained, versioned with the server
- [ ] SOUL.md snippet with the memory firewall
- [ ] `TMSV2_READ_ONLY=1` mode
- [ ] GEPA optimization loop: tool descriptions + skills, per-model variants pinned like `embedding_model`
- [ ] Catalog submission once the above are boring
