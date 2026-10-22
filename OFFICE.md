# Live office (spec)

Builds on PR #5 (`/office`, `tms/office.html`, `window.botOffice` hooks). The office becomes the logged-out landing page and is driven by real but anonymous ledger data. Expect to tweak the visuals; the data contract below is the part to get right.

## 1. Boards

- **One board per collection**, on easels on the office floor. A small thumbnail wall at the back shows every board, with the one facing out highlighted.
- **Boards flip over their horizontal axis**, like a whiteboard on a stand. Before a bot pins something, the board it's heading to flips to that collection. When nothing is happening, boards cycle through collections slowly.
- **Visual language:**

  | Ledger | On the board |
  |---|---|
  | claim | an index card |
  | claim with no links | a yellow card, unstrung: a hypothesis |
  | evidence | a paper (squiggles only) |
  | link | string from paper to card: green SUPPORTS, red REBUTS, amber QUALIFIES |
  | contradiction | a red zigzag across its two or more cards |

- **Layout:** force-directed, seeded by the slice ID, so the same slice always looks the same.

## 2. Slices, never whole graphs

Collections will get massive, so a board only ever shows a **slice**.

- **Building a slice:** pick a root node, then breadth-first through links and contradictions until there are about 40 nodes (cards plus papers). Cap each node's branching factor so one hub doesn't fill the whole slice.
- **Edges leaving the slice** are drawn as strings running off the board's edge. A big collection spills strings off every side; a small one sits neatly inside its frame. That shows scale without numbers.
- **Choosing the root:**
  - For a replayed event: the record that was added, so the bot pins where it really connects.
  - For idle cycling: rotate through recently active claims.

## 3. Bot reactions

When a bot adds something, it shows a speech bubble:

| Event | Bubble |
|---|---|
| evidence | `!` or a small doc icon |
| link SUPPORTS | `✓` |
| link QUALIFIES | `~` |
| link REBUTS | `!?` |
| contradiction | one `?` per claim in it (`??` … `????`), plus a head-scratch animation |

**Standing confusion:** while a board faces out, a bot beside it shows 0–4 floating `?`. The count is a bucket of the collection's contradictions per claim. Never show the raw number.

## 4. `/office.json` (public, cached, recomputed hourly)

```json
{
  "generated_at": "2026-10-21T20:00:00Z",
  "totals": {"evidence": 0, "claims": 0, "links": 0, "contradictions": 0, "collections": 0, "contributors": 0},
  "boards": [
    {"id": "b_<random>", "confusion": 0, "slices": [
      {"id": "s_<random>", "nodes": [{"i": 0, "t": "claim"}, {"i": 1, "t": "evidence"}],
       "edges": [[1, 0, "S"]], "contradictions": [[0, 2]], "off_edge": [[0, 3]]}
    ]}
  ],
  "replay": [{"board": "b_<random>", "slice": "s_<random>", "kind": "link", "relation": "S", "node": 1, "claims": 0, "t": 312}]
}
```

- **Anonymous by construction.** Board and slice IDs are random each hour, and boards are shuffled. There are no slugs, owners, pubkeys, text, record IDs or timestamps, only `t`, a seconds offset within the hour.
- **Small collections:** under 10 records, a collection counts toward `totals` but gets no board.
- **Size:** a few idle slices per board plus one slice per replay event, capped at about 200 replay events per hour. The JSON stays small however big the ledger gets.
- **Replay:** the previous hour's events, played back at real pace or sped up, through the `botOffice` hooks.

## 5. Landing page

- **Logged out:** `/` shows the office full-width, with global totals overlaid (for example "1,240 papers · 312 claims · 9 contradictions across 6 private collections") and a **Request access** call to action.
- **After connecting:** the existing flow. `/office` stays as a direct link.

## 6. Request access

- **The form:** an npub field plus an optional note (500 characters max). There's no signing, because the visitor may not have an extension yet. Rate-limited per IP, and the same npub can't have more than one pending request.
- **Storage:** an operational table, `access_requests` (npub, note, at, status).
- **In `/admin`:** a list of pending requests with Approve and Dismiss buttons.
- **Approvals move into the database:** a new `approvals` table (pubkey, approved_by, at). Access becomes `TMS_ADMINS ∪ TMS_APPROVED (env, bootstrap) ∪ approvals`, so approving someone doesn't need a redeploy.
- **Schema changes** are applied by hand with doadmin, then GRANTed to `tms`, as before.

## 7. Tests

- `/office.json` contains no slugs, pubkeys, record IDs or text from a seeded ledger.
- Collections under the size threshold get no board.
- Slices are capped at about 40 nodes.
- The request-access rate limit works.
- Approve from `/admin` grants access without a restart.
