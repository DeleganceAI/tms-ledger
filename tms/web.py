"""Browser side (EVENTS.md section 6): NIP-07 login cookie, the pages, and their JSON.

    /                       logged out: the office, totals and Sign up; logged in: your collections as pin boards
    /connect                log in or sign up; then your account: profile, terms, collection settings, agents
    /submit                 sign and publish evidence, claims and links
    /office                 ambient animation; no ledger data
    /favicon.*              the Paranoy icons in tms/brand
    /c/<slug>/members       owner or admin: sign a new members list; the owner also signs admins
    /c/<slug>/export.jsonl  members: every event in the collection, one signed event per line

Pages are one static file (web.html); everything they show comes from the JSON routes, which
read the login cookie. Writes are signed in the browser and go to /api/publish.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
from collections import deque
from html import escape
from pathlib import Path

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route

from . import events as E
from . import ledger as L
from . import site

COOKIE = "tms"
COOKIE_TTL = 12 * 3600
PAGE_FILE = Path(__file__).with_name("web.html")
COLLECTIONS_FILE = Path(__file__).with_name("collections.html")
OFFICE_FILE = Path(__file__).with_name("office.html")
PRICING_FILE = Path(__file__).with_name("pricing.html")
DOCS_FILE = Path(__file__).resolve().parent.parent / "DOCS.md"
# Extra docs pages, served at /docs/<name> with the same template.
DOCS_PAGES = {"bitter-lesson": Path(__file__).resolve().parent.parent / "BITTER_LESSON.md",
              "why-nostr": Path(__file__).resolve().parent.parent / "WHY_NOSTR.md"}
CONTACT_EMAIL = L.CONTACT
# Cloudflare Turnstile on sign-up only. Unset, sign-up goes unchecked (local dev and tests).
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "")
# Hostnames a token may come from; unset, the host the request came to (behind the proxy, the public one)
TURNSTILE_HOSTNAMES = {h for h in os.environ.get("TURNSTILE_HOSTNAMES", "").replace(",", " ").split() if h}
if not TURNSTILE_SECRET:
    print("TURNSTILE_SECRET is not set: sign-up is not checked for bots", file=sys.stderr)
DOCS_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/site.css?v=SITE_V"><style>
:root{{--code:#241e2c}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,sans-serif}}
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
</style></head><body>{header}
<div class="wrap"><details id="toc" hidden><summary>Contents</summary><ol></ol></details><main id="main"><pre id="md">{md}</pre></main></div>
<script src="https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js"></script>
<script>const el = document.getElementById('md'); if (window.marked) el.outerHTML = marked.parse(el.textContent)</script>
<script>{toc_js}</script></body></html>"""


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
  const pages = [['/docs', 'Using Paranoy'], ['/docs/bitter-lesson', 'The Bitter Lesson Applied to Knowledge Graphs'], ['/docs/why-nostr', 'Why Nostr Keys for Login']];
  const group = document.createElement('li'); group.className = 'pages';
  group.innerHTML = '<b>Pages</b><ol>' + pages.map(([href, title]) =>
    `<li><a href="${href}"${location.pathname === href ? ' class="here"' : ''}>${title}</a></li>`).join('') + '<li><a href="/docs.md">This guide as Markdown</a></li></ol>';
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


def invite_token(slug: str) -> str:
    """The token in a collection's invite link. It lets its holder ask to join, even when the collection
    is private; the owner or an admin still accepts. ponytail: one fixed link per collection, so it can't
    be revoked; rotating TMS_SECRET resets them all (and logs everyone out). A table of links if that bites."""
    return _mac(f"invite:{slug}")[:32]


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


async def db(fn, *args):
    """fn(conn, *args) on a pooled connection, in a worker thread. Async handlers use this for every
    query: waiting on a busy pool from the event loop would stall every request, MCP included."""
    def run():
        with L.connect() as conn:
            return fn(conn, *args)
    return await run_in_threadpool(run)


# Join requests waiting on an owner or admin: not dismissed, and the key is not a member yet.
PENDING = """SELECT j.collection, j.pubkey, j.note, j.at, p.name FROM join_requests j LEFT JOIN profiles p ON p.pubkey = j.pubkey
    WHERE j.dismissed_at IS NULL AND NOT EXISTS (SELECT 1 FROM members m WHERE m.collection = j.collection AND m.pubkey = j.pubkey)"""


def _account(conn, pubkey: str) -> dict:
    """What the pages need about the logged-in key. custodial: the server holds its key (email sign-in).
    requested: collections it asked to join; requests on each collection it runs: how many are waiting."""
    email = conn.execute("SELECT email, nsec_enc IS NOT NULL AS held FROM email_accounts WHERE pubkey = %s", (pubkey,)).fetchone()
    acct = L.account(conn, pubkey)
    runs = [c["slug"] for c in acct["collections"] if c["role"] in ("owner", "admin")]
    waiting: dict[str, int] = {}
    for r in conn.execute(f"SELECT collection FROM ({PENDING}) q WHERE collection = ANY(%s)", (runs,)):
        waiting[r["collection"]] = waiting.get(r["collection"], 0) + 1
    for c in acct["collections"]:
        c["requests"] = waiting.get(c["slug"], 0)
    asked = [r["collection"] for r in conn.execute("SELECT collection FROM join_requests WHERE pubkey = %s", (pubkey,))]
    return {**acct, "terms_text": L.TERMS_TEXT.decode(), "requested": asked, "is_admin": L.is_admin(conn, pubkey),
            "email": email["email"] if email else None, "custodial": bool(email and email["held"])}


async def login(request: Request) -> JSONResponse:
    """POST a request event signed with tool "login"; get a 12-hour HttpOnly cookie."""
    from .server import authenticate
    def run(conn, ev):
        pubkey, _ = authenticate(conn, ev, "login")
        return pubkey, _account(conn, pubkey)
    try:
        pubkey, acct = await db(run, await request.json())
    except ValueError as err:
        return _error(err)
    resp = JSONResponse(acct)
    resp.set_cookie(COOKIE, make_cookie(pubkey), max_age=COOKIE_TTL, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


def turnstile_ok(token, ip: str, action: str, host: str) -> bool:
    """Cloudflare's verdict on a Turnstile token: it passed, for this action ("signup" or "email"),
    on one of our hostnames. True when Turnstile isn't configured. Tests replace httpx.post."""
    if not TURNSTILE_SECRET:
        return True
    if not isinstance(token, str) or not token or len(token) > 2048:
        return False
    try:
        r = httpx.post("https://challenges.cloudflare.com/turnstile/v0/siteverify", timeout=10,
                       data={"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip})
        r.raise_for_status()
        out = r.json()
    except (httpx.HTTPError, ValueError):
        return False
    if (out.get("metadata") or {}).get("result_with_testing_key"):  # Cloudflare's test keys: example.com, no action
        return out.get("success") is True
    return out.get("success") is True and out.get("action") == action and out.get("hostname") in (TURNSTILE_HOSTNAMES or {host})


async def signup(request: Request) -> JSONResponse:
    """POST {event, turnstile}: a login request signed by a new key, plus a Turnstile token. Creates
    the free account (the signups table) and logs in. Signing up again is harmless."""
    from .server import authenticate
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _error(ValueError("send {event, turnstile}"))
    if not await run_in_threadpool(turnstile_ok, body.get("turnstile"), _client_ip(request), "signup", request.url.hostname):
        return JSONResponse({"error": "the bot check failed; try it again", "turnstile": True}, status_code=400)

    def run(conn, ev):
        pubkey, _ = authenticate(conn, ev, "login", check_allowed=False)
        conn.execute("INSERT INTO signups (pubkey) VALUES (%s) ON CONFLICT DO NOTHING", (pubkey,))
        return pubkey, _account(conn, pubkey)
    try:
        pubkey, acct = await db(run, body.get("event"))
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


TITLES = {"/": "Collections", "/connect": "Account", "/submit": "Submit", "/communities": "Communities", "/pricing": "Pricing"}


def with_header(request: Request, html: str) -> str:
    """A page with the shared header (tms/site.py) filled in for this visitor, and its title."""
    path, signed_in = request.url.path, cookie_pubkey(request) is not None
    title = ("Invite" if path.endswith("/invite") else "Members") if path.startswith("/c/") else TITLES.get(path, "")
    if path == "/connect" and not signed_in:
        title = "Log in"
    return (html.replace("<!--HEADER-->", site.header(signed_in, path)).replace("?v=SITE_V", f"?v={site.VERSION}")
            .replace("<title>Paranoy</title>", f"<title>Paranoy · {title}</title>" if title else "<title>Paranoy</title>"))


def to_login(request: Request) -> RedirectResponse:
    """Signed-out visitors to a signed-in page go to Login, which brings them back after (?next=)."""
    from urllib.parse import quote
    here = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/connect?next={quote(here, safe='/?=&')}", status_code=302)


async def page(request: Request):
    if request.url.path == "/submit" and cookie_pubkey(request) is None:
        return to_login(request)
    return HTMLResponse(with_header(request, PAGE_FILE.read_text(encoding="utf-8")  # re-read so edits show on refresh
                                    .replace("{{TURNSTILE_SITE_KEY}}", TURNSTILE_SITE_KEY)))


async def home(request: Request):
    """Logged out, the landing page is the office; logged in, your collections and their pin boards."""
    resp = (HTMLResponse(with_header(request, COLLECTIONS_FILE.read_text(encoding="utf-8"))) if cookie_pubkey(request)
            else await office(request))
    resp.headers["Cache-Control"] = "private, no-store"  # the page depends on the cookie
    return resp


REQUEST_LIMIT, REQUEST_WINDOW = 5, 3600  # email codes per IP per hour
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


async def pricing(request: Request) -> HTMLResponse:
    """Plans. ponytail: no checkout yet, the paid buttons email CONTACT_EMAIL; Stripe when someone wants to pay."""
    return HTMLResponse(with_header(request, PRICING_FILE.read_text(encoding="utf-8").replace("{{CONTACT_EMAIL}}", CONTACT_EMAIL)))


async def office(request: Request) -> HTMLResponse:
    """Ambient picture of the work. Papers are squiggles; nothing here is ledger data."""
    return HTMLResponse(with_header(request, OFFICE_FILE.read_text(encoding="utf-8")))


def _docs_text(request: Request, path: Path = DOCS_FILE) -> str:
    base = str(request.base_url).rstrip("/")  # behind DO's proxy, uvicorn's proxy_headers make this https
    return (path.read_text(encoding="utf-8").replace("{{BASE}}", base).replace("{{CONTACT_EMAIL}}", CONTACT_EMAIL)
            .replace("{{TERMS_VERSION}}", L.TERMS["version"]).replace("{{TERMS_SHA256}}", L.TERMS["sha256"]))


async def docs(request: Request) -> HTMLResponse:
    """DOCS.md, rendered in the browser by a pinned marked; readable as plain text without JS."""
    return _docs_html(request, DOCS_FILE)


def _docs_html(request: Request, path: Path) -> HTMLResponse:
    title = "Paranoy · Docs" if path == DOCS_FILE else f"Paranoy · {path.read_text(encoding='utf-8').split(chr(10), 1)[0].lstrip('# ')}"
    return HTMLResponse(DOCS_PAGE.format(md=escape(_docs_text(request, path)), toc_js=TOC_JS, title=escape(title),
                                         header=site.header(cookie_pubkey(request) is not None, request.url.path))
                        .replace("?v=SITE_V", f"?v={site.VERSION}"))


async def docs_page(request: Request) -> HTMLResponse:
    """An extra docs page from DOCS_PAGES, same template as /docs."""
    path = DOCS_PAGES.get(request.path_params["name"])
    if path is None:
        return HTMLResponse("not found", status_code=404)
    return _docs_html(request, path)


async def docs_md(request: Request) -> PlainTextResponse:
    return PlainTextResponse(_docs_text(request), media_type="text/markdown; charset=utf-8")


async def members_page(request: Request):
    pubkey, slug = cookie_pubkey(request), request.path_params["slug"]
    if pubkey is None:
        return to_login(request)
    role = await db(L.acting_role, pubkey, slug)
    if role not in ("owner", "admin"):
        return PlainTextResponse(f"Only an owner or admin of '{slug}' manages its members.", status_code=403)
    return await page(request)


async def me(request: Request) -> JSONResponse:
    pubkey = cookie_pubkey(request)
    if pubkey is None:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    return JSONResponse(await db(_account, pubkey))


async def collection(request: Request) -> JSONResponse:
    """Members of one collection with their profile names, for the members page."""
    pubkey, slug = cookie_pubkey(request), request.path_params["slug"]
    if pubkey is None:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    def run(conn):
        L.require_member(conn, pubkey, slug)
        owner = conn.execute("SELECT owner FROM collections WHERE slug = %s", (slug,)).fetchone()["owner"]
        members = [L._clean(r) for r in conn.execute(
            """SELECT r.pubkey, r.role, p.name, p.about FROM collection_roster r
               LEFT JOIN profiles p ON p.pubkey = r.pubkey
               WHERE r.collection = %s
               ORDER BY CASE r.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                        p.name NULLS LAST, r.pubkey""", (slug,))]
        bots = L.collection_bots(conn, slug)
        for m in members:
            m.update(bots.get(m["pubkey"], {"ledger": None, "agents": []}))
        about = conn.execute("SELECT topic, public FROM collection_about WHERE collection = %s", (slug,)).fetchone()
        role = L.acting_role(conn, pubkey, slug)
        requests = [L._clean(r) for r in conn.execute(f"{PENDING} AND j.collection = %s ORDER BY j.at", (slug,))] if role in ("owner", "admin") else []
        return owner, members, role, about, requests
    try:
        owner, members, role, about, requests = await db(run)
    except ValueError as err:
        return _error(err)
    for m in members + requests:
        m["npub"] = E.bech32_encode("npub", m["pubkey"])
    invite = f"{str(request.base_url).rstrip('/')}/c/{slug}/invite?t={invite_token(slug)}" if role in ("owner", "admin") else None
    return JSONResponse({"slug": slug, "owner": owner, "caller_role": role, "members": members, "requests": requests,
                         "topic": about["topic"] if about else None, "public": bool(about and about["public"]), "invite": invite})


async def join(request: Request) -> JSONResponse:
    """POST {note, invite}: ask to join a public collection, or any collection with its invite token.
    The owner and admins see it on the members page, and an owner who signed in by email gets an email.
    One request per key and collection."""
    pubkey, slug = cookie_pubkey(request), request.path_params["slug"]
    if pubkey is None:
        return JSONResponse({"error": "log in first"}, status_code=401)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    note = str((body or {}).get("note") or "").strip()
    invited = hmac.compare_digest(str((body or {}).get("invite") or ""), invite_token(slug))
    note = (f"Came from your invite link. {note}" if invited else note).strip()[:280]

    def run(conn):
        L.require_allowed(conn, pubkey)
        about = conn.execute("SELECT public FROM collection_about WHERE collection = %s", (slug,)).fetchone()
        if not (invited or (about and about["public"])):
            raise L.Denied(f"'{slug}' is not open to requests")  # private collections stay unseen
        if conn.execute("SELECT 1 FROM members WHERE collection = %s AND pubkey = %s", (slug, pubkey)).fetchone():
            raise ValueError(f"you are already a member of '{slug}'")
        new = conn.execute("""INSERT INTO join_requests (collection, pubkey, note) VALUES (%s, %s, %s)
                              ON CONFLICT DO NOTHING RETURNING at""", (slug, pubkey, note)).fetchone()
        owner = conn.execute("""SELECT a.email, p.name FROM collections c JOIN email_accounts a ON a.pubkey = c.owner
                                LEFT JOIN profiles p ON p.pubkey = %s WHERE c.slug = %s""", (pubkey, slug)).fetchone()
        return bool(new), owner
    try:
        new, owner = await db(run)
    except ValueError as err:
        return _error(err)
    if new and owner:  # ponytail: email only owners who signed in by email; extension-only owners see it in the app
        from . import email_login
        who = owner["name"] or E.bech32_encode("npub", pubkey)[:16] + "…"
        base = str(request.base_url).rstrip("/")
        try:
            await run_in_threadpool(email_login.send, owner["email"], f"{who} asked to join {slug} on Paranoy",
                                    f"{who} asked to join your collection {slug}." + (f'\n\n"{note}"' if note else "")
                                    + f"\n\nAccept or dismiss it on the members page: {base}/c/{slug}/members")
        except Exception as err:  # the request is saved either way
            print(f"join request email failed: {err}", file=sys.stderr)
    return JSONResponse({"ok": True, "status": "asked" if new else "already asked"})


async def invite_page(request: Request):
    """Where an invite link lands. Signed out: Login (or sign up), then back here."""
    if cookie_pubkey(request) is None:
        return to_login(request)
    return await page(request)


async def dismiss(request: Request) -> JSONResponse:
    """POST: an owner or admin dismisses a join request. Accepting is signing a members list."""
    pubkey, slug, who = cookie_pubkey(request), request.path_params["slug"], request.path_params["pubkey"]
    if pubkey is None:
        return JSONResponse({"error": "log in first"}, status_code=401)

    def run(conn):
        if L.acting_role(conn, pubkey, slug) not in ("owner", "admin"):
            raise L.Denied(f"only an owner or admin of '{slug}' answers its requests")
        conn.execute("""UPDATE join_requests SET dismissed_by = %s, dismissed_at = now()
                        WHERE collection = %s AND pubkey = %s AND dismissed_at IS NULL""", (pubkey, slug, who))
    try:
        await db(run)
    except ValueError as err:
        return _error(err)
    return JSONResponse({"ok": True})


BOARD_LINKS = 300  # ponytail: the board is the ends of the newest links; paging or zooming in if that ever falls short
BOARD_LOOSE = 12   # per kind: the newest evidence and claims with no link yet, in a row under the board


def board(conn, pubkey: str, slug: str) -> dict:
    """One collection as a pin board: the evidence and claims at the ends of its newest links and
    contradictions, every link between them, and a few of the newest records nothing links to yet.
    Members only. The page lays it out; nothing about the layout is stored."""
    L.require_member(conn, pubkey, slug)
    contradictions = [L._clean(r) for r in conn.execute("""SELECT x.id, x.reason, x.claim_ids AS claims FROM contradictions x
            WHERE x.collection = %s ORDER BY x.received_at DESC, x.id LIMIT 50""", (slug,))]
    ends = conn.execute("""SELECT x.from_id, x.to_id FROM links x WHERE x.collection = %s
            ORDER BY x.received_at DESC, x.id LIMIT %s""", (slug, BOARD_LINKS)).fetchall()
    shown = list({r[k] for r in ends for k in ("from_id", "to_id")} | {i for k in contradictions for i in k["claims"]})
    who = "coalesce((SELECT p.name FROM profiles p WHERE p.pubkey = x.pubkey), 'no profile') AS author"
    ev = f"SELECT x.id, x.pubkey, {who}, x.title, x.source, x.url, x.received_at, left(x.text, 280) AS excerpt FROM evidence x"
    cl = f"SELECT x.id, x.pubkey, {who}, x.text, x.received_at FROM claims x"
    rows = lambda sql, *a: [L._clean(r) for r in conn.execute(sql, a)]
    evidence = rows(ev + " WHERE x.collection = %s AND x.id = ANY(%s) ORDER BY x.received_at DESC, x.id", slug, shown)
    claims = rows(cl + " WHERE x.collection = %s AND x.id = ANY(%s) ORDER BY x.received_at DESC, x.id", slug, shown)
    links = rows("""SELECT x.id, x.from_id AS "from", x.to_id AS "to", x.relation
            FROM links x WHERE x.collection = %s AND x.from_id = ANY(%s) AND x.to_id = ANY(%s)""", slug, shown, shown)
    unlinked = " AND ".join(f"NOT EXISTS (SELECT 1 FROM links l WHERE l.{end} = x.id)" for end in ("from_id", "to_id"))  # both indexed
    loose = {"evidence": rows(ev + f" WHERE x.collection = %s AND {unlinked} ORDER BY x.received_at DESC, x.id LIMIT %s", slug, BOARD_LOOSE),
             "claims": rows(cl + f""" WHERE x.collection = %s AND {unlinked} AND NOT EXISTS
                 (SELECT 1 FROM contradiction_claims k WHERE k.claim_id = x.id) ORDER BY x.received_at DESC, x.id LIMIT %s""", slug, BOARD_LOOSE)}
    totals = L._clean(conn.execute("""SELECT count(*) FILTER (WHERE kind = 4701) AS evidence, count(*) FILTER (WHERE kind = 4702) AS claims,
            count(*) FILTER (WHERE kind = 4703) AS links FROM events WHERE collection = %s""", (slug,)).fetchone())
    return {"slug": slug, "evidence": evidence, "claims": claims, "links": links, "contradictions": contradictions,
            "loose": loose, "totals": totals}


async def board_json(request: Request) -> JSONResponse:
    pubkey = cookie_pubkey(request)
    if pubkey is None:
        return JSONResponse({"error": "not logged in"}, status_code=401)
    try:
        return JSONResponse(await db(board, pubkey, request.path_params["slug"]))
    except ValueError as err:
        return _error(err)


async def publish(request: Request) -> JSONResponse:
    """Signed events need no cookie: each one is its own proof."""
    def run(body):
        events = body.get("events") if isinstance(body, dict) else body
        with L.connect() as conn:
            res = L.publish(conn, events)
        if any(isinstance(e, dict) and e.get("kind") == E.ABOUT for e in events):
            from . import office
            office._showcase.clear()  # a topic or visibility change shows on /communities at once
        return res
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
        await db(L.require_allowed, pubkey)
        text, title = await run_in_threadpool(L.fetch_text, url)  # over HTTP, ALLOW_LOCAL is off: http(s) only
    except Exception as err:
        return _error(err)
    return JSONResponse({"url": url, "title": title, "text": text})


async def export(request: Request):
    pubkey, slug = cookie_pubkey(request), request.path_params["slug"]
    if pubkey is None:
        return PlainTextResponse("log in first", status_code=401)
    try:
        await db(L.require_member, pubkey, slug)
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
    Route("/submit", page),
    Route("/communities", page),
    Route("/office", office),
    Route("/pricing", pricing),
    *[Route("/" + f.name, lambda r, f=f: FileResponse(f, headers={"Cache-Control": "public, max-age=86400"}))
      for f in (Path(__file__).with_name("site.css"), Path(__file__).with_name("site.js"))],  # the shared header and styles; pages add ?v=

    *[Route("/" + f.name, lambda r, f=f: FileResponse(f, headers={"Cache-Control": "public, max-age=86400"}))
      for f in Path(__file__).with_name("brand").iterdir()],  # favicon.svg, favicon.ico, apple-touch-icon.png, logo.png (emails)
    Route("/c/{slug}/members", members_page),
    Route("/c/{slug}/invite", invite_page),
    Route("/c/{slug}/export.jsonl", export),
    Route("/login", login, methods=["POST"]),
    Route("/api/signup", signup, methods=["POST"]),
    Route("/logout", logout, methods=["POST"]),
    Route("/api/me", me),
    Route("/api/c/{slug}", collection),
    Route("/api/c/{slug}/board", board_json),
    Route("/api/c/{slug}/join", join, methods=["POST"]),
    Route("/api/c/{slug}/join/{pubkey}/dismiss", dismiss, methods=["POST"]),
    Route("/api/publish", publish, methods=["POST"]),
    Route("/api/fetch", fetch),
]
