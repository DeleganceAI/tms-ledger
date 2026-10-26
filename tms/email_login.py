"""Email sign-in: a one-time code by email, and a Nostr key the server holds for the account.

Signing up with an email creates a Nostr key pair for that address. The server keeps the secret,
encrypted with TMS_KEY_SECRET, and signs the account's events with it (/api/sign), so the pages
work without a browser extension. The user can export the key (after a fresh emailed code) and ask
the server to forget it; from then on the account signs with its own key, like any Nostr user.
There are no passwords: every sign-in emails a new code. Codes go out through Resend.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sys

import httpx
from coincurve import PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import events as E
from . import ledger as L
from . import web as W

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("TMS_EMAIL_FROM", "TMS ledger <login@delegance.ai>")
KEY_SECRET = os.environ.get("TMS_KEY_SECRET", "")
DEV_PRINT = os.environ.get("TMS_EMAIL_DEV") == "1"  # local only: print codes instead of emailing them
# who hears about new access requests; defaults to the site's contact address
NOTIFY = [a.strip() for a in (os.environ.get("TMS_NOTIFY_EMAIL") or W.CONTACT_EMAIL).split(",") if a.strip()]
CODE_TTL = 600            # seconds a code stays valid
CODES_PER_HOUR = 5        # codes per email address per hour
MAX_ATTEMPTS = 5          # wrong guesses before a code is dead
EXPORT_GRACE = 600        # seconds after an export during which "forget my key" needs no new code
SIGNABLE = {E.PROFILE, E.EVIDENCE, E.CLAIM, E.LINK, E.CONTRADICTION, E.MEMBERS, E.TERMS}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Refused(ValueError):
    """The request can't go ahead; the message says why. status is the HTTP code."""
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def configured() -> bool:
    return bool(KEY_SECRET) and (bool(RESEND_API_KEY) or DEV_PRINT)


# ------------------------------------------------------------------ keys at rest

def _aead() -> AESGCM:
    return AESGCM(hashlib.sha256(KEY_SECRET.encode()).digest())


def seal(secret: bytes, pubkey: str) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + _aead().encrypt(nonce, secret, pubkey.encode())).decode()


def unseal(blob: str, pubkey: str) -> bytes:
    raw = base64.b64decode(blob)
    return _aead().decrypt(raw[:12], raw[12:], pubkey.encode())


# ------------------------------------------------------------------ codes

def _hash(email: str, purpose: str, code: str) -> str:
    return hmac.new(os.environ["TMS_SECRET"].encode(), f"{purpose}:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def send(email: str, subject: str, text: str) -> None:
    """Send one email through Resend. Tests replace this."""
    if not RESEND_API_KEY:
        if DEV_PRINT:
            print(f"[email to {email}] {subject}\n{text}", file=sys.stderr)
            return
        raise Refused("email sign-in is not configured", 503)
    r = httpx.post("https://api.resend.com/emails", timeout=20, headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                   json={"from": EMAIL_FROM, "to": [email], "subject": subject, "text": text})
    if r.status_code >= 400:
        raise Refused("the email could not be sent; try again in a minute", 502)


def issue(conn, email: str, purpose: str) -> None:
    n = conn.execute("""SELECT count(*) AS n FROM email_codes WHERE email = %s AND created_at > now() - interval '1 hour'""",
                     (email,)).fetchone()["n"]
    if n >= CODES_PER_HOUR:
        raise Refused("too many codes for this address; wait an hour and try again", 429)
    code = f"{secrets.randbelow(10**6):06d}"
    conn.execute("""INSERT INTO email_codes (email, purpose, code_hash, expires_at)
                    VALUES (%s, %s, %s, now() + make_interval(secs => %s))""", (email, purpose, _hash(email, purpose, code), CODE_TTL))
    what = "sign in to" if purpose == "login" else "export your key from"
    send(email, f"Your TMS code: {code}",
         f"Your code to {what} the TMS ledger is:\n\n    {code}\n\nIt works once and expires in {CODE_TTL // 60} minutes. "
         "If you didn't ask for it, ignore this email.")


def redeem(conn, email: str, purpose: str, code: str) -> None:
    """Use up the newest live code for this address and purpose, or refuse."""
    row = conn.execute("""SELECT id, code_hash, attempts FROM email_codes
                          WHERE email = %s AND purpose = %s AND used_at IS NULL AND expires_at > now()
                          ORDER BY created_at DESC LIMIT 1""", (email, purpose)).fetchone()
    if row is None or row["attempts"] >= MAX_ATTEMPTS:
        raise Refused("that code is wrong or has expired; ask for a new one")
    if not hmac.compare_digest(row["code_hash"], _hash(email, purpose, re.sub(r"\D", "", code))):
        conn.execute("UPDATE email_codes SET attempts = attempts + 1 WHERE id = %s", (row["id"],))
        raise Refused("that code is wrong or has expired; ask for a new one")
    conn.execute("UPDATE email_codes SET used_at = now() WHERE id = %s", (row["id"],))


def _email(raw) -> str:
    email = str(raw or "").strip().lower()
    if not EMAIL.match(email) or len(email) > 254:
        raise Refused("enter a valid email address")
    return email


def ensure_account(conn, email: str) -> dict:
    """The email account for this address, creating it and its held key on first use."""
    sk = PrivateKey()
    pubkey = E.pubkey_of(sk.secret)
    conn.execute("""INSERT INTO email_accounts (email, pubkey, nsec_enc) VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO NOTHING""", (email, pubkey, seal(sk.secret, pubkey)))
    return conn.execute("SELECT * FROM email_accounts WHERE email = %s", (email,)).fetchone()


def notify_request(base: str, npub: str | None, email: str | None, note: str | None) -> None:
    """Tell the admins a request arrived. Best effort: a failed email never fails the request."""
    if not NOTIFY or not (RESEND_API_KEY or DEV_PRINT):
        return
    who = " / ".join(x for x in (npub, email) if x)
    try:
        for to in NOTIFY:
            send(to, f"TMS access request: {email or npub[:20] + '…'}",
                 f"Someone asked for access to the TMS ledger.\n\n{'npub:  ' + npub + chr(10) if npub else ''}"
                 f"{'email: ' + email + chr(10) if email else ''}note:  {note or '(none)'}\n\n"
                 f"Approve or dismiss it at {base}/admin")
    except Exception as err:
        print(f"access request notification failed for {who}: {err}", file=sys.stderr)


def notify_approved(base: str, email: str) -> None:
    """Tell an email requester they're in. Best effort."""
    if not (RESEND_API_KEY or DEV_PRINT):
        return
    try:
        send(email, "You're approved for the TMS ledger",
             f"Your access request was approved.\n\nSign in at {base}/connect: under \"Or sign in with email\", enter "
             f"{email} and we'll email you a one-time code. There's no password.")
    except Exception as err:
        print(f"approval email to {email} failed: {err}", file=sys.stderr)


def account_for(conn, pubkey: str) -> dict | None:
    return conn.execute("SELECT * FROM email_accounts WHERE pubkey = %s", (pubkey,)).fetchone()


# ------------------------------------------------------------------ HTTP

def _json_error(err: Exception) -> JSONResponse:
    if isinstance(err, Refused):
        return JSONResponse({"error": str(err)}, status_code=err.status)
    return W._error(err)


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise Refused("send a JSON object")
    return body


def _same_site(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise Refused("cross-site request refused", 403)


async def start(request: Request) -> JSONResponse:
    """POST {email}: email a sign-in code. The reply is the same whether or not the address has an account."""
    try:
        if not configured():
            raise Refused("email sign-in is not configured", 503)
        _same_site(request)
        if W._rate_limited("email:" + W._client_ip(request)):
            raise Refused("too many requests from this address; try again later", 429)
        email = _email((await _body(request)).get("email"))

        def run():
            with L.connect() as conn:
                issue(conn, email, "login")
        await run_in_threadpool(run)
    except (Refused, ValueError) as err:
        return _json_error(err)
    return JSONResponse({"sent": True})


async def verify(request: Request) -> JSONResponse:
    """POST {email, code}: sign in, creating the account and its key on first use."""
    try:
        if not configured():
            raise Refused("email sign-in is not configured", 503)
        _same_site(request)
        body = await _body(request)
        email, code = _email(body.get("email")), str(body.get("code") or "")

        def run():
            with L.connect() as conn:  # autocommit: a wrong guess's attempt count sticks
                redeem(conn, email, "login", code)
                acct = ensure_account(conn, email)
                if acct["nsec_enc"] is None:
                    raise Refused("this account now signs with its own key: connect with your Nostr extension instead", 409)
                pubkey = acct["pubkey"]
                if not L.allowed(conn, pubkey):
                    npub = E.bech32_encode("npub", pubkey)
                    new = conn.execute("""INSERT INTO access_requests (npub, email, note) SELECT %s, %s, %s
                                          WHERE NOT EXISTS (SELECT 1 FROM access_requests WHERE npub = %s AND status = 'pending')
                                          RETURNING id""", (npub, email, "Signed up by email", npub)).fetchone()
                    if new:
                        notify_request(str(request.base_url).rstrip("/"), npub, email, "Signed up by email")
                    raise Refused(f"your account is created and waiting for an admin to approve it ({npub})", 403)
                return pubkey, W._account(conn, pubkey)
        pubkey, acct = await run_in_threadpool(run)
    except (Refused, ValueError) as err:
        return _json_error(err)
    resp = JSONResponse(acct)
    resp.set_cookie(W.COOKIE, W.make_cookie(pubkey), max_age=W.COOKIE_TTL, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


def _custodial(conn, request: Request) -> tuple[str, dict]:
    pubkey = W.cookie_pubkey(request)
    if pubkey is None:
        raise Refused("not logged in", 401)
    acct = account_for(conn, pubkey)
    if acct is None or acct["nsec_enc"] is None:
        raise Refused("this account signs with its own key", 403)
    return pubkey, acct


async def sign(request: Request) -> JSONResponse:
    """POST {kind, content}: sign one event with the account's held key. Nothing is published."""
    try:
        _same_site(request)
        body = await _body(request)
        kind, content = body.get("kind"), body.get("content")
        if kind not in SIGNABLE:
            raise Refused("that kind can't be signed here")

        def run():
            with L.connect() as conn:
                pubkey, acct = _custodial(conn, request)
                return E.sign(unseal(acct["nsec_enc"], pubkey), kind, content, tags=body.get("tags") or None)
        return JSONResponse(await run_in_threadpool(run))
    except (Refused, ValueError, TypeError) as err:
        return _json_error(err)


async def export_code(request: Request) -> JSONResponse:
    """POST: email the account a code for exporting its key."""
    try:
        if not configured():
            raise Refused("email sign-in is not configured", 503)
        _same_site(request)

        def run():
            with L.connect() as conn:
                _, acct = _custodial(conn, request)
                issue(conn, acct["email"], "export")
        await run_in_threadpool(run)
    except (Refused, ValueError) as err:
        return _json_error(err)
    return JSONResponse({"sent": True})


async def export(request: Request) -> JSONResponse:
    """POST {code}: the account's secret key, once per code."""
    try:
        _same_site(request)
        code = str((await _body(request)).get("code") or "")

        def run():
            with L.connect() as conn:
                pubkey, acct = _custodial(conn, request)
                redeem(conn, acct["email"], "export", code)
                conn.execute("UPDATE email_accounts SET exported_at = now() WHERE pubkey = %s", (pubkey,))
                secret = unseal(acct["nsec_enc"], pubkey)
                return {"nsec": E.bech32_encode("nsec", secret.hex()), "npub": E.bech32_encode("npub", pubkey)}
        return JSONResponse(await run_in_threadpool(run))
    except (Refused, ValueError) as err:
        return _json_error(err)


async def forget(request: Request) -> JSONResponse:
    """POST: delete the held key, within EXPORT_GRACE of exporting it. The account then signs for itself."""
    try:
        _same_site(request)

        def run():
            with L.connect() as conn:
                pubkey, _ = _custodial(conn, request)
                done = conn.execute(f"""UPDATE email_accounts SET nsec_enc = NULL WHERE pubkey = %s
                                        AND exported_at > now() - interval '{EXPORT_GRACE} seconds' RETURNING pubkey""",
                                    (pubkey,)).fetchone()
                if done is None:
                    raise Refused("export your key first (within the last 10 minutes), then ask us to forget it")
        await run_in_threadpool(run)
    except (Refused, ValueError) as err:
        return _json_error(err)
    return JSONResponse({"forgotten": True})


routes = [
    Route("/api/email/start", start, methods=["POST"]),
    Route("/api/email/verify", verify, methods=["POST"]),
    Route("/api/sign", sign, methods=["POST"]),
    Route("/api/key/export-code", export_code, methods=["POST"]),
    Route("/api/key/export", export, methods=["POST"]),
    Route("/api/key/forget", forget, methods=["POST"]),
]
