# Polish: Paranoy for real users

The 2026-10-28 polish list. Each item is a stacked PR off `main`, merged in order. A box is ticked when its PR is open.

## Checklist

- [x] 1. Rename "TMS ledger" to Paranoy in user-facing text ([#68](https://github.com/DeleganceAI/tms-ledger/pull/68))
- [x] 2. One shared header on every page, the dashboard's sections as a second bar, a ☰ menu on phones (Polish 2)
- [x] 3. One visual system and consistent page titles (Polish 2)
- [x] 13a. chat.js only for signed-in people; no 404 in the console (Polish 2)

## Decisions

1. **Rename.** Only text people read changes. The domain, the repo name, the `TMS_*` settings, the MCP server name (`tms`), its tool names and the event kinds stay, so connected agents and their configs keep working. "Paranoy is a truth maintenance system (TMS)" keeps the acronym explained in the docs. The `not a TMS kind` error stays: it names the protocol's kind range, not the product.

2. **Header.** `tms/site.py` builds it once; every page has a `<!--HEADER-->` slot the handler fills (the admin and docs pages, which are Python strings, call it directly). It reads only the cookie, so it costs no query. Signed in: Collections, Submit, Dashboard ▾, Communities, Docs, then your name (to Account) and Log out. Signed out: Communities, Docs, Office, then Log in and Sign up. "Ledger home" and the docs' extra header links went: the docs sidebar now carries the Markdown link.
3. **Second bar.** The dashboard's tabs (Overview, Activity, Browse, Agents, Npubs, Sources) live in `nav.subnav` under the header. On the dashboard it is pinned; elsewhere hovering Dashboard, or clicking its ▾, pops it over the page. Tabs are hash links (`/dashboard#agents`), so they can be bookmarked. On phones the sections sit inside the ☰ menu under Dashboard, and on the dashboard the bar scrolls sideways.
4. **Visual system.** `tms/site.css` holds the colours (the dark purple the app already used, Paranoy's amber as the one action colour, blue kept for links and record IDs), the fonts (system sans, Georgia italic for the logo) and the header. Primary buttons are amber everywhere, secondary ones outlined. The dashboard keeps its denser type. Titles read "Paranoy · <page>". The CSS and JS URLs carry a content hash, so they cache for a day and still change on deploy.
5. **Chat loading.** Visitors get no `chat.js`. Signed-in non-admins get `{"enabled": false}` from `/dashboard/api/chat` instead of a 404.

## SQL to apply

None yet.
