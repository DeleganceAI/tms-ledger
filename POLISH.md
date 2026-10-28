# Polish: Paranoy for real users

The 2026-10-28 polish list. Each item is a stacked PR off `main`, merged in order. A box is ticked when its PR is open.

## Checklist

- [x] 1. Rename "TMS ledger" to Paranoy in user-facing text ([#68](https://github.com/DeleganceAI/tms-ledger/pull/68))
- [x] 2. One shared header on every page, the dashboard's sections as a second bar, a ☰ menu on phones ([#69](https://github.com/DeleganceAI/tms-ledger/pull/69))
- [x] 3. One visual system and consistent page titles ([#69](https://github.com/DeleganceAI/tms-ledger/pull/69))
- [x] 4. Collections page as the signed-in home: cards on the left, a zoomable pin board on the right ([#70](https://github.com/DeleganceAI/tms-ledger/pull/70))
- [x] 5. Full-page chat per collection, approved accounts only, with the records it reads beside it (Polish 4)
- [x] 13a. chat.js only for signed-in people; no 404 in the console ([#69](https://github.com/DeleganceAI/tms-ledger/pull/69))

## Decisions

1. **Rename.** Only text people read changes. The domain, the repo name, the `TMS_*` settings, the MCP server name (`tms`), its tool names and the event kinds stay, so connected agents and their configs keep working. "Paranoy is a truth maintenance system (TMS)" keeps the acronym explained in the docs. The `not a TMS kind` error stays: it names the protocol's kind range, not the product.

2. **Header.** `tms/site.py` builds it once; every page has a `<!--HEADER-->` slot the handler fills (the admin and docs pages, which are Python strings, call it directly). It reads only the cookie, so it costs no query. Signed in: Collections, Submit, Dashboard ▾, Communities, Docs, then your name (to Account) and Log out. Signed out: Communities, Docs, Office, then Log in and Sign up. "Ledger home" and the docs' extra header links went: the docs sidebar now carries the Markdown link.
3. **Second bar.** The dashboard's tabs (Overview, Activity, Browse, Agents, Npubs, Sources) live in `nav.subnav` under the header. On the dashboard it is pinned; elsewhere hovering Dashboard, or clicking its ▾, pops it over the page. Tabs are hash links (`/dashboard#agents`), so they can be bookmarked. On phones the sections sit inside the ☰ menu under Dashboard, and on the dashboard the bar scrolls sideways.
4. **Visual system.** `tms/site.css` holds the colours (the dark purple the app already used, Paranoy's amber as the one action colour, blue kept for links and record IDs), the fonts (system sans, Georgia italic for the logo) and the header. Primary buttons are amber everywhere, secondary ones outlined. The dashboard keeps its denser type. Titles read "Paranoy · <page>". The CSS and JS URLs carry a content hash, so they cache for a day and still change on deploy.
5. **Chat loading.** Visitors get no `chat.js`. Signed-in non-admins get `{"enabled": false}` from `/dashboard/api/chat` instead of a 404.

6. **Collections page.** Signed in, `/` is now your collections: a card for each one (topic, role, public, counts, Members and Export) and, on the right, a pin board of the selected collection. Account settings (profile, key, terms, topic and visibility, new collection, agents) stay on `/connect`, which the header calls Account. `/?c=<slug>` opens a given board.
7. **Pin board.** Evidence is a paper, a claim an index card. Links are strings coloured by relation (green supports, amber qualifies, red rebuts), and a contradiction is the office's red zigzag. The layout is a force layout computed in the browser on every load: strings pull linked pins together, pins push each other apart, and a last pass stops them overlapping. Nothing is stored and there are no new tables. The board shows the newest 300 evidence and 300 claims and says so when there are more (the layout takes 0.3 s for 600 pins). Click a pin to open its record beside the board, dim everything unrelated, and step along its links. You can pan by dragging or with the arrow keys, zoom with the wheel, a pinch, +/−, or Fit, and press 0 to fit.

8. **Chat.** `/c/<slug>/chat` replaces the admin popup (`chat.js` is gone): one page per collection, with the conversation on the left and the records the agent reads on the right. The server pulls those records out of each tool result before truncating it and streams them as a `records` event. Records the answer cites by id get a **cited** mark and move to the top, and clicking an id in the answer jumps to its card. Any member can open the page. Only approved accounts (TMS_APPROVED, admins, limits lifted in /admin) can send, because every turn costs model calls. Everyone else sees the chat greyed out with "Email dustin@delegance.ai for access to the chat" (`TMS_CONTACT`), and the API refuses them before any model call. Collections get a Chat link on their card and a "Chat with it" button over the board. Conversations still stay in the browser tab only.

## SQL to apply

None yet.
