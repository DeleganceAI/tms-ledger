# Polish: Paranoy for real users

The 2026-10-28 polish list. Each item is a stacked PR off `main`, merged in order. A box is ticked when its PR is open.

## Checklist

- [x] 1. Rename "TMS ledger" to Paranoy in user-facing text ([#68](https://github.com/DeleganceAI/tms-ledger/pull/68))

## Decisions

1. **Rename.** Only text people read changes. The domain, the repo name, the `TMS_*` settings, the MCP server name (`tms`), its tool names and the event kinds stay, so connected agents and their configs keep working. "Paranoy is a truth maintenance system (TMS)" keeps the acronym explained in the docs. The `not a TMS kind` error stays: it names the protocol's kind range, not the product.

## SQL to apply

None yet.
