"""Browser side: NIP-07 login cookie and the web pages (EVENTS.md section 6)."""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import events as E
from . import ledger as L

COOKIE = "tms"
COOKIE_TTL = 12 * 3600


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


async def login(request: Request) -> JSONResponse:
    """POST a request event signed with tool "login"; get a 12-hour HttpOnly cookie."""
    from .server import authenticate
    try:
        ev = await request.json()
        with L.connect() as conn:
            pubkey, _ = authenticate(conn, ev, "login")
            acct = L.account(conn, pubkey)
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


routes = [
    Route("/login", login, methods=["POST"]),
    Route("/logout", logout, methods=["POST"]),
]
