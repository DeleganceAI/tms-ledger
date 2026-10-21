"""Operator page at /admin: embedding spend, users, and a few context numbers.

Admins are the pubkeys in TMS_ADMINS, logged in with the same cookie as the other pages.
Everyone else gets a 404, so the page's existence isn't advertised. Plain tables, server-rendered.
"""
from __future__ import annotations

from html import escape

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

from . import events as E
from . import ledger as L
from .web import cookie_pubkey

SPEND_SQL = """SELECT
    coalesce(sum(cost_usd) FILTER (WHERE at >= date_trunc('day', now())), 0) AS today,
    coalesce(sum(cost_usd) FILTER (WHERE at > now() - interval '7 days'), 0) AS last_7_days,
    coalesce(sum(cost_usd) FILTER (WHERE at > now() - interval '30 days'), 0) AS last_30_days,
    coalesce(sum(cost_usd), 0) AS all_time,
    coalesce(sum(tokens), 0) AS tokens, count(*) AS calls
  FROM embed_calls"""

USERS_SQL = """WITH keys AS (
    SELECT unnest(%s::text[]) AS pubkey UNION SELECT pubkey FROM members UNION SELECT pubkey FROM events)
  SELECT k.pubkey, p.name, p.about,
         (SELECT count(*) FROM members m WHERE m.pubkey = k.pubkey) AS collections,
         (SELECT count(*) FROM collections c WHERE c.owner = k.pubkey) AS owned,
         (SELECT count(*) FROM events e WHERE e.pubkey = k.pubkey) AS events,
         greatest((SELECT max(received_at) FROM events e WHERE e.pubkey = k.pubkey),
                  (SELECT max(at) FROM mcp_calls c WHERE c.pubkey = k.pubkey)) AS last_activity
  FROM keys k LEFT JOIN profiles p ON p.pubkey = k.pubkey
  ORDER BY last_activity DESC NULLS LAST, k.pubkey"""


def report(conn) -> dict:
    users = conn.execute(USERS_SQL, (sorted(L.APPROVED),)).fetchall()
    return {
        "spend": conn.execute(SPEND_SQL).fetchone(),
        "by_pubkey": conn.execute("""SELECT e.pubkey, p.name, count(*) AS calls, sum(e.tokens) AS tokens, sum(e.cost_usd) AS cost
            FROM embed_calls e LEFT JOIN profiles p ON p.pubkey = e.pubkey GROUP BY 1, 2 ORDER BY cost DESC, calls DESC""").fetchall(),
        "by_collection": conn.execute("""SELECT collection, count(*) AS calls, sum(tokens) AS tokens, sum(cost_usd) AS cost
            FROM embed_calls GROUP BY 1 ORDER BY cost DESC, calls DESC""").fetchall(),
        "users": users,
        "db_bytes": conn.execute("SELECT pg_database_size(current_database()) AS b").fetchone()["b"],
        "per_day": conn.execute("""SELECT d::date AS day, (SELECT count(*) FROM events e
                WHERE e.received_at >= d AND e.received_at < d + interval '1 day') AS events
            FROM generate_series(date_trunc('day', now()) - interval '13 days', date_trunc('day', now()), interval '1 day') d
            ORDER BY d DESC""").fetchall(),
        "collections": conn.execute("SELECT count(*) AS n FROM collections").fetchone()["n"],
        "pubkeys": len(users),
    }


def _table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body or f'<tr><td colspan={len(headers)}>none</td></tr>'}</table>"


def _usd(v) -> str:
    return f"${float(v or 0):,.4f}"


def _who(pubkey, name) -> str:
    if not pubkey:
        return "—"
    label = escape(name) if name else escape(E.bech32_encode("npub", pubkey)[:16] + "…")
    return f'<span title="{escape(E.bech32_encode("npub", pubkey))}">{label}</span>'


def render(r: dict) -> str:
    s = r["spend"]
    when = lambda v: v.strftime("%Y-%m-%d %H:%M") if v else "—"  # noqa: E731
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TMS admin</title><style>
:root{{--bg:#f4f4f2;--panel:#fff;--line:#e2e2de;--ink:#171716;--ink3:#8c8c86;--accent:#2f6fde;--mono:ui-monospace,Menlo,monospace}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121211;--panel:#1a1a19;--line:#2b2b29;--ink:#ececea;--ink3:#74746d;--accent:#7aa6f5}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif}}main{{max-width:1100px;margin:0 auto;padding:16px}}
a{{color:var(--accent)}}h1{{font-size:18px}}h2{{font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink3);margin:22px 0 6px}}
table{{border-collapse:collapse;background:var(--panel);width:100%;margin-bottom:6px}}td,th{{text-align:left;padding:5px 8px;border:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;color:var(--ink3)}}td{{font-variant-numeric:tabular-nums}}.mono{{font-family:var(--mono);font-size:12px}}
</style></head><body><main>
<h1>TMS admin</h1><p><a href="/">Home</a> · <a href="/dashboard">Dashboard</a> · <a href="/docs">Docs</a></p>
<h2>Embedding spend (DeepInfra)</h2>
{_table(["Today (UTC)", "7 days", "30 days", "All time", "Tokens", "Calls"],
        [[_usd(s["today"]), _usd(s["last_7_days"]), _usd(s["last_30_days"]), _usd(s["all_time"]), f"{s['tokens']:,}", s["calls"]]])}
<p class="mono">At ${L.EMBED_PRICE_PER_MTOK} per million tokens (EMBED_PRICE_PER_MTOK); local endpoints cost $0.</p>
<h2>Spend by pubkey</h2>
{_table(["Who", "Calls", "Tokens", "Cost"], [[_who(x["pubkey"], x["name"]), x["calls"], f"{x['tokens']:,}", _usd(x["cost"])] for x in r["by_pubkey"]])}
<h2>Spend by collection</h2>
{_table(["Collection", "Calls", "Tokens", "Cost"], [[escape(x["collection"] or "—"), x["calls"], f"{x['tokens']:,}", _usd(x["cost"])] for x in r["by_collection"]])}
<h2>Users ({r["pubkeys"]})</h2>
{_table(["npub", "Name", "About", "Collections", "Owns", "Events", "Last activity"],
        [[f'<span class="mono">{escape(E.bech32_encode("npub", u["pubkey"]))}</span>', escape(u["name"] or "—"), escape(u["about"] or ""),
          u["collections"], u["owned"], u["events"], when(u["last_activity"])] for u in r["users"]])}
<h2>Context</h2>
{_table(["Database size", "Pubkeys", "Collections"], [[f"{r['db_bytes'] / 1e6:,.1f} MB", r["pubkeys"], r["collections"]]])}
<h2>Events per day (last 14 days)</h2>
{_table(["Day", "Events"], [[d["day"].isoformat(), d["events"]] for d in r["per_day"]])}
</main></body></html>"""


def admin(request: Request):
    pubkey = cookie_pubkey(request)
    if pubkey is None or pubkey not in L.ADMINS:
        return PlainTextResponse("Not Found", status_code=404)
    with L.connect() as conn:
        return HTMLResponse(render(report(conn)))


routes = [Route("/admin", admin)]  # sync handler: Starlette runs it in its threadpool
