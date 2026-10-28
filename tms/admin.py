"""Operator page at /admin: free accounts and lifting their limits, admins, DeepInfra spend (embeddings and chat), users, and a few context numbers.

Site admins are the pubkeys in TMS_ADMINS; they can add and remove admins here (the admins table),
who can do everything else. Both log in with the same cookie as the other pages.
Everyone else gets a 404, so the page's existence isn't advertised. Plain tables, server-rendered.
"""
from __future__ import annotations

from html import escape

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from . import chat
from . import events as E
from . import ledger as L
from . import site
from .web import cookie_pubkey

SPEND_SQL = """SELECT
    coalesce(sum(cost_usd) FILTER (WHERE at >= date_trunc('day', now())), 0) AS today,
    coalesce(sum(cost_usd) FILTER (WHERE at > now() - interval '7 days'), 0) AS last_7_days,
    coalesce(sum(cost_usd) FILTER (WHERE at > now() - interval '30 days'), 0) AS last_30_days,
    coalesce(sum(cost_usd), 0) AS all_time,
    coalesce(sum(tokens), 0) AS tokens, count(*) AS calls
  FROM embed_calls"""

USERS_SQL = """WITH keys AS (
    SELECT unnest(%s::text[]) AS pubkey UNION SELECT pubkey FROM approvals UNION SELECT pubkey FROM admins
    UNION SELECT pubkey FROM members UNION SELECT pubkey FROM events)
  SELECT k.pubkey, p.name, p.about,
         (SELECT count(*) FROM members m WHERE m.pubkey = k.pubkey) AS collections,
         (SELECT count(*) FROM collections c WHERE c.owner = k.pubkey) AS owned,
         (SELECT count(*) FROM events e WHERE e.pubkey = k.pubkey) AS events,
         greatest((SELECT max(received_at) FROM events e WHERE e.pubkey = k.pubkey),
                  (SELECT max(at) FROM mcp_calls c WHERE c.pubkey = k.pubkey)) AS last_activity
  FROM keys k LEFT JOIN profiles p ON p.pubkey = k.pubkey
  ORDER BY last_activity DESC NULLS LAST, k.pubkey"""


def report(conn, viewer: str) -> dict:
    r = _report(conn, viewer)
    r["records"] = {q["pubkey"]: L._records(conn, q["pubkey"]) for q in r["free"]}  # ponytail: one count per account
    return r


def _report(conn, viewer: str) -> dict:
    # Site admins see spend for every collection; added admins only for the collections they're in.
    cols = None if viewer in L.ADMINS else L.my_collections(conn, viewer)
    users = conn.execute(USERS_SQL, (sorted(L.APPROVED | L.ADMINS),)).fetchall()
    return {
        "free": conn.execute("""SELECT k.pubkey, min(k.at) AS at, p.name, (SELECT email FROM email_accounts a WHERE a.pubkey = k.pubkey) AS email,
              (SELECT count(*) FROM collections c WHERE c.owner = k.pubkey) AS owned,
              (SELECT cardinality(a.agents) FROM accounts a WHERE a.human = k.pubkey) AS agents
            FROM (SELECT pubkey, at FROM signups UNION ALL SELECT pubkey, created_at FROM email_accounts) k
            LEFT JOIN profiles p ON p.pubkey = k.pubkey
            WHERE k.pubkey NOT IN (SELECT pubkey FROM approvals) AND k.pubkey NOT IN (SELECT pubkey FROM admins)
              AND k.pubkey <> ALL(%s) GROUP BY k.pubkey, p.name ORDER BY min(k.at) DESC""", (sorted(L.APPROVED | L.ADMINS),)).fetchall(),
        "approvals": conn.execute("""SELECT a.pubkey, a.at, p.name, (SELECT name FROM profiles q WHERE q.pubkey = a.approved_by) AS by_name,
              a.approved_by FROM approvals a LEFT JOIN profiles p ON p.pubkey = a.pubkey ORDER BY a.at DESC""").fetchall(),
        "admins": conn.execute("""SELECT a.pubkey, a.at, p.name, (SELECT name FROM profiles q WHERE q.pubkey = a.added_by) AS by_name,
              a.added_by FROM admins a LEFT JOIN profiles p ON p.pubkey = a.pubkey ORDER BY a.at""").fetchall(),
        "site_admins": [{"pubkey": k, "name": (conn.execute("SELECT name FROM profiles WHERE pubkey = %s", (k,)).fetchone() or {}).get("name")}
                        for k in sorted(L.ADMINS)],
        "spend": conn.execute(SPEND_SQL).fetchone(),
        "by_pubkey": conn.execute("""SELECT e.pubkey, p.name, count(*) AS calls, sum(e.tokens) AS tokens, sum(e.cost_usd) AS cost
            FROM embed_calls e LEFT JOIN profiles p ON p.pubkey = e.pubkey GROUP BY 1, 2 ORDER BY cost DESC, calls DESC""").fetchall(),
        "by_model": conn.execute("""SELECT model, count(*) AS calls, sum(tokens) AS tokens, sum(cost_usd) AS cost
            FROM embed_calls GROUP BY 1 ORDER BY cost DESC, calls DESC""").fetchall(),
        "by_collection": conn.execute("""SELECT collection, count(*) AS calls, sum(tokens) AS tokens, sum(cost_usd) AS cost
            FROM embed_calls WHERE %(cols)s::text[] IS NULL OR collection = ANY(%(cols)s)
            GROUP BY 1 ORDER BY cost DESC, calls DESC""", {"cols": cols}).fetchall(),
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
    if not E.HEX64.match(pubkey):  # not a key (a test or script wrote something else): show it as text
        return escape(pubkey)
    label = escape(name) if name else escape(E.bech32_encode("npub", pubkey)[:16] + "…")
    return f'<span title="{escape(E.bech32_encode("npub", pubkey))}">{label}</span>'


def render(r: dict, viewer: str) -> str:
    s = r["spend"]
    when = lambda v: v.strftime("%Y-%m-%d %H:%M") if v else "—"  # noqa: E731
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paranoy · Admin</title><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/site.css?v={site.VERSION}"><style>
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif}}main{{max-width:1100px;margin:0 auto;padding:16px}}
a{{color:var(--accent)}}h1{{font-size:18px}}h2{{font-size:13px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink3);margin:22px 0 6px}}
table{{border-collapse:collapse;background:var(--panel);width:100%;margin-bottom:6px}}td,th{{text-align:left;padding:5px 8px;border:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;color:var(--ink3)}}td{{font-variant-numeric:tabular-nums}}.mono{{font-family:var(--mono);font-size:12px}}
form{{display:inline}}main button{{font:inherit;padding:3px 10px;border-radius:5px;border:1px solid var(--brand);background:var(--brand);color:var(--brand-ink);cursor:pointer}}
main button.ghost{{background:none;color:var(--ink);border-color:var(--line)}}form.add{{display:block;margin:6px 0}}form.add input{{font:13px var(--mono);padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--panel);color:var(--ink);max-width:100%}}td.note{{white-space:pre-wrap;max-width:420px}}
</style></head><body>{site.header(True, "/admin")}<main id="main">
<h1>Admin</h1>
<h2>Free accounts ({len(r["free"])})</h2>
<p class="mono">Anyone can sign up. A free account owns {L.FREE_COLLECTIONS} collection, has {L.FREE_AGENTS} agents, and writes {L.FREE_RECORDS:,} evidence, claims, links and contradictions (its human, Ledger and agents together).</p>
{_table(["Who", "npub or email", "Signed up", "Owns", "Agents", "Records", ""],
        [[escape(q["name"] or "—"), '<br>'.join(f'<span class="mono">{escape(x)}</span>' for x in (E.bech32_encode("npub", q["pubkey"]), q["email"]) if x),
          when(q["at"]), q["owned"], q["agents"] or 0, f'{r["records"][q["pubkey"]]:,}',
          f'<form method="post" action="/admin/lift/{q["pubkey"]}"><button>Lift limits</button></form>']
         for q in r["free"]])}
<form method="post" action="/admin/lift" class="add"><input name="npub" placeholder="npub1… to lift its limits" required size="66"> <button>Lift limits</button></form>
<h2>Limits lifted here ({len(r["approvals"])})</h2>
{_table(["Who", "npub", "Lifted by", "When"],
        [[escape(a["name"] or "—"), f'<span class="mono">{escape(E.bech32_encode("npub", a["pubkey"]))}</span>',
          _who(a["approved_by"], a["by_name"]), when(a["at"])] for a in r["approvals"]])}
<p class="mono">No limits = TMS_ADMINS + TMS_APPROVED ({len(L.APPROVED | L.ADMINS)} from the environment) + the keys lifted here.</p>
<h2>Admins</h2>
{_table(["Who", "npub", "Role", "Added by", "When", ""],
        [[escape(a["name"] or "—"), f'<span class="mono">{escape(E.bech32_encode("npub", a["pubkey"]))}</span>', "site admin (TMS_ADMINS)", "—", "—", ""]
         for a in r["site_admins"]] +
        [[escape(a["name"] or "—"), f'<span class="mono">{escape(E.bech32_encode("npub", a["pubkey"]))}</span>', "admin",
          _who(a["added_by"], a["by_name"]), when(a["at"]),
          f'<form method="post" action="/admin/admins/{a["pubkey"]}/remove"><button class="ghost">Remove</button></form>' if viewer in L.ADMINS else ""]
         for a in r["admins"]])}
{'<form method="post" action="/admin/admins" class="add"><input name="npub" placeholder="npub1… to make an admin" required size="66"> <button>Add admin</button></form>'
 if viewer in L.ADMINS else '<p class="mono">Only site admins (TMS_ADMINS) can add or remove admins.</p>'}
<h2>DeepInfra spend (embeddings and chat)</h2>
{_table(["Today (UTC)", "7 days", "30 days", "All time", "Tokens", "Calls"],
        [[_usd(s["today"]), _usd(s["last_7_days"]), _usd(s["last_30_days"]), _usd(s["all_time"]), f"{s['tokens']:,}", s["calls"]]])}
<p class="mono">Embeddings at ${L.EMBED_PRICE_PER_MTOK} per million tokens (EMBED_PRICE_PER_MTOK), local endpoints $0; chat at ${chat.PRICE_IN} in / ${chat.PRICE_OUT} out (CHAT_PRICE_IN_PER_MTOK, CHAT_PRICE_OUT_PER_MTOK).</p>
<h2>Spend by model</h2>
{_table(["Model", "Calls", "Tokens", "Cost"], [[escape(x["model"] or "—"), x["calls"], f"{x['tokens']:,}", _usd(x["cost"])] for x in r["by_model"]])}
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
    with L.connect() as conn:
        if not L.is_admin(conn, pubkey):
            return PlainTextResponse("Not Found", status_code=404)
        return HTMLResponse(render(report(conn, pubkey), pubkey))


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    return not origin or origin == str(request.base_url).rstrip("/")  # the cookie is SameSite=Lax too


async def admins(request: Request):
    """Site admins only: add an admin (POST /admin/admins, form field npub) or remove one."""
    pubkey = cookie_pubkey(request)
    if pubkey is None or pubkey not in L.ADMINS:
        return PlainTextResponse("Not Found", status_code=404)
    if not _same_origin(request):
        return PlainTextResponse("cross-site request refused", status_code=403)
    target = request.path_params.get("pubkey")
    if target is None:
        try:
            target = E.pubkey_hex(str((await request.form()).get("npub", "")).strip())
        except ValueError as err:
            return PlainTextResponse(f"not a valid npub or hex key: {err}", status_code=400)

    def write():
        with L.connect() as conn:
            if request.path_params.get("pubkey"):
                conn.execute("DELETE FROM admins WHERE pubkey = %s", (target,))
            else:
                conn.execute("INSERT INTO admins (pubkey, added_by) VALUES (%s, %s) ON CONFLICT DO NOTHING", (target, pubkey))
    await run_in_threadpool(write)
    return RedirectResponse("/admin", status_code=303)


async def lift(request: Request):
    """Admins: lift a key's free-account limits (POST /admin/lift, form field npub, or /admin/lift/<hex>).
    Writes the approvals table, so it takes effect on the key's next write, with no redeploy."""
    pubkey = cookie_pubkey(request)
    if not await run_in_threadpool(lambda: _is_admin(pubkey)):
        return PlainTextResponse("Not Found", status_code=404)
    if not _same_origin(request):
        return PlainTextResponse("cross-site request refused", status_code=403)
    try:
        target = E.pubkey_hex(request.path_params.get("pubkey") or str((await request.form()).get("npub", "")))
    except ValueError as err:
        return PlainTextResponse(f"not a valid npub or hex key: {err}", status_code=400)

    def write():
        with L.connect() as conn:
            conn.execute("INSERT INTO approvals (pubkey, approved_by) VALUES (%s, %s) ON CONFLICT DO NOTHING", (target, pubkey))
    await run_in_threadpool(write)
    return RedirectResponse("/admin", status_code=303)


def _is_admin(pubkey) -> bool:
    with L.connect() as conn:
        return L.is_admin(conn, pubkey)


routes = [  # sync handlers: Starlette runs them in its threadpool
    Route("/admin", admin),
    Route("/admin/lift", lift, methods=["POST"]),
    Route("/admin/lift/{pubkey:str}", lift, methods=["POST"]),
    Route("/admin/admins", admins, methods=["POST"]),
    Route("/admin/admins/{pubkey:str}/remove", admins, methods=["POST"]),
]
