# tms bot prompt templates

Templates for agents that work a Paranoy ledger. Anyone running their own ledger can copy one, fill in the placeholders, and use it. They are not tied to a particular operator, collection, or machine. They are not the MCP prompts the server serves (`briefing`, `claims_pass`). Those, and the protocol, live at `/docs` on the server.

## How to adapt one

1. Copy the file into the agent's standing instructions.
2. Replace every placeholder in that file's **Fill these in** section. Use the same value wherever the name repeats.
3. Keep the **The team** section as it is. It tells each agent what tms is for, what its teammates do, and that it only has to do its own job. It is the same in every template except that each one leaves its own bot out of the teammates list. If you do not run one of the bots, delete its line from every template, and change the section in all of them together.
4. Leave the method in place. Writers authenticate with their own Nostr key and never print the nsec. They sign the terms and publish a profile before the first write. Every writer runs a deterministic loop with one LLM call per item, checkpoints as it goes, and dedupes before writing. Every writer except the Fool logs the real candidates it rejects to `<REJECT_LOG>`. None of them invent sources.
5. Point the agent at `<SERVER_URL>/docs` for tools, event kinds, and signing. Do not paste a snapshot of those details into the prompt.
6. Keep the key file at `<KEY_PATH>` on the machine that runs the agent. Do not paste the key into the prompt, the journal, or an issue report.
7. `<STATE_DIR>` is local bookkeeping (checkpoints, journals, the overview). It is not a collection.
8. `<REJECT_LOG>` is one shared file, a JSON line per rejected candidate, that every writing bot on the ledger appends to and the Fool reads. Point every template at the same path.
9. `<REPORT_TO>` is whoever should hear that a pass did something: a person, or another agent. The agent stays quiet when nothing changed.
10. `<OWNER>` is the person the agent answers when they ask directly. That can be the same party as `<REPORT_TO>`.

| Placeholder | Fill with |
|---|---|
| `<OWNER>` | The person the agent works for. |
| `<SERVER_URL>` | Ledger base URL, with no path. The guide is `<SERVER_URL>/docs`. |
| `<COLLECTION>` | A collection slug. Some templates allow a list, or every collection the key can read. |
| `<KEY_PATH>` | Path to this agent's own Nostr key. |
| `<STATE_DIR>` | Directory for checkpoints and notes. |
| `<REJECT_LOG>` | Shared reject log, the same file for every bot. |
| `<REPORT_TO>` | Recipient of short pass summaries. |

Scout adds `<TOPIC>`, `<SCOPE>`, and `<HYPOTHESES>`, described in its own file.

## How they fit together

Scouts add evidence: each owns one collection and hunts for full-text sources for and against its seed hypotheses, adding any claims it comes across. Claim Miner extracts claims from those documents. Linker links claims to evidence already in the collection. tms-gap-finder looks for rebuttals and qualifications and adds full-text counter-evidence when it is missing. Every bot that turns down a real candidate logs it, and the Fool argues for the rejects, publishing the ones that are real sources with real content, and hunts for fringe evidence the others miss. Ponder is a read-only reflective reader, skeptical of its own first reactions. Ledger manages the collections: what exists, who writes where, and whether the records are healthy.

## Bots

| Bot | Role |
|---|---|
| [Scout](scout.md) | Owns one collection and keeps it fed with balanced, full-text evidence from real sources, plus claims it comes across. One template, filled in per topic. |
| [Ledger](ledger.md) | Manages the collections: what exists, who writes where, searches, proofs, and ledger health. |
| [Claim Miner](claim-miner.md) | Extracts distinct, falsifiable claims from evidence documents and links each new claim to the document it came from. |
| [Linker](linker.md) | Links existing evidence to claims when that evidence supports, rebuts, or qualifies the claim. |
| [Ponder](ponder.md) | Read-only reflective reader. Journals about one collection a day, writes nothing, and checks its first reactions before reporting them. |
| [tms-gap-finder](tms-gap-finder.md) | Looks for rebuttals and qualifications of a collection's claims and adds full-text counter-evidence. |
| [The Fool](fool.md) | Reviews the shared reject log, argues for the contrarian and impolite takes, and publishes rejects that are real sources. Also hunts for fringe evidence. |
