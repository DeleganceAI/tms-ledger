# Polish: Paranoy for real users

The 2026-10-28 polish list. Each item is a stacked PR off `main`, merged in order. A box is ticked when its PR is open.

## What landed

Seven stacked PRs; merge them in this order (each targets the one before, so merging #68 into `main` and then retargeting the next is the usual dance, or merge #74 into #73 and so on down, then #68 into `main`):

| # | PR | Items |
|---|---|---|
| 1 | [#68](https://github.com/DeleganceAI/tms-ledger/pull/68) | Rename to Paranoy |
| 2 | [#69](https://github.com/DeleganceAI/tms-ledger/pull/69) | Shared header, dashboard second bar, phone menu, one stylesheet, titles |
| 3 | [#70](https://github.com/DeleganceAI/tms-ledger/pull/70) | Collections page with the pin board |
| 4 | [#71](https://github.com/DeleganceAI/tms-ledger/pull/71) | Chat page per collection, approved accounts only |
| 5 | [#72](https://github.com/DeleganceAI/tms-ledger/pull/72) | + buttons, login and back, first-run guide, Connect an agent, usage meter |
| 6 | [#73](https://github.com/DeleganceAI/tms-ledger/pull/73) | Ask to join (**needs `db/migrate_join_requests.sql` first**) |
| 7 | Polish 7 | Names not hex, Agents by account, error breakdown, accessibility |

Every PR passed `test_smoke.py` and `test_events.py` and was checked in a local preview at desktop and phone widths; screenshots are in each PR (stored on the `polish-screenshots` branch, which can be deleted after merging).

## Checklist

- [x] 1. Rename "TMS ledger" to Paranoy in user-facing text ([#68](https://github.com/DeleganceAI/tms-ledger/pull/68))
- [x] 2. One shared header on every page, the dashboard's sections as a second bar, a ☰ menu on phones ([#69](https://github.com/DeleganceAI/tms-ledger/pull/69))
- [x] 3. One visual system and consistent page titles ([#69](https://github.com/DeleganceAI/tms-ledger/pull/69))
- [x] 4. Collections page as the signed-in home: cards on the left, a zoomable pin board on the right ([#70](https://github.com/DeleganceAI/tms-ledger/pull/70))
- [x] 5. Full-page chat per collection, approved accounts only, with the records it reads beside it ([#71](https://github.com/DeleganceAI/tms-ledger/pull/71))
- [x] 6. A + button to add an npub (members, admins, agents, stewards) instead of editing a text list ([#72](https://github.com/DeleganceAI/tms-ledger/pull/72))
- [x] 7. Signed-out visitors to signed-in pages go to Login with a reason, and come back after ([#72](https://github.com/DeleganceAI/tms-ledger/pull/72))
- [x] 8. First-run guide on the collections page, and a Connect an agent panel with MCP config and a starter prompt ([#72](https://github.com/DeleganceAI/tms-ledger/pull/72))
- [x] 9. Usage meter for free accounts ([#72](https://github.com/DeleganceAI/tms-ledger/pull/72))
- [x] 10. Request-to-join on Communities; the owner sees it and accepts it in the app ([#73](https://github.com/DeleganceAI/tms-ledger/pull/73))
- [x] 11. Names instead of hex keys, npub on hover with a copy button; the dashboard's Agents table grouped by account (Polish 7)
- [x] 12. Why ledger-grokbot errors: the dashboard now lists each key's error messages, and auth failures count against the key that signed them (Polish 7; see below)
- [x] 13. Small fixes: the Ledger box ([#72](https://github.com/DeleganceAI/tms-ledger/pull/72)); chat.js only for signed-in people ([#69](https://github.com/DeleganceAI/tms-ledger/pull/69)); keyboard and screen-reader pass (every PR, finished in Polish 7)

## Decisions

1. **Rename.** Only text people read changes. The domain, the repo name, the `TMS_*` settings, the MCP server name (`tms`), its tool names and the event kinds stay, so connected agents and their configs keep working. "Paranoy is a truth maintenance system (TMS)" keeps the acronym explained in the docs. The `not a TMS kind` error stays: it names the protocol's kind range, not the product.

2. **Header.** `tms/site.py` builds it once; every page has a `<!--HEADER-->` slot the handler fills (the admin and docs pages, which are Python strings, call it directly). It reads only the cookie, so it costs no query. Signed in: Collections, Submit, Dashboard ▾, Communities, Docs, then your name (to Account) and Log out. Signed out: Communities, Docs, Office, then Log in and Sign up. "Ledger home" and the docs' extra header links went: the docs sidebar now carries the Markdown link.
3. **Second bar.** The dashboard's tabs (Overview, Activity, Browse, Agents, Npubs, Sources) live in `nav.subnav` under the header. On the dashboard it is pinned; elsewhere hovering Dashboard, or clicking its ▾, pops it over the page. Tabs are hash links (`/dashboard#agents`), so they can be bookmarked. On phones the sections sit inside the ☰ menu under Dashboard, and on the dashboard the bar scrolls sideways.
4. **Visual system.** `tms/site.css` holds the colours (the dark purple the app already used, Paranoy's amber as the one action colour, blue kept for links and record IDs), the fonts (system sans, Georgia italic for the logo) and the header. Primary buttons are amber everywhere, secondary ones outlined. The dashboard keeps its denser type. Titles read "Paranoy · <page>". The CSS and JS URLs carry a content hash, so they cache for a day and still change on deploy.
5. **Chat loading.** Visitors get no `chat.js`. Signed-in non-admins get `{"enabled": false}` from `/dashboard/api/chat` instead of a 404.

6. **Collections page.** Signed in, `/` is now your collections: a card for each one (topic, role, public, counts, Members and Export) and, on the right, a pin board of the selected collection. Account settings (profile, key, terms, topic and visibility, new collection, agents) stay on `/connect`, which the header calls Account. `/?c=<slug>` opens a given board.
7. **Pin board.** Evidence is a paper, a claim an index card. Links are strings coloured by relation (green supports, amber qualifies, red rebuts), and a contradiction is the office's red zigzag. The layout is a force layout computed in the browser on every load: strings pull linked pins together, pins push each other apart, and a last pass stops them overlapping. Nothing is stored and there are no new tables. The board shows the newest 300 evidence and 300 claims and says so when there are more (the layout takes 0.3 s for 600 pins). Click a pin to open its record beside the board, dim everything unrelated, and step along its links. You can pan by dragging or with the arrow keys, zoom with the wheel, a pinch, +/−, or Fit, and press 0 to fit.

8. **Chat.** `/c/<slug>/chat` replaces the admin popup (`chat.js` is gone): one page per collection, with the conversation on the left and the records the agent reads on the right. The server pulls those records out of each tool result before truncating it and streams them as a `records` event. Records the answer cites by id get a **cited** mark and move to the top, and clicking an id in the answer jumps to its card. Any member can open the page. Only approved accounts (TMS_APPROVED, admins, limits lifted in /admin) can send, because every turn costs model calls. Everyone else sees the chat greyed out with "Email dustin@delegance.ai for access to the chat" (`TMS_CONTACT`), and the API refuses them before any model call. Collections get a Chat link on their card and a "Chat with it" button over the board. Conversations still stay in the browser tab only.

9. **+ buttons.** Every key list (a collection's people and admins, your agents, your stewards) is now a list of names with a × each and a "+ Add" field that takes an npub or hex key. Each change still signs the whole new list, because that is what those events carry, so nothing changes on the server. Removing asks first. The Ledger stays a single field with its own Save. Its row is now full width, which also fixes the Ledger box sitting lower than the Agents box (item 13).
10. **Login and back.** `/dashboard`, `/submit`, `/c/<slug>/members` and `/c/<slug>/chat` send signed-out visitors to `/connect?next=<path>`. The page says why ("Log in to see your dashboard.") and returns there after an extension, sign-up or email login. `next` must be a path on this site.
11. **First run.** A "Getting started" card tops the collections page for human accounts until its five steps are done (sign the terms, create a collection, connect your Ledger, add agents, pick where they work) or it is hidden. Each step ticks itself off from the account as it stands, and nothing new is stored.
12. **Connect an agent.** This panel under Your agents gives the key step (`tms-sign keygen`), the MCP config (`{"mcpServers": {"paranoy": {"type": "http", "url": "<base>/mcp"}}}`) and a starter prompt naming your collections, with copy buttons and links to the bot templates and the signing docs. The panel says plainly that every call is signed, since a bare MCP client can list tools but not call them.
13. **Usage meter.** `/api/me` now has `usage` for free accounts: records, collections and agents against their limits. It uses the same counts the write path checks. The Account page shows three bars, and the collections page shows a one-line summary with a mailto to `TMS_CONTACT`. At the collection limit, the New collection card turns into that note. Approved accounts see no meter.

14. **Join requests.** A request is a note to an owner, not a ledger record, so it lives in a small operational table (`join_requests`, like `signups` and `approvals`) rather than as a new event kind. Accepting is the existing members list (kind 4705) with the person added, signed by the owner or an admin. A request counts as pending while its key is not a member and nobody has dismissed it, so accepting needs no second write. Only signed-in keys with an account can ask, only public collections take requests, and each key gets one request per collection, with a note of up to 280 characters. Owners and admins see requests on the members page, with Accept and Dismiss, and a badge on the collection's card. Owners who signed in by email also get an email (through the existing Resend sender). Extension-only owners have no address, so they see requests only in the app.

15. **Names, not hex.** Everywhere a key shows (the dashboard's records, calls, agents, npubs and drawer, the members table, board pins), it is the profile name, or a short npub (`npub1abcd…wxyz`) when there is none; the full npub is on hover, and ⧉ copies it. Raw hex stays only inside the drawer's signed event. The dashboard turns hex into npubs in the browser (a small bech32 encoder), so the APIs are unchanged except `agents`, which now carries `npub`.
16. **Agents by account.** The Agents tab groups keys under their account: the human first, then their Ledger and agents (tagged and indented), groups ordered by latest activity, keys in no account last. A signed-up human with no account event yet heads their own group.
17. **ledger-grokbot's errors.** I could not look at production's numbers: reading the production database or dashboard was refused by the session's safety classifier, and the brief said not to touch production, so I left it. What the code shows instead: an auth failure (a stale request outside the 60-second window, or a replayed one) was logged with *no* pubkey, so those never counted against any agent. The 107 errors on ledger-grokbot are therefore all post-authentication failures: tool-level errors such as bad arguments (`limit must be an integer between 1 and 200` is the commonest in the tests), embedding rate limits (429), a quote not found in its evidence, or a collection it isn't in. Two changes: (a) each agent's error count on the Agents tab is now a button that lists its commonest messages (top six, with counts and when last seen; only from calls whose collections are all yours, as the calls feed already did), so the cause is one click away once this deploys; (b) a request whose signature checks out is now attributed to its signer even when it is then refused as stale or replayed, so clock-skew and retry bugs show up against the agent too. Whatever grokbot's top message turns out to be, it is almost certainly the bot's call shape (its prompt or client), not the server; if it is the 429s, the fix is on our side (a higher embedding rate limit or more keyword fallback) and worth a follow-up.
18. **Accessibility.** A skip link and visible focus ring on every page; the header's menus are buttons with `aria-expanded`; current pages carry `aria-current`; reduced motion is honoured. New pages: pins are buttons with labels, the board pans and zooms from the keyboard, opening a pin moves focus into its panel and Esc returns it; chat is a labelled form with a live log; meters are `progressbar`s; key lists' add and remove controls are labelled. An automated pass over eight pages found unlabelled fields on Account (topic inputs) and Submit (claim rows); both now have labels.

## Not done

- Production numbers for ledger-grokbot (see 17): open the Agents tab after Polish 7 deploys, or ask me to read them with your go-ahead.
- Admins have no Admin link in the header (it would need a database query on every page); `/admin` still works.

## SQL to apply

Apply by hand as doadmin, before deploying the PR that needs it:

| PR | File | What |
|---|---|---|
| Polish 6 | `db/migrate_join_requests.sql` | `join_requests` table, `GRANT SELECT, INSERT, UPDATE` to `tms` |
