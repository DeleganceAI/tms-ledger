"""Browser side (EVENTS.md section 6): NIP-07 login cookie, the pages, and their JSON.

    /                       connect, profile, terms, your collections
    /submit                 sign and publish evidence, claims and links
    /office                 ambient animation; no ledger data
    /c/<slug>/members       owner only: sign a new members list
    /c/<slug>/export.jsonl  members: every event in the collection, one signed event per line

Pages are one static file (web.html); everything they show comes from the JSON routes, which
read the login cookie. Writes are signed in the browser and go to /api/publish.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from . import events as E
from . import ledger as L

COOKIE = "tms"
COOKIE_TTL = 12 * 3600
PAGE_FILE = Path(__file__).with_name("web.html")
OFFICE_FILE = Path(__file__).with_name("office.html")
DOCS_FILE = Path(__file__).resolve().parent.parent / "DOCS.md"
DOCS_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>TMS docs</title><style>
:root{{--bg:#f4f4f2;--panel:#fff;--line:#e2e2de;--ink:#171716;--ink3:#8c8c86;--accent:#2f6fde;--code:#ecece8}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121211;--panel:#1a1a19;--line:#2b2b29;--ink:#ececea;--ink3:#74746d;--accent:#7aa6f5;--code:#232321}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,sans-serif}}
header{{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:14px}}header a{{color:var(--ink3);text-decoration:none}}
main{{max-width:860px;margin:0 auto;padding:8px 16px 40px}}a{{color:var(--accent)}}
pre,code{{font:13px/1.5 ui-monospace,Menlo,monospace;background:var(--code);border-radius:4px}}code{{padding:1px 4px}}
pre{{padding:10px 12px;overflow-x:auto;white-space:pre}}pre code{{padding:0;background:none}}#md{{white-space:pre-wrap}}
table{{border-collapse:collapse;display:block;overflow-x:auto}}td,th{{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
blockquote{{margin:0;padding:2px 14px;border-left:3px solid var(--line);color:var(--ink3)}}
</style></head><body><header><b>TMS ledger</b><a href="/">Home</a><a href="/submit">Submit</a><a href="/dashboard">Dashboard</a>
<a href="/office">Office</a><a href="/docs.md">Markdown</a></header><main><pre id="md">{md}</pre></main>
<script src="https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js"></script>
<script>const el = document.getElementById('md'); if (window.marked) el.outerHTML = marked.parse(el.textContent)</script>
</body></html>"""


def _mac(payload: str) -> str:
    return hmac.new(os.environ["TMS_SECRET"].encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_cookie(pubkey: str, now: float | None = None) -> str:
    payload = f"{pubkey}.{int(now or time.time()) + COOKIE_TTL}"
    return f"{payload}.{_mac(payload)}"


def cookie_pubkey(request: Request) -> str | None:
    """The logged-in pubkey, if the cookie is ours and unexpired."""
    pubkey, _, rest = request.cookies.get(COOKIE, "").partition(".")
    exp, _, mac = rest.partition(".")
    if not (E.HEX64.match(pubkey) and exp.isdigit() and int(exp) > time.time()):
        return None
    return pubkey if hmac.compare_digest(mac, _mac(f"{pubkey}.{exp}")) else None


def _error(err: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(err)}, status_code=403 if isinstance(err, L.Denied) else status)


def _account(conn, pubkey: str) -> dict:
    return {**L.account(conn, pubkey), "terms_text": L.TERMS_TEXT.decode()}


async def login(request: Request) -> JSONResponse:
    """POST a request event signed with tool "login"; get a 12-hour HttpOnly cookie."""
    from .server import authenticate
    try:
        ev = await request.json()
        with L.connect() as conn:
            pubkey, _ = authenticate(conn, ev, "login")
            acct = _account(conn, pubkey)
    except ValueError as err:
        return _error(err)
    resp = JSONResponse(acct)
    resp.set_cookie(COOKIE, make_cookie(pubkey), max_age=COOKIE_TTL, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


async def logout(request: Request) -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


async def page(request: Request):
    return HTMLResponse(PAGE_FILE.read_text(encoding="utf-8"))  # re-read so edits show on refresh


async def office(request: Request) -> HTMLResponse:
    """Ambient picture of the work. Papers are squiggles; nothing here is ledger data."""
    return HTMLResponse(OFFICE_FILE.read_text(encoding="utf-8"))


def _docs_text(request: Request) -> str:
    base = str(request.base_url).rstrip("/")  # behind DO's proxy, uvicorn's proxy_headers make this https
    return (DOCS_FILE.read_text(encoding="utf-8").replace("{{BASE}}", base)
            .replace("{{TERMS_VERSION}}", L.TERMS["version"]).replace("{{TERMS_SHA256}}", L.TERMS["sha256"]))


async def docs(request: Request) -> HTMLResponse:
    """DOCS.md, rendered in the browser by a pinned marked; readable as plain text without JS."""
    from html import escape
    return HTMLResponse(DOCS_PAGE.format(md=escape(_docs_text(request))))


async def docs_md(request: Request) -> PlainTextResponse:
    return PlainTextResponse(_docs_text(request), media_type="text/markdown; charset=utf-8")


async def members_page(request: Request):
    pubkey, slug = cookie_pubkey(request), request.path_params["slug"]
    if pubkey is None:
        return HTMLResponse('<meta http-equiv="refresh" content="0;url=/">', status_code=401)
    with L.connect() as conn:
        row = conn.execute("SELECT owner FROM collections WHERE slug = %s", (slug,)).fetchone()
    if row is None or row["owner"] != pubkey:
        return PlainTextResponse(f"Only the owner of '{slug}' manages its members.", status_code=403)
    return await page(request)


async def me(request: Request) -> JSONResponse:
    pubkey = cookie_pubkey(request)
    if pubkey is None:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    with L.connect() as conn:
        return JSONResponse(_account(conn, pubkey))


async def collection(request: Request) -> JSONResponse:
    """Members of one collection with their profile names, for the members page."""
    pubkey, slug = cookie_pubkey(request), request.path_params["slug"]
    if pubkey is None:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    try:
        with L.connect() as conn:
            L.require_member(conn, pubkey, slug)
            owner = conn.execute("SELECT owner FROM collections WHERE slug = %s", (slug,)).fetchone()["owner"]
            members = [L._clean(r) for r in conn.execute(
                """SELECT m.pubkey, p.name, p.about FROM members m LEFT JOIN profiles p ON p.pubkey = m.pubkey
                   WHERE m.collection = %s ORDER BY m.pubkey = %s DESC, p.name NULLS LAST, m.pubkey""", (slug, owner))]
    except ValueError as err:
        return _error(err)
    for m in members:
        m["npub"] = E.bech32_encode("npub", m["pubkey"])
    return JSONResponse({"slug": slug, "owner": owner, "members": members})


async def publish(request: Request) -> JSONResponse:
    """Signed events need no cookie: each one is its own proof."""
    def run(body):
        with L.connect() as conn:
            return L.publish(conn, body.get("events") if isinstance(body, dict) else body)
    try:
        return JSONResponse(await run_in_threadpool(run, await request.json()))
    except (ValueError, TypeError) as err:
        return _error(err)
    except Exception as err:  # psycopg errors carry the acceptance rule that failed
        msg = getattr(getattr(err, "diag", None), "message_primary", None)
        if msg:
            return _error(ValueError(msg))
        raise


async def fetch(request: Request) -> JSONResponse:
    """Fetch a URL's text for the submit form (logged-in users only; http(s), no internal hosts)."""
    pubkey = cookie_pubkey(request)
    if pubkey is None:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    url = request.query_params.get("url", "")
    try:
        with L.connect() as conn:
            L.require_allowed(conn, pubkey)
        text, title = await run_in_threadpool(L.fetch_text, url)  # over HTTP, ALLOW_LOCAL is off: http(s) only
    except Exception as err:
        return _error(err)
    return JSONResponse({"url": url, "title": title, "text": text})


async def export(request: Request):
    pubkey, slug = cookie_pubkey(request), request.path_params["slug"]
    if pubkey is None:
        return PlainTextResponse("log in first", status_code=401)
    with L.connect() as conn:
        try:
            L.require_member(conn, pubkey, slug)
        except ValueError as err:
            return PlainTextResponse(str(err), status_code=403)

    def lines():
        with L.connect() as conn:
            for ev in L.export(conn, pubkey, slug):
                yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={
        "Content-Disposition": f'attachment; filename="{slug}-{time.strftime("%Y%m%d")}.jsonl"'})


async def healthz(request: Request) -> PlainTextResponse:
    def ping():
        with L.connect() as conn:
            conn.execute("SELECT 1")
    await run_in_threadpool(ping)
    return PlainTextResponse("ok")


routes = [
    Route("/healthz", healthz),
    Route("/docs", docs),
    Route("/docs.md", docs_md),
    Route("/", page),
    Route("/submit", page),
    Route("/office", office),
    Route("/c/{slug}/members", members_page),
    Route("/c/{slug}/export.jsonl", export),
    Route("/login", login, methods=["POST"]),
    Route("/logout", logout, methods=["POST"]),
    Route("/api/me", me),
    Route("/api/c/{slug}", collection),
    Route("/api/publish", publish, methods=["POST"]),
    Route("/api/fetch", fetch),
]
