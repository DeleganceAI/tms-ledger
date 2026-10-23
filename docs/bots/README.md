# tms bot prompts

Standing instructions for the bots Dustin runs against this ledger, copied from each bot's saved profile on Oct 22, 2026. Each file below holds that text verbatim. These are operator instructions. The server does not assign this work, and these are not the MCP prompts the service serves (`briefing`, `claims_pass`).

## How they fit together

Collectors add evidence. Burn Rate, Chronos, Forge, Milkshake and Nomad each write full-text documents into a collection. Claim Miner extracts claims from those documents. Linker links claims to evidence already in the collection, as support, rebuttal or qualification. tms-gap-finder looks for counter-evidence. Ponder is a read-only reflective reader: it journals about a collection and does not write to the ledger. Ledger manages the collections: what exists, who writes where, and whether the records are healthy.

The worker bots send short updates to Churchill, Dustin's chief of staff, and stay quiet when nothing changed. Ledger also answers Dustin directly when he messages it.

tms-gap-finder's prompt isn't captured yet. It has no saved profile; the note in its file is all that was kept. AntiRL's saved profile does not mention tms. The profile text is included; the collection work (`alignment-rl-research`) was given in chat on Oct 22 and is not part of that profile.

## Bots

| Bot | Role |
|---|---|
| [Burn Rate](burn-rate.md) | Collects AI-industry finance evidence: filings, burn, compute commitments, circular deals, and bubble arguments with their rebuttals. |
| [Chronos](chronos.md) | Collects full-text evidence on whether experienced time is discrete moments rather than a continuous flow, into `time-and-reality`. |
| [Claim Miner](claim-miner.md) | Extracts distinct, falsifiable claims from evidence documents and links each new claim to the document it came from. |
| [Forge](forge.md) | Collects evidence on AI coding agents, harnesses and the dev-tools fundraising scene into `agentic-dev-tools`. |
| [Ledger](ledger.md) | Manages the collections: what exists, who writes where, searches, proofs and ledger health. |
| [Linker](linker.md) | Links existing evidence to claims when that evidence supports, rebuts or qualifies the claim. |
| [Milkshake](milkshake.md) | Collects full-text evidence on the dollar, Fed policy and dollar-milkshake theory into `dollar-macro`. |
| [Nomad](nomad.md) | Collects evidence for and against decentralized, serverless AI into `homeless-ai`. |
| [Ponder](ponder.md) | Read-only reflective reader that visits one collection a day and journals, without writing to the ledger. |
| [tms-gap-finder](tms-gap-finder.md) | Looks for counter-evidence and contradictions. Prompt isn't captured yet. |
| [AntiRL](antirl.md) | Tracks arguments that reinforcement learning is a dangerous way to train AI. Saved profile does not mention tms. |
