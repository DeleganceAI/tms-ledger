# tms bot prompt templates

Templates for agents that work a tms ledger. Anyone running their own ledger can copy one, fill in the placeholders, and use it. They are not tied to a particular operator, collection, or machine. They are not the MCP prompts the server serves (`briefing`, `claims_pass`). Those, and the protocol, live at `/docs` on the server.

## How to adapt one

1. Copy the file into the agent's standing instructions.
2. Replace every placeholder in that file's **Fill these in** section. Use the same value wherever the name repeats.
3. Leave the method in place. Writers authenticate with their own Nostr key and never print the private key. They sign the terms and publish a profile before the first write. Claim Miner, Linker, and tms-gap-finder run a deterministic loop with one LLM call per item, checkpoint as they go, and dedupe before writing. None of them invent sources.
4. Point the agent at `<SERVER_URL>/docs` for tools, event kinds, and signing. Do not paste a snapshot of those details into the prompt.
5. Keep the key file at `<KEY_PATH>` on the machine that runs the agent. Do not paste the key into the prompt, the journal, or an issue report.
6. `<STATE_DIR>` is local bookkeeping (checkpoints, journals, the overview). It is not a collection.
7. `<REPORT_TO>` is whoever should hear that a pass did something: a person, or another agent. The agent stays quiet when nothing changed.
8. `<OWNER>` is the person the agent answers when they ask directly. That can be the same party as `<REPORT_TO>`.

| Placeholder | Fill with |
|---|---|
| `<OWNER>` | The person the agent works for. |
| `<SERVER_URL>` | Ledger base URL, with no path. The guide is `<SERVER_URL>/docs`. |
| `<COLLECTION>` | A collection slug. Some templates allow a list, or every collection the key can read. |
| `<KEY_PATH>` | Path to this agent's own Nostr key. |
| `<STATE_DIR>` | Directory for checkpoints and notes. |
| `<REPORT_TO>` | Recipient of short pass summaries. |

## How they fit together

Collectors add evidence. Claim Miner extracts claims from those documents. Linker links claims to evidence already in the collection. tms-gap-finder looks for rebuttals and qualifications and adds full-text counter-evidence when it is missing. Ponder is a read-only reflective reader, skeptical of its own first reactions. Ledger manages the collections: what exists, who writes where, and whether the records are healthy.

## Bots

| Bot | Role |
|---|---|
| [Ledger](ledger.md) | Manages the collections: what exists, who writes where, searches, proofs, and ledger health. |
| [Claim Miner](claim-miner.md) | Extracts distinct, falsifiable claims from evidence documents and links each new claim to the document it came from. |
| [Linker](linker.md) | Links existing evidence to claims when that evidence supports, rebuts, or qualifies the claim. |
| [Ponder](ponder.md) | Read-only reflective reader. Journals about one collection a day, writes nothing, and checks its first reactions before reporting them. |
| [tms-gap-finder](tms-gap-finder.md) | Looks for rebuttals and qualifications of a collection's claims and adds full-text counter-evidence. |
