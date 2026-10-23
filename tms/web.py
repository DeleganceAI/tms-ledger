"""Browser side (EVENTS.md section 6): NIP-07 login cookie, the pages, and their JSON.

    /                       logged out: the office, totals and Request access; logged in: as /connect
    /connect                connect, profile, terms, your collections
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
import threading
import time
from collections import deque
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
# Extra docs pages, served at /docs/<name> with the same template.
DOCS_PAGES = {"bitter-lesson": Path(__file__).resolve().parent.parent / "BITTER_LESSON.md",
              "why-nostr": Path(__file__).resolve().parent.parent / "WHY_NOSTR.md"}
CONTACT_EMAIL = os.environ.get("TMS_CONTACT_EMAIL", "dustin@delegance.ai")
DOCS_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>TMS docs</title><style>
:root{{color-scheme:dark;--bg:#2b2433;--panel:#342b3e;--line:#4a3f57;--ink:#f4efe6;--ink3:#9d91a8;--accent:#8ab6f9;--code:#241e2c}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,sans-serif}}
header{{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:4px 14px}}header a{{color:var(--ink3);text-decoration:none}}
main{{max-width:860px;margin:0 auto;padding:8px 16px 40px;min-width:0}}a{{color:var(--accent)}}
.wrap{{display:flex;justify-content:center;gap:28px}}
#toc{{font-size:13px;line-height:1.4;padding:14px 0 0 16px}}#toc summary{{cursor:pointer;color:var(--ink3);font-weight:600}}
#toc ol{{list-style:none;margin:6px 0 0;padding:0}}#toc li{{margin:3px 0}}#toc li.h3{{padding-left:12px}}#toc li.h4{{padding-left:24px;font-size:12px}}#toc li.h2{{margin-top:10px}}#toc li.h2:first-child{{margin-top:0}}#toc li.h2>a{{color:var(--ink);font-weight:600}}#toc a{{color:var(--ink3);text-decoration:none}}
#toc a:hover,#toc a.on{{color:var(--ink)}}#toc a.on{{font-weight:600}}#toc li.pages{{margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--line)}}#toc li.pages b{{color:var(--ink3);font-size:11px;letter-spacing:.06em;text-transform:uppercase}}#toc li.pages ol{{margin-top:4px}}#toc a.here{{color:var(--ink);font-weight:600}}
@media(min-width:1100px){{#toc{{position:sticky;top:0;align-self:flex-start;width:230px;max-height:100vh;overflow:auto;flex:none}}#toc summary{{display:none}}}}
@media(max-width:1099px){{.wrap{{display:block}}#toc{{display:block;padding:10px 16px 0;max-width:860px;margin:0 auto;box-sizing:border-box}}}}
h2,h3{{scroll-margin-top:12px}}
pre,code{{font:13px/1.5 ui-monospace,Menlo,monospace;background:var(--code);border-radius:4px}}code{{padding:1px 4px}}:not(pre)>code{{overflow-wrap:anywhere}}td>code:only-child{{white-space:nowrap;overflow-wrap:normal}}
pre{{padding:10px 12px;overflow-x:auto;white-space:pre}}pre code{{padding:0;background:none}}#md{{white-space:pre-wrap}}
table{{border-collapse:collapse;display:block;overflow-x:auto}}td,th{{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
blockquote{{margin:0;padding:2px 14px;border-left:3px solid var(--line);color:var(--ink3)}}
</style></head><body><header><b>TMS ledger</b><a href="/">Home</a><a href="/submit">Submit</a><a href="/dashboard">Dashboard</a>
<a href="/office">Office</a><a href="/docs">Docs</a><a href="/docs/bitter-lesson">Bitter lesson</a><a href="/docs.md">Markdown</a><a href="https://github.com/DeleganceAI/tms-ledger" target="_blank" rel="noopener" title="Source on GitHub"><svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true" style="vertical-align:-2px;margin-right:4px"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"/></svg>GitHub</a></header>
<div class="wrap"><details id="toc" hidden><summary>Contents</summary><ol></ol></details><main><pre id="md">{md}</pre></main></div>
<script src="https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js"></script>
<script>const el = document.getElementById('md'); if (window.marked) el.outerHTML = marked.parse(el.textContent)</script>
<script>{toc_js}</script>
<script src="/chat.js" defer></script></body></html>"""


# The docs sidebar: a contents list from the rendered h2/h3, with the section in view highlighted.
TOC_JS = r"""(() => {
  const heads = [...document.querySelectorAll('main h2, main h3, main h4')];
  if (!heads.length) return;
  const slug = t => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const toc = document.getElementById('toc'), list = toc.querySelector('ol'), links = new Map();
  for (const h of heads) {
    h.id ||= slug(h.textContent);
    const li = document.createElement('li'), a = document.createElement('a');
    li.className = h.tagName.toLowerCase(); a.href = '#' + h.id; a.textContent = h.textContent;
    li.append(a); list.append(li); links.set(h, a);
  }
  // the docs pages themselves, above this page's sections
  const pages = [['/docs', 'Using the TMS ledger'], ['/docs/bitter-lesson', 'The Bitter Lesson Applied to Knowledge Graphs'], ['/docs/why-nostr', 'Why Nostr Keys for Login']];
  const group = document.createElement('li'); group.className = 'pages';
  group.innerHTML = '<b>Pages</b><ol>' + pages.map(([href, title]) =>
    `<li><a href="${href}"${location.pathname === href ? ' class="here"' : ''}>${title}</a></li>`).join('') + '</ol>';
  list.prepend(group);
  toc.hidden = false; toc.open = matchMedia('(min-width: 1100px)').matches;
  toc.addEventListener('click', e => { if (e.target.closest('a') && !matchMedia('(min-width: 1100px)').matches) toc.open = false; });
  const seen = new Set();
  const obs = new IntersectionObserver(es => {
    for (const e of es) e.isIntersecting ? seen.add(e.target) : seen.delete(e.target);
    const top = heads.find(h => seen.has(h));
    if (top) links.forEach((a, h) => a.classList.toggle('on', h === top));
  }, {rootMargin: '0px 0px -70% 0px'});
  heads.forEach(h => obs.observe(h));
})();"""


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


async def home(request: Request):
    """Logged out, the landing page is the office; logged in, the connect and collections page."""
    resp = await page(request) if cookie_pubkey(request) else await office(request)
    resp.headers["Cache-Control"] = "private, no-store"  # the page depends on the cookie
    return resp


REQUEST_LIMIT, REQUEST_WINDOW = 5, 3600  # access requests per IP per hour
MAX_PENDING = 200                        # all pending requests together, whatever the addresses
_recent: dict[str, deque] = {}
_recent_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """The address our proxy saw: the rightmost X-Forwarded-For entry, which DigitalOcean's proxy
    appends. Not request.client.host: uvicorn trusts every proxy here, so that is the leftmost
    entry, which the client can set to anything."""
    xff = request.headers.get("x-forwarded-for", "")
    return xff.rsplit(",", 1)[-1].strip() or (request.client.host if request.client else "?")


def _rate_limited(ip: str) -> bool:
    """ponytail: in-process, per instance; a table if the app ever runs more than one instance."""
    now = time.monotonic()
    with _recent_lock:
        for key in [k for k, q in _recent.items() if not q or now - q[-1] > REQUEST_WINDOW]:
            del _recent[key]  # forget quiet addresses, so the map can't grow without bound
        q = _recent.setdefault(ip, deque())
        while q and now - q[0] > REQUEST_WINDOW:
            q.popleft()
        if len(q) >= REQUEST_LIMIT:
            return True
        q.append(now)
        return False


async def access_request(request: Request) -> JSONResponse:
    """Unsigned on purpose: the visitor may not have a Nostr extension yet. An admin decides in /admin."""
    if _rate_limited(_client_ip(request)):
        return JSONResponse({"error": "too many requests from this address; try again later"}, status_code=429)
    try:
        body = await request.json()
        npub = E.bech32_encode("npub", E.pubkey_hex(str(body.get("npub", ""))))
        note = str(body.get("note") or "").strip()
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"error": "enter an npub (npub1...) or a 64-character hex pubkey"}, status_code=400)
    if len(note) > 500:
        return JSONResponse({"error": "the note is limited to 500 characters"}, status_code=400)

    def store() -> bool:
        with L.connect() as conn:
            if conn.execute("SELECT count(*) AS n FROM access_requests WHERE status = 'pending'").fetchone()["n"] >= MAX_PENDING:
                return False
            conn.execute("""INSERT INTO access_requests (npub, note) VALUES (%s, %s)
                            ON CONFLICT (npub) WHERE status = 'pending' DO NOTHING""", (npub, note or None))
            return True
    if not await run_in_threadpool(store):
        return JSONResponse({"error": "too many requests are waiting; try again later"}, status_code=429)
    # The same answer whether or not this key already had a request waiting: the reply says nothing about anyone.
    return JSONResponse({"status": "pending", "npub": npub}, status_code=201)


async def office(request: Request) -> HTMLResponse:
    """Ambient picture of the work. Papers are squiggles; nothing here is ledger data."""
    return HTMLResponse(OFFICE_FILE.read_text(encoding="utf-8"))


def _docs_text(request: Request, path: Path = DOCS_FILE) -> str:
    base = str(request.base_url).rstrip("/")  # behind DO's proxy, uvicorn's proxy_headers make this https
    return (path.read_text(encoding="utf-8").replace("{{BASE}}", base).replace("{{CONTACT_EMAIL}}", CONTACT_EMAIL)
            .replace("{{TERMS_VERSION}}", L.TERMS["version"]).replace("{{TERMS_SHA256}}", L.TERMS["sha256"]))


async def docs(request: Request) -> HTMLResponse:
    """DOCS.md, rendered in the browser by a pinned marked; readable as plain text without JS."""
    from html import escape
    return HTMLResponse(DOCS_PAGE.format(md=escape(_docs_text(request)), toc_js=TOC_JS))


async def docs_page(request: Request) -> HTMLResponse:
    """An extra docs page from DOCS_PAGES, same template as /docs."""
    from html import escape
    path = DOCS_PAGES.get(request.path_params["name"])
    if path is None:
        return HTMLResponse("not found", status_code=404)
    return HTMLResponse(DOCS_PAGE.format(md=escape(_docs_text(request, path)), toc_js=TOC_JS))


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
    Route("/docs/{name}", docs_page),
    Route("/", home),
    Route("/connect", page),
    Route("/api/access-request", access_request, methods=["POST"]),
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
