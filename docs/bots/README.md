# tms bot prompts

Standing instructions for the general bots that work across collections on this ledger, taken from each bot's saved profile on Oct 22, 2026. Collection names are written as `<collection>` (or "a collection"), and agent ids are removed. Otherwise the text is as saved. These are operator instructions. The server does not assign this work, and these are not the MCP prompts the service serves (`briefing`, `claims_pass`).

## How they fit together

Collectors add evidence. Claim Miner extracts claims. Linker links claims to evidence. tms-gap-finder looks for counter-evidence and gaps in a collection. Ponder is a read-only reflective reader: it journals about a collection and does not write to the ledger. Ledger manages the collections.

The worker bots send short updates to Churchill, Dustin's chief of staff, and stay quiet when nothing changed. Ledger also answers Dustin directly when he messages it.

tms-gap-finder's prompt is not yet captured. It has no saved profile.

## Bots

| Bot | Role |
|---|---|
| [Ledger](ledger.md) | Manages the collections: what exists, who writes where, searches, proofs and ledger health. |
| [Claim Miner](claim-miner.md) | Extracts distinct, falsifiable claims from evidence documents and links each new claim to the document it came from. |
| [Linker](linker.md) | Links existing evidence to claims when that evidence supports, rebuts or qualifies the claim. |
| [Ponder](ponder.md) | Read-only reflective reader that visits one collection a day and journals, without writing to the ledger. |
| [tms-gap-finder](tms-gap-finder.md) | Looks for counter-evidence and gaps in a collection. Prompt not yet captured. |
