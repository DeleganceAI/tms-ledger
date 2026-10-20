"""Local dashboard for watching the ledger and MCP activity.

    tms-ui   ->  http://127.0.0.1:8780

Read-only, localhost only, no auth: never put it behind the tunnel. Polls the
database every two seconds; the server's `mcp_calls` table supplies call stats.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import ledger as L

COUNTS_SQL = """SELECT
  (SELECT count(*) FROM collections) AS collections, (SELECT count(*) FROM authors) AS authors,
  (SELECT count(*) FROM sources) AS sources, (SELECT count(*) FROM observations) AS observations,
  (SELECT count(*) FROM claims) AS claims, (SELECT count(*) FROM evidence) AS evidence,
  (SELECT count(*) FROM contradictions) AS contradictions"""

RECENT_SQL = """SELECT kind, id, collection_id, author_id, asserted_at, summary FROM (
  SELECT 'observation' AS kind, id, collection_id, author_id, asserted_at, left(uri, 140) AS summary FROM observations
  UNION ALL SELECT 'claim', id, collection_id, author_id, asserted_at, left(text, 220) FROM claims
  UNION ALL SELECT 'evidence', id, NULL, author_id, asserted_at,
    relation || ' ' || target_kind || ' ' || coalesce(target_claim_id, target_contradiction_id, target_evidence_id,
                                                      target_source_id, target_observation_id)
    || ': ' || left(quote, 140) FROM evidence
  UNION ALL SELECT 'contradiction', id, collection_id, author_id, asserted_at, left(reason, 220) FROM contradictions
  UNION ALL SELECT 'source', id, NULL, author_id, asserted_at, name FROM sources
  UNION ALL SELECT 'collection', id, id, author_id, asserted_at, name FROM collections
  UNION ALL SELECT 'author', id, NULL, id, asserted_at, name || ' (' || kind || ')' FROM authors
) r ORDER BY asserted_at DESC, id LIMIT %s"""


def snapshot(conn, limit: int = 60) -> dict:
    rows = lambda sql, *params: [L._clean(r) for r in conn.execute(sql, params or None)]
    return {
        "now": datetime.now(UTC).isoformat(),
        "counts": L._clean(conn.execute(COUNTS_SQL).fetchone()),
        "collections": rows("""SELECT c.id, c.name,
              (SELECT count(*) FROM observations o WHERE o.collection_id = c.id) AS observations,
              (SELECT count(*) FROM claims k WHERE k.collection_id = c.id) AS claims,
              (SELECT count(*) FROM contradictions x WHERE x.collection_id = c.id) AS contradictions
            FROM collections c ORDER BY c.asserted_at, c.id"""),
        "calls": L._clean(conn.execute("""SELECT count(*) AS total, count(*) FILTER (WHERE NOT ok) AS errors,
              count(*) FILTER (WHERE at > now() - interval '1 hour') AS last_hour,
              count(*) FILTER (WHERE at > now() - interval '5 minutes') AS last_5m,
              count(*) FILTER (WHERE tool LIKE 'add_%') AS writes FROM mcp_calls""").fetchone()),
        "by_tool": rows("""SELECT coalesce(tool, method) AS name, count(*) AS n, count(*) FILTER (WHERE NOT ok) AS errors
            FROM mcp_calls GROUP BY 1 ORDER BY n DESC, 1"""),
        "by_author": rows("""SELECT coalesce(author_id, '(no author)') AS author_id, count(*) AS n,
              count(*) FILTER (WHERE tool LIKE 'add_%') AS writes, max(at) AS last_at
            FROM mcp_calls GROUP BY 1 ORDER BY n DESC, 1"""),
        "recent_calls": rows("""SELECT id, at, method, tool, author_id, collection, ok, left(error, 200) AS error, ms
            FROM mcp_calls ORDER BY at DESC, id DESC LIMIT %s""", limit),
        "recent_records": rows(RECENT_SQL, limit),
    }


async def index(request) -> HTMLResponse:
    return HTMLResponse(PAGE)


async def api_snapshot(request) -> JSONResponse:
    with L.connect() as conn:  # ponytail: sync psycopg on the event loop; one local viewer
        return JSONResponse(snapshot(conn))


async def api_record(request) -> JSONResponse:
    kind, id = request.path_params["kind"], request.path_params["id"]
    with L.connect() as conn:
        try:
            rec = L.get_record(conn, kind, id, max_chars=4000)
        except ValueError as err:
            return JSONResponse({"error": str(err)}, status_code=400)
        if rec and kind == "claim":
            rec["evidence"] = L.get_evidence(conn, "claim", id)
        if rec and kind == "contradiction":
            rec["evidence"] = L.get_evidence(conn, "contradiction", id)
    return JSONResponse(rec or {"error": "not found"}, status_code=200 if rec else 404)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/snapshot", api_snapshot),
    Route("/api/record/{kind}/{id}", api_record),
])


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TMS activity</title>
<style>
:root{--bg:#fcfcfb;--card:#ffffff;--ink:#1a1a19;--ink2:#5c5c58;--ink3:#8a8a85;--line:#e6e6e3;--accent:#2f6fde;--track:#e9eef8;--bad:#b4232c;--new:#fff1bf;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a19;--card:#232322;--ink:#f0f0ee;--ink2:#b4b4af;--ink3:#8a8a85;--line:#34342f;--accent:#7aa6f5;--track:#2a3345;--bad:#f08a8a;--new:#3d3516}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{display:flex;align-items:baseline;gap:16px;padding:18px 24px 6px}h1{font-size:18px;margin:0;font-weight:600}
#status{color:var(--ink3);font-size:12px}#status.err{color:var(--bad)}
main{padding:0 24px 32px;display:grid;gap:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.tile .v{font-size:28px;font-weight:600;letter-spacing:-.01em;font-variant-numeric:tabular-nums}.tile .k{color:var(--ink2);font-size:12px;margin-top:2px}
.tile.small .v{font-size:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
h2{font-size:13px;font-weight:600;color:var(--ink2);margin:0 0 10px;text-transform:uppercase;letter-spacing:.04em}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:1000px){.cols{grid-template-columns:1fr}}
.bars{display:grid;grid-template-columns:max-content 1fr max-content;gap:6px 10px;align-items:center}
.bars .name{font-family:var(--mono);font-size:12px;color:var(--ink)}.bars .n{font-variant-numeric:tabular-nums;font-size:12px;color:var(--ink2);text-align:right}
.track{height:8px;background:var(--track);border-radius:4px;overflow:hidden}.fill{height:100%;background:var(--accent);border-radius:4px}
table{width:100%;border-collapse:collapse;font-size:12.5px}td{padding:5px 8px;border-top:1px solid var(--line);vertical-align:top}tr:first-child td{border-top:0}
td.t{color:var(--ink3);white-space:nowrap;font-variant-numeric:tabular-nums;width:1%}td.k{font-family:var(--mono);white-space:nowrap;width:1%}td.a{color:var(--ink2);white-space:nowrap;width:1%}
td.s{color:var(--ink);word-break:break-word}tr.rec{cursor:pointer}tr.rec:hover td{background:color-mix(in srgb,var(--accent) 7%,transparent)}
tr.new td{animation:flash 6s ease-out}@keyframes flash{from{background:var(--new)}to{background:transparent}}
.bad{color:var(--bad)}.ok{color:var(--ink3)}
#detail{display:none;margin-top:10px}#detail pre{margin:0;max-height:360px;overflow:auto;font:12px/1.4 var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px;white-space:pre-wrap}
#detail .close{float:right;cursor:pointer;color:var(--ink3);font-size:12px}
.empty{color:var(--ink3);font-size:12.5px;padding:4px 0}
.col-list{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12.5px;color:var(--ink2)}.col-list b{color:var(--ink);font-weight:600}
</style></head><body>
<header><h1>TMS activity</h1><span id="status">connecting…</span></header>
<main>
  <section class="tiles" id="counts"></section>
  <section class="card"><h2>Collections</h2><div class="col-list" id="collections"></div></section>
  <section class="cols">
    <div class="card"><h2>MCP calls</h2><div class="tiles" id="callstats" style="margin-bottom:12px"></div>
      <h2>By tool</h2><div class="bars" id="bytool"></div></div>
    <div class="card"><h2>By author</h2><table id="byauthor"></table></div>
  </section>
  <section class="cols">
    <div class="card"><h2>Recent records</h2><table id="records"></table>
      <div id="detail"><span class="close" onclick="hideDetail()">close ×</span><pre id="detailpre"></pre></div></div>
    <div class="card"><h2>Recent calls</h2><table id="calls"></table></div>
  </section>
</main>
<script>
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ago = iso => { if (!iso) return ''; const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  return s < 60 ? `${s|0}s ago` : s < 3600 ? `${(s/60)|0}m ago` : s < 86400 ? `${(s/3600)|0}h ago` : `${(s/86400)|0}d ago`; };
const seenRec = new Set(), seenCall = new Set(); let first = true;
const tile = (k, v, small) => `<div class="tile${small?' small':''}"><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`;
function render(d) {
  document.getElementById('counts').innerHTML = ['collections','sources','observations','claims','evidence','contradictions','authors'].map(k => tile(k, d.counts[k])).join('');
  document.getElementById('collections').innerHTML = d.collections.length ? d.collections.map(c =>
    `<span><b>${esc(c.id)}</b> ${esc(c.observations)} obs · ${esc(c.claims)} claims · ${esc(c.contradictions)} findings</span>`).join('') : '<span class="empty">none yet</span>';
  const c = d.calls;
  document.getElementById('callstats').innerHTML = tile('calls total', c.total, 1) + tile('writes', c.writes, 1) + tile('errors', c.errors, 1) + tile('last hour', c.last_hour, 1) + tile('last 5 min', c.last_5m, 1);
  const max = Math.max(1, ...d.by_tool.map(t => t.n));
  document.getElementById('bytool').innerHTML = d.by_tool.length ? d.by_tool.map(t =>
    `<span class="name">${esc(t.name)}</span><div class="track"><div class="fill" style="width:${(100*t.n/max).toFixed(1)}%"></div></div><span class="n">${esc(t.n)}${t.errors ? ` <span class="bad">(${esc(t.errors)} err)</span>` : ''}</span>`).join('')
    : '<span class="empty">no calls recorded yet (restart the server after enabling logging)</span>';
  document.getElementById('byauthor').innerHTML = d.by_author.length ? d.by_author.map(a =>
    `<tr><td class="k">${esc(a.author_id)}</td><td class="s">${esc(a.n)} calls · ${esc(a.writes)} writes</td><td class="t" title="${esc(a.last_at)}">${ago(a.last_at)}</td></tr>`).join('') : '<tr><td class="empty">none yet</td></tr>';
  document.getElementById('records').innerHTML = d.recent_records.length ? d.recent_records.map(r => {
    const isNew = !first && !seenRec.has(r.id); seenRec.add(r.id);
    return `<tr class="rec${isNew?' new':''}" onclick="showDetail('${esc(r.kind)}','${esc(r.id)}')"><td class="t" title="${esc(r.asserted_at)}">${ago(r.asserted_at)}</td><td class="k">${esc(r.kind)}</td><td class="a">${esc(r.author_id)}</td><td class="s">${esc(r.summary)}</td></tr>`; }).join('')
    : '<tr><td class="empty">no records yet</td></tr>';
  document.getElementById('calls').innerHTML = d.recent_calls.length ? d.recent_calls.map(r => {
    const isNew = !first && !seenCall.has(r.id); seenCall.add(r.id);
    return `<tr class="${isNew?'new':''}"><td class="t" title="${esc(r.at)}">${ago(r.at)}</td><td class="k">${esc(r.tool || r.method)}</td><td class="a">${esc(r.author_id || '')}</td><td class="s">${r.ok ? `<span class="ok">ok · ${esc(r.ms)} ms</span>` : `<span class="bad">✕ ${esc(r.error)}</span>`}</td></tr>`; }).join('')
    : '<tr><td class="empty">no calls recorded yet</td></tr>';
  first = false;
}
async function poll() {
  const st = document.getElementById('status');
  try { const r = await fetch('/api/snapshot'); if (!r.ok) throw new Error(r.status); render(await r.json());
    st.textContent = `live · updated ${new Date().toLocaleTimeString()}`; st.className = ''; }
  catch (e) { st.textContent = `cannot reach the database or server: ${e.message}`; st.className = 'err'; }
}
async function showDetail(kind, id) {
  const box = document.getElementById('detail'), pre = document.getElementById('detailpre');
  box.style.display = 'block'; pre.textContent = 'loading…';
  try { const r = await fetch(`/api/record/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`); pre.textContent = JSON.stringify(await r.json(), null, 2); }
  catch (e) { pre.textContent = String(e); }
}
function hideDetail() { document.getElementById('detail').style.display = 'none'; }
poll(); setInterval(poll, 2000);
</script></body></html>"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8780)
    a = p.parse_args()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
