"""TMS v2 ledger: signed-event publishing, member-scoped reads, retrieval, proof checking.

Every function takes an open psycopg connection; reads also take the caller's verified pubkey
and only see collections that pubkey is a member of. The ledger stores signed assertions and
relationships; it never decides what is true. The server checks signatures and access here;
db/init.sql checks references, link quotes and immutability.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import html
import ipaddress
import os
import re
import subprocess
import sys
import tempfile
import threading
from contextlib import nullcontext
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from pathlib import Path
from urllib.parse import urlparse

import httpx
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import events as E

DB_URL = (os.environ.get("DATABASE_URL") or os.environ.get("TMS_DATABASE_URL")
          or "postgresql://tmsv2:tmsv2@localhost:5432/tmsv2")
# OpenAI-compatible embeddings: DeepInfra in the cloud, Ollama's /v1 locally.
EMBED_URL = os.environ.get("EMBED_URL", "http://localhost:11434/v1").rstrip("/")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY", "")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "qwen3-embedding:8b")  # DeepInfra: Qwen/Qwen3-Embedding-8B
EMBED_DIM = 4096
EMBED_PRICE_PER_MTOK = float(os.environ.get("EMBED_PRICE_PER_MTOK", "0.01"))  # USD; DeepInfra's Qwen3-Embedding-8B rate
QUERY_PREFIX = "Instruct: Given a question or statement, retrieve claims relevant to it\nQuery: "
APPROVED = {E.pubkey_hex(p) for p in re.split(r"[\s,]+", os.environ.get("TMS_APPROVED", "")) if p}
ADMINS = {E.pubkey_hex(p) for p in re.split(r"[\s,]+", os.environ.get("TMS_ADMINS", "")) if p}  # site admins
SERVER_PUBKEY = E.pubkey_of(os.environ["TMS_SERVER_NSEC"]) if os.environ.get("TMS_SERVER_NSEC") else None
TERMS_TEXT = (Path(__file__).resolve().parent.parent / "TERMS.md").read_bytes()
TERMS = {"version": re.search(rb"Version (\S+)", TERMS_TEXT).group(1).decode(),
         "sha256": hashlib.sha256(TERMS_TEXT).hexdigest()}
MAX_CONTENT = 2_000_000  # chars per event; ponytail: one cap for everything, split documents if it ever binds
MAX_BATCH = 1000
MAX_BYTES = 50_000_000   # download/file cap before extraction
ALLOW_LOCAL = True       # the HTTP entry point sets this False: remote callers get http(s) only
FETCH_HEADERS = {
    # ponytail: a browser-like UA gets past most publishers; for the rest the caller
    # fetches the text itself (Firecrawl, a browser) and passes it as content.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/pdf,text/html,application/xml,text/plain;q=0.9,*/*;q=0.8",
}


class Denied(ValueError):
    """The signer may not do this. The message says why."""


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


# Telemetry waits this long for a pooled connection, then drops its row: a full pool must not
# hold up the call being logged (the pool's own default wait is 30 s).
TELEMETRY_WAIT = 2.0


def connect(timeout: float | None = None):
    """A pooled connection (context manager). Autocommit; batches open their own transaction.
    prepare_threshold=None because PgBouncer in transaction mode breaks prepared statements.
    timeout: seconds to wait for a free connection; None is the pool default."""
    global _pool
    with _pool_lock:
        if _pool is None:
            # check: a cheap ping on checkout, so connections dropped by a database restart are replaced
            _pool = ConnectionPool(DB_URL, min_size=1, max_size=10, open=True, check=ConnectionPool.check_connection, kwargs={
                "autocommit": True, "row_factory": dict_row, "prepare_threshold": None})
            atexit.register(_pool.close)
    return _pool.connection(timeout=timeout)


def _clean(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(row).items()}


def _limit(n, hi: int = 200) -> int:
    return max(1, min(int(n), hi))


def _offset(n) -> int:
    return max(0, int(n))


# ---------------------------------------------------------------- embeddings

def embed(texts: list[str], query: bool = False, pubkey: str | None = None,
          collection: str | None = None, conn=None) -> list[str]:
    """pgvector literals for each text. Queries get the Qwen3 instruct prefix. Each call is
    logged in embed_calls with the tokens the endpoint reports; a local endpoint costs nothing.
    Pass the caller's conn when it holds one: a second checkout while holding the first can
    starve a full pool. The embed_calls row then commits (or rolls back) with the caller's
    transaction, if one is open."""
    r = httpx.post(f"{EMBED_URL}/embeddings", timeout=120,
                   headers={"Authorization": f"Bearer {EMBED_API_KEY}"} if EMBED_API_KEY else {},
                   json={"model": EMBED_MODEL, "input": [(QUERY_PREFIX + t) if query else t for t in texts],
                         "encoding_format": "float"})
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as err:
        if r.status_code != 429:
            raise
        retry_after = r.headers.get("Retry-After", "")
        try:
            delay = int(retry_after) if retry_after.isascii() and retry_after.isdigit() else ceil(
                (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
            delay = max(1, delay)
        except (ValueError, TypeError, OverflowError):
            delay = 60  # No usable provider hint; suggest a delay without holding a database connection.
        raise RuntimeError(
            f"Embedding service rate limited (429; retryable). Retry after {delay} seconds with a fresh signed request. "
            "For search_claims, method='keyword' remains available; it uses word matching instead of vector similarity."
        ) from err
    body = r.json()
    usage = body.get("usage") or {}
    tokens = int(usage.get("total_tokens") or usage.get("prompt_tokens") or 0)
    cost = 0.0 if _is_internal(urlparse(EMBED_URL).hostname or "") else tokens * EMBED_PRICE_PER_MTOK / 1e6
    try:  # in its own transaction, or a savepoint in the caller's, so a failed insert aborts nothing else
        with nullcontext(conn) if conn is not None else connect(timeout=TELEMETRY_WAIT) as c, c.transaction():
            c.execute("""INSERT INTO embed_calls (pubkey, collection, model, tokens, cost_usd)
                         VALUES (%s, %s, %s, %s, %s)""", (pubkey, collection, EMBED_MODEL, tokens, cost))
    except Exception as err:  # telemetry never fails an embedding
        print(f"embed_calls logging failed: {err}", file=sys.stderr)
    out = []
    for item in sorted(body["data"], key=lambda d: d["index"]):
        if len(item["embedding"]) != EMBED_DIM:
            raise RuntimeError(f"{EMBED_MODEL} returned {len(item['embedding'])} dims, schema expects {EMBED_DIM}")
        out.append("[" + ",".join(repr(float(x)) for x in item["embedding"]) + "]")
    return out


def embed_pending(conn, pubkey: str | None = None, limit: int = 64) -> int:
    """Embed claims that have no vector yet (this batch's, plus any an earlier outage left),
    one call per collection so embed_calls can attribute the cost."""
    rows = conn.execute("""SELECT c.id, c.text, c.collection FROM claims c LEFT JOIN embeddings v ON v.event_id = c.id
                           WHERE v.event_id IS NULL ORDER BY c.collection, c.received_at LIMIT %s""", (limit,)).fetchall()
    chunks: list[list[dict]] = []
    for r in rows:
        if not chunks or len(chunks[-1]) == 32 or chunks[-1][0]["collection"] != r["collection"]:
            chunks.append([])
        chunks[-1].append(r)
    for chunk in chunks:
        vecs = embed([r["text"] for r in chunk], pubkey=pubkey, collection=chunk[0]["collection"], conn=conn)
        conn.cursor().executemany(
            "INSERT INTO embeddings (event_id, vector, model) VALUES (%s, %s::vector, %s) ON CONFLICT DO NOTHING",
            [(r["id"], v, EMBED_MODEL) for r, v in zip(chunk, vecs)])
    return len(rows)


# -------------------------------------------------------------------- fetch

def _is_internal(host: str) -> bool:
    if host in ("", "localhost") or host.endswith(".localhost"):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False  # ponytail: a DNS name resolving to a private address still gets through


def _download(uri: str) -> tuple[bytes, str]:
    with httpx.stream("GET", uri, follow_redirects=True, timeout=60, headers=FETCH_HEADERS) as r:
        r.raise_for_status()
        chunks, size = [], 0
        for chunk in r.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError(f"{uri} exceeds {MAX_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks), r.headers.get("content-type", "")


# Bot walls and captcha pages that publishers serve instead of the article.
CHALLENGE = re.compile(r"recaptcha|hcaptcha|g-recaptcha|cf-challenge|challenge-platform|cf-turnstile|"
                       r"just a moment\.\.\.|are you a robot|verify you are (a )?human|captcha", re.IGNORECASE)
MIN_HTML_TEXT = 200  # chars; ponytail: one fixed floor, tune if real short pages get rejected


def _reject_stub(uri: str, doc: str, text: str) -> None:
    """Refuse an HTML page that is a bot challenge or nearly empty, so it never becomes evidence."""
    n = len(text.strip())
    if n < MIN_HTML_TEXT or (n < 2000 and CHALLENGE.search(doc)):
        raise ValueError(f"{uri} returned a bot challenge or near-empty page ({n} chars of text), not the "
                         "document; get the text another way (an API, an archive copy) and publish it as evidence")


def fetch_text(uri: str) -> tuple[str, str | None]:
    """Fetch an http(s) URL, or read a local path when ALLOW_LOCAL, and return (plain text, title).
    PDF via pdftotext, HTML via trafilatura, JATS XML by stripping tags; the title comes from
    <title>/<article-title> for HTML/XML and is None otherwise."""
    parsed = urlparse(uri)
    path = uri[7:] if uri.startswith("file://") else uri
    if parsed.scheme in ("http", "https"):
        if not ALLOW_LOCAL and _is_internal(parsed.hostname or ""):
            raise ValueError("internal hosts are not fetched for remote callers; pass the text as content")
        data, ctype = _download(uri)
    elif not ALLOW_LOCAL:
        raise ValueError("only http(s) URLs are fetched for remote callers; pass the text as content")
    elif os.path.isfile(path):
        if os.path.getsize(path) > MAX_BYTES:
            raise ValueError(f"{path} exceeds {MAX_BYTES} bytes")
        with open(path, "rb") as f:
            data = f.read()
        ctype = ""
    else:
        raise ValueError(f"{uri} is neither an http(s) URL nor an existing file")

    title = None
    if data[:5] == b"%PDF-" or "pdf" in ctype or (not ctype and path.lower().endswith(".pdf")):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                text = subprocess.run(["pdftotext", tmp.name, "-"], capture_output=True, text=True,
                                      check=True, timeout=120).stdout
            except subprocess.CalledProcessError as err:
                raise ValueError(f"pdftotext failed: {err.stderr.strip()[:300]}") from err
    elif "html" in ctype or b"<html" in data[:2000].lower():
        import trafilatura
        doc = data.decode("utf-8", errors="replace")
        text = trafilatura.extract(doc, include_comments=False, include_tables=True) or ""
        m = re.search(r"<title[^>]*>(.*?)</title>", doc, re.S | re.I)
        title = m.group(1) if m else trafilatura.extract_metadata(doc).title
        _reject_stub(uri, doc, text)
    elif "xml" in ctype or data.lstrip()[:5] == b"<?xml":
        # JATS full text from the Europe PMC REST API and similar: keep the words, drop the tags.
        doc = data.decode("utf-8", errors="replace")
        m = re.search(r"<article-title\b[^>]*>(.*?)</article-title>", doc, re.S)
        title = m.group(1) if m else None
        # Front matter shrinks to title + abstract; journal metadata, bibliography and back matter go.
        front = re.search(r"<front>.*?</front>", doc, re.S)
        if front:
            keep = re.findall(r"<article-title\b[^>]*>.*?</article-title>|<abstract\b[^>]*>.*?</abstract>", front.group(), re.S)
            doc = doc[:front.start()] + "\n".join(keep) + doc[front.end():]
        doc = re.sub(r"<(journal-meta|ref-list|back)\b.*?</\1>", " ", doc, flags=re.S)
        doc = re.sub(r"</t[dh]>", "\t", doc)  # table cells stay apart, one row per line
        doc = re.sub(r"</(tr|p|title|sec)>", "\n", doc)
        text = html.unescape(re.sub(r"<[^>]+>", " ", doc))
    else:
        text = data.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        raise ValueError(f"No text could be extracted from {uri}")
    if title:
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", title)).split())  # inline markup, not separators
    return text, title or None




# -------------------------------------------------------------------- access

def my_collections(conn, pubkey: str) -> list[str]:
    return [r["collection"] for r in conn.execute(
        "SELECT collection FROM members WHERE pubkey = %s ORDER BY collection", (pubkey,))]


def is_admin(conn, pubkey: str | None) -> bool:
    """A site admin (TMS_ADMINS) or an admin a site admin added in /admin (the admins table)."""
    return bool(pubkey) and (pubkey in ADMINS or conn.execute(
        "SELECT 1 FROM admins WHERE pubkey = %s", (pubkey,)).fetchone() is not None)


def is_approved(conn, pubkey: str) -> bool:
    """Approved by the operator: an admin, TMS_APPROVED (env, for bootstrap), or the approvals table."""
    return pubkey in APPROVED or is_admin(conn, pubkey) or conn.execute(
        "SELECT 1 FROM approvals WHERE pubkey = %s", (pubkey,)).fetchone() is not None


def allowed(conn, pubkey: str) -> bool:
    """Approved, or a member of some collection (EVENTS.md section 3)."""
    return is_approved(conn, pubkey) or conn.execute(
        "SELECT 1 FROM members WHERE pubkey = %s LIMIT 1", (pubkey,)).fetchone() is not None


def require_allowed(conn, pubkey: str) -> None:
    if not allowed(conn, pubkey):
        raise Denied(f"{pubkey} is not approved and is not a member of any collection")


def require_member(conn, pubkey: str, collection: str) -> None:
    if not isinstance(collection, str) or not collection:
        raise ValueError("collection is required")
    if conn.execute("SELECT 1 FROM members WHERE collection = %s AND pubkey = %s",
                    (collection, pubkey)).fetchone() is None:
        raise Denied(f"not a member of collection '{collection}'")


def signed_terms(conn, pubkey: str) -> bool:
    return conn.execute("""SELECT 1 FROM events WHERE kind = 4706 AND pubkey = %s
                             AND content::jsonb ->> 'version' = %s AND content::jsonb ->> 'sha256' = %s LIMIT 1""",
                        (pubkey, TERMS["version"], TERMS["sha256"])).fetchone() is not None


def account(conn, pubkey: str) -> dict:
    """What the web pages need to know about a signer."""
    profile = _clean(conn.execute("SELECT * FROM profiles WHERE pubkey = %s", (pubkey,)).fetchone())
    return {"pubkey": pubkey, "npub": E.bech32_encode("npub", pubkey), "approved": is_approved(conn, pubkey),
            "allowed": allowed(conn, pubkey), "terms_signed": signed_terms(conn, pubkey), "terms": TERMS,
            "profile": profile, "collections": list_collections(conn, pubkey)}


# ------------------------------------------------------------------ publish

def _authorize(conn, ev: dict, data: dict) -> str | None:
    """Acceptance rule 3. Creates the collection when an approved signer names a new slug.
    Returns the event's collection (None for profiles, terms and snapshots)."""
    pk, kind = ev["pubkey"], ev["kind"]
    if kind == E.SNAPSHOT:
        return None  # rule 6 already checked the server key
    require_allowed(conn, pk)
    if kind == E.TERMS:
        if (data["version"], data["sha256"]) != (TERMS["version"], TERMS["sha256"]):
            raise E.Invalid(f"{ev['id']}: terms must be version {TERMS['version']} with sha256 {TERMS['sha256']}")
        return None
    if kind == E.PROFILE:
        return None
    if not signed_terms(conn, pk):
        raise Denied(f"{ev['id']}: sign the current terms first (kind 4706, version {TERMS['version']}, "
                     f"sha256 {TERMS['sha256']})")
    col = data["collection"]
    row = conn.execute("SELECT owner FROM collections WHERE slug = %s", (col,)).fetchone()
    if row is None:
        if not is_approved(conn, pk):
            raise Denied(f"{ev['id']}: collection '{col}' does not exist, and only approved pubkeys create collections")
        conn.execute("INSERT INTO collections (slug, owner) VALUES (%s, %s) ON CONFLICT DO NOTHING", (col, pk))
        row = conn.execute("SELECT owner FROM collections WHERE slug = %s", (col,)).fetchone()
    require_member(conn, pk, col)
    if kind in (E.MEMBERS, E.ABOUT) and row["owner"] != pk:
        raise Denied(f"{ev['id']}: only the owner of '{col}' changes its {E.NAMES[kind]}")
    return col


def publish(conn, events: list) -> dict:
    """Accept a batch of signed events, all or nothing (EVENTS.md section 5). Events already in
    the ledger are skipped. Claims are embedded after the batch commits."""
    if not isinstance(events, list) or not events:
        raise E.Invalid("events must be a non-empty list of signed events")
    if len(events) > MAX_BATCH:
        raise E.Invalid(f"at most {MAX_BATCH} events per batch")
    checked = []
    for ev in events:
        data = E.verify(ev)  # rules 1 and 2
        if ev["kind"] == E.REQUEST:
            raise E.Invalid(f"{ev['id']}: request events accompany tool calls and are never published")
        if (ev["kind"] == E.SNAPSHOT) != (SERVER_PUBKEY is not None and ev["pubkey"] == SERVER_PUBKEY):
            raise Denied(f"{ev['id']}: snapshots are signed by the server's key, and nothing else is")
        if len(ev["content"]) > MAX_CONTENT:
            raise E.Invalid(f"{ev['id']}: content is {len(ev['content'])} chars; cap is {MAX_CONTENT}")
        checked.append((ev, data))
    accepted, skipped, collections = [], [], set()
    with conn.transaction():
        for ev, data in checked:
            if conn.execute("SELECT 1 FROM events WHERE id = %s", (ev["id"],)).fetchone():
                skipped.append(ev["id"])  # same ID, same signed bytes: a retry
                continue
            col = _authorize(conn, ev, data)
            conn.execute("""INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig, collection)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                         (ev["id"], ev["pubkey"], ev["created_at"], ev["kind"], Jsonb(ev["tags"]), ev["content"],
                          ev["sig"], col))
            accepted.append(ev["id"])
            collections.add(col)
    out = {"accepted": accepted, "skipped": skipped}
    if any(ev["kind"] == E.CLAIM for ev, _ in checked):
        try:
            out["embedded"] = embed_pending(conn, checked[0][0]["pubkey"])
        except (httpx.HTTPError, RuntimeError, KeyError) as err:  # the claims are in; vectors catch up next time
            out["embedding_error"] = str(err)[:300]
    out["collections"] = sorted(c for c in collections if c)
    return out


# -------------------------------------------------------------------- reads

AUTHOR = "(SELECT name FROM profiles p WHERE p.pubkey = x.pubkey) AS author"
LINK_COLS = f"""x.id, x.pubkey, {AUTHOR}, x.from_id AS "from", x.to_id AS "to", x.relation, x.quote, x.reason,
                x.received_at"""


def list_collections(conn, pubkey: str) -> list[dict]:
    return [_clean(r) for r in conn.execute(
        """SELECT c.slug, c.owner, c.created_at,
                  ARRAY(SELECT m.pubkey FROM members m WHERE m.collection = c.slug ORDER BY m.pubkey) AS members,
                  (SELECT count(*) FROM evidence WHERE collection = c.slug) AS evidence,
                  (SELECT count(*) FROM claims WHERE collection = c.slug) AS claims,
                  (SELECT count(*) FROM links WHERE collection = c.slug) AS links,
                  (SELECT count(*) FROM contradictions WHERE collection = c.slug) AS contradictions,
                  a.topic, coalesce(a.public, false) AS public
           FROM collections c LEFT JOIN collection_about a ON a.collection = c.slug
           WHERE c.slug IN (SELECT collection FROM members WHERE pubkey = %s)
           ORDER BY c.created_at, c.slug""", (pubkey,))]


def showcase(conn) -> list[dict]:
    """Collections whose owner made them public: name, topic and record counts only."""
    return [_clean(r) for r in conn.execute(
        """SELECT a.collection AS slug, a.topic,
                  count(*) FILTER (WHERE e.kind = 4701) AS evidence, count(*) FILTER (WHERE e.kind = 4702) AS claims,
                  count(*) FILTER (WHERE e.kind = 4703) AS links, count(*) FILTER (WHERE e.kind = 4704) AS contradictions
           FROM collection_about a LEFT JOIN events e ON e.collection = a.collection
           WHERE a.public GROUP BY a.collection, a.topic
           ORDER BY count(*) FILTER (WHERE e.kind BETWEEN 4701 AND 4704) DESC, a.collection""")]


def _visible(conn, pubkey: str, ref: str):
    """The event row if the caller may read it: collection events need membership; profiles,
    terms and snapshots are visible to anyone allowed in."""
    if not isinstance(ref, str) or not E.HEX64.match(ref):
        return None
    row = conn.execute("SELECT * FROM events WHERE id = %s", (ref,)).fetchone()
    if row is None:
        return None
    if row["collection"] is not None and conn.execute(
            "SELECT 1 FROM members WHERE collection = %s AND pubkey = %s", (row["collection"], pubkey)).fetchone() is None:
        return None
    return row


def get_event(conn, pubkey: str, id: str, offset: int = 0, max_chars: int = 20000) -> dict | None:
    """One event by ID, content parsed. Evidence text comes back as a window: offset, max_chars, chars."""
    row = _visible(conn, pubkey, id)
    if row is None:
        return None

    data = json.loads(row["content"])
    out = _clean({k: row[k] for k in ("id", "pubkey", "kind", "collection", "created_at", "received_at")})
    out["kind_name"] = E.NAMES[row["kind"]]
    out["author"] = (conn.execute("SELECT name FROM profiles WHERE pubkey = %s", (row["pubkey"],)).fetchone()
                     or {}).get("name")
    if row["kind"] == E.EVIDENCE:
        offset, text = max(0, int(offset)), data["text"]
        data["text"] = text[offset:offset + max(0, int(max_chars))]
        out.update(chars=len(text), offset=offset)
    out["content"] = data
    return out


def _attach_claim_context(conn, collection: str, claims: list[dict]) -> list[dict]:
    """Inline each claim's links and contradiction memberships. Raw records, no verdicts."""
    ids = [c["id"] for c in claims]
    if not ids:
        return claims
    links: dict[str, list] = {i: [] for i in ids}
    for r in conn.execute(f"SELECT {LINK_COLS} FROM links x WHERE x.to_id = ANY(%s) ORDER BY x.received_at, x.id", (ids,)):
        links[r["to"]].append(_clean(r))
    ks: dict[str, list] = {i: [] for i in ids}
    for r in conn.execute("""SELECT id, claim_ids FROM contradictions WHERE collection = %s AND claim_ids && %s
                             ORDER BY received_at, id""", (collection, ids)):
        for c in r["claim_ids"]:
            if c in ks:
                ks[c].append(r["id"])
    for c in claims:
        c["links"] = links[c["id"]]
        c["contradiction_ids"] = ks[c["id"]]
    return claims


def search_claims(conn, pubkey: str, collection: str, text: str, method: str = "vector", limit: int = 10) -> dict:
    require_member(conn, pubkey, collection)
    limit = _limit(limit)
    if method == "vector":
        rows = conn.execute(
            f"""SELECT x.id, x.pubkey, {AUTHOR}, x.text, x.received_at, v.vector <=> %s::vector AS distance
                FROM claims x JOIN embeddings v ON v.event_id = x.id WHERE x.collection = %s
                ORDER BY distance, x.id LIMIT %s""", (embed([text], query=True, pubkey=pubkey, collection=collection, conn=conn)[0], collection, limit))
    elif method == "keyword":
        rows = conn.execute(
            f"""SELECT x.id, x.pubkey, {AUTHOR}, x.text, x.received_at,
                       ts_rank_cd(to_tsvector('simple', x.text), plainto_tsquery('simple', %s)) AS rank
                FROM claims x WHERE x.collection = %s
                  AND to_tsvector('simple', x.text) @@ plainto_tsquery('simple', %s)
                ORDER BY rank DESC, x.id LIMIT %s""", (text, collection, text, limit))
    else:
        raise ValueError("method must be 'vector' or 'keyword'")
    items = _attach_claim_context(conn, collection, [_clean(r) for r in rows])
    for e in (e for c in items for e in c["links"]):  # search results stay skimmable; get_links has the whole quote
        if len(e["quote"]) > 300:
            e["quote"] = e["quote"][:300] + "…"
    return {"method": method, "note": "Distances and ranks are retrieval aids, not confidence.", "items": items}


CLAIM_COUNTS = """(SELECT count(*) FROM links l WHERE l.to_id = x.id AND l.relation = 'SUPPORTS') AS supports,
    (SELECT count(*) FROM links l WHERE l.to_id = x.id AND l.relation = 'QUALIFIES') AS qualifies,
    (SELECT count(*) FROM links l WHERE l.to_id = x.id AND l.relation = 'REBUTS') AS rebuts,
    (SELECT count(*) FROM contradictions k WHERE k.collection = x.collection AND x.id = ANY(k.claim_ids)) AS findings"""
CLAIM_SORTS = {
    "recent": "received_at DESC, id",
    "oldest": "received_at, id",  # stable order for paging through every claim
    "links": "supports + qualifies + rebuts DESC, received_at DESC, id",
    "unsupported": "supports + qualifies + rebuts ASC, received_at DESC, id",
    "unchallenged": "rebuts + qualifies ASC, supports DESC, received_at DESC, id",
    "contested": "rebuts DESC, findings DESC, received_at DESC, id",
}


def list_claims(conn, pubkey: str, collection: str, sort: str = "unsupported", limit: int = 50,
                offset: int = 0) -> list[dict]:
    """Claims with their link counts, ordered for follow-up work. Counts are retrieval aids, not verdicts."""
    require_member(conn, pubkey, collection)
    if sort not in CLAIM_SORTS:
        raise ValueError(f"sort must be one of {sorted(CLAIM_SORTS)}")
    return [_clean(r) for r in conn.execute(
        f"""SELECT * FROM (SELECT x.id, x.pubkey, {AUTHOR}, x.text, x.received_at, {CLAIM_COUNTS}
                           FROM claims x WHERE x.collection = %s) b
            ORDER BY {CLAIM_SORTS[sort]} LIMIT %s OFFSET %s""", (collection, _limit(limit), _offset(offset)))]


def get_links(conn, pubkey: str, collection: str, to_id: str = "", from_id: str = "", relation: str = "",
              limit: int = 100, offset: int = 0) -> list[dict]:
    """Links in a collection, filtered by target, grounding evidence and/or relation."""
    require_member(conn, pubkey, collection)
    where, params = ["x.collection = %s"], [collection]
    for col, val in (("x.to_id", to_id), ("x.from_id", from_id), ("x.relation", relation)):
        if val:
            where.append(f"{col} = %s")
            params.append(val)
    return [_clean(r) for r in conn.execute(
        f"SELECT {LINK_COLS} FROM links x WHERE {' AND '.join(where)} ORDER BY x.received_at, x.id LIMIT %s OFFSET %s",
        (*params, _limit(limit, 1000), _offset(offset)))]


def list_evidence(conn, pubkey: str, collection: str, ungrounded_only: bool = False, source: str = "",
                  limit: int = 50, offset: int = 0) -> list[dict]:
    """Evidence documents in a collection, oldest first, without their text. ungrounded_only: no link
    cites them yet. source: substring of the source field."""
    require_member(conn, pubkey, collection)
    where, params = ["x.collection = %s"], [collection]
    if ungrounded_only:
        where.append("NOT EXISTS (SELECT 1 FROM links l WHERE l.from_id = x.id)")
    if source:
        where.append("x.source ILIKE %s")
        params.append(f"%{source}%")
    return [_clean(r) for r in conn.execute(
        f"""SELECT x.id, x.pubkey, {AUTHOR}, x.title, x.url, x.source,
                   e.content::jsonb ->> 'archive_url' AS archive_url, e.content::jsonb ->> 'retrieved_via' AS retrieved_via,
                   x.received_at, char_length(x.text) AS chars,
                   (SELECT count(*) FROM links l WHERE l.from_id = x.id) AS link_count
            FROM evidence x JOIN events e ON e.id = x.id
            WHERE {' AND '.join(where)} ORDER BY x.received_at, x.id LIMIT %s OFFSET %s""",
        (*params, _limit(limit, 500), _offset(offset)))]


def search_contradictions(conn, pubkey: str, collection: str, claim: str = "", text: str = "",
                          limit: int = 20) -> list[dict]:
    """Contradictions in a collection, optionally naming a claim or matching words in the reason,
    each with its member claims and the links that target it."""
    require_member(conn, pubkey, collection)
    where, params = ["x.collection = %s"], [collection]
    if claim:
        where.append("%s = ANY(x.claim_ids)")
        params.append(claim)
    if text:
        where.append("to_tsvector('simple', x.reason) @@ plainto_tsquery('simple', %s)")
        params.append(text)
    rows = [_clean(r) for r in conn.execute(
        f"""SELECT x.id, x.pubkey, {AUTHOR}, x.reason, x.claim_ids, x.received_at FROM contradictions x
            WHERE {' AND '.join(where)} ORDER BY x.received_at, x.id LIMIT %s""", (*params, _limit(limit)))]
    for r in rows:
        r["claims"] = [_clean(c) for c in conn.execute(
            f"SELECT x.id, x.pubkey, {AUTHOR}, x.text FROM claims x WHERE x.id = ANY(%s) ORDER BY x.id", (r["claim_ids"],))]
        r["links"] = [_clean(c) for c in conn.execute(
            f"SELECT {LINK_COLS} FROM links x WHERE x.to_id = %s ORDER BY x.received_at, x.id", (r["id"],))]
    return rows


def export(conn, pubkey: str, collection: str, page: int = 500):
    """Every event in the collection, oldest first, as signed envelopes that each verify on their own."""
    require_member(conn, pubkey, collection)
    after = ("-infinity", "")
    while True:
        rows = conn.execute(
            """SELECT id, pubkey, created_at, kind, tags, content, sig, received_at FROM events
               WHERE collection = %s AND (received_at, id) > (%s::timestamptz, %s) ORDER BY received_at, id LIMIT %s""",
            (collection, *after, page)).fetchall()
        for r in rows:
            yield {"id": r["id"], "pubkey": r["pubkey"], "created_at": r["created_at"], "kind": r["kind"],
                   "tags": r["tags"], "content": r["content"], "sig": r["sig"]}
        if len(rows) < page:
            return
        after = (rows[-1]["received_at"], rows[-1]["id"])


# --------------------------------------------------------------- telemetry

def log_call(conn, method: str, tool: str | None, pubkey: str | None, collection: str | None,
             ok: bool, error: str | None, ms: int) -> None:
    """Operational record of one MCP request. Not part of the ledger."""
    conn.execute(
        "INSERT INTO mcp_calls (method, tool, pubkey, collection, ok, error, ms) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (method, tool, pubkey, collection, ok, error, ms))


# -------------------------------------------------------------- proof check

def _leaf_line(row: dict) -> str:

    c = json.loads(row["content"])
    kind = row["kind"]
    if kind == E.CLAIM:
        return f"claim: {c['text']}"
    if kind == E.LINK:
        return f"link {c['relation']} {c['to']} from {c['from']}: \"{c['quote']}\""
    if kind == E.CONTRADICTION:
        return f"contradiction among {', '.join(c['claims'])}: {c['reason']}"
    if kind == E.EVIDENCE:
        title = f'"{c["title"]}" ' if c.get("title") else ""
        where = " ".join(x for x in (c.get("url"), f"({c['source']})" if c.get("source") else None) if x)
        return f"evidence {title}{where} by {row['pubkey'][:12]}".replace("  ", " ")
    return f"{E.NAMES[kind]} by {row['pubkey'][:12]}"


def check_proof(conn, pubkey: str, collection: str, proof: dict) -> dict:
    """Validate a thinking proof: steps cite events in this collection or earlier steps; one root;
    every step is grounded or marked gap. Returns problems and an inspectable tree."""
    require_member(conn, pubkey, collection)
    steps = proof.get("steps") if isinstance(proof, dict) else None
    if not isinstance(steps, list) or not steps:
        return {"ok": False, "problems": ["proof.steps must be a non-empty list"], "tree": ""}
    problems: list[str] = []
    by_id: dict[str, dict] = {}
    premises: dict[str, list[str]] = {}
    grounded: dict[str, bool] = {}
    leaves: dict[str, dict] = {}
    referenced: set[str] = set()
    all_ids = {s.get("id") for s in steps if isinstance(s, dict) and isinstance(s.get("id"), str)}
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            problems.append(f"step {i}: not an object")
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not sid or sid in by_id:
            problems.append(f"step {i}: missing, non-string or duplicate id")
            continue
        by_id[sid] = s
        if not isinstance(s.get("say"), str) or not s["say"].strip():
            problems.append(f"{sid}: 'say' must be a non-empty string")
        frm = s.get("from") or []
        if not isinstance(frm, list) or not all(isinstance(r, str) for r in frm):
            problems.append(f"{sid}: 'from' must be a list of id strings")
            frm = []
        premises[sid] = frm
        ok = False
        for ref in frm:
            if ref in grounded:
                referenced.add(ref)
                ok = ok or grounded[ref]
            elif ref in all_ids:
                problems.append(f"{sid}: cites step {ref}, which is not an earlier step; list premises before conclusions")
            else:
                row = _visible(conn, pubkey, ref)
                if row is None or row["collection"] != collection:  # never say which other collection
                    problems.append(f"{sid}: {ref} is not an event in collection '{collection}'")
                    continue
                leaves[ref] = row
                ok = True
        if not ok and not s.get("gap"):
            problems.append(f"{sid}: no ledger event in its ancestry and not marked gap")
        grounded[sid] = ok
    roots = [sid for sid in by_id if sid not in referenced]
    if len(roots) != 1:
        problems.append(f"expected exactly one root step, found {roots}")

    lines: list[str] = []
    order = {sid: i for i, sid in enumerate(by_id)}
    shown: set[str] = set()

    def render(sid: str, depth: int) -> None:
        pad = "  " * depth
        if sid in shown:  # a shared premise: print once, then point back
            lines.append(f"{pad}[{sid}] (see above)")
            return
        shown.add(sid)
        s = by_id[sid]
        tag = " (gap)" if s.get("gap") else ""
        lines.append(f"{pad}[{sid}]{tag} {s.get('say', '')}")
        for ref in premises[sid]:
            if ref in by_id and order[ref] < order[sid]:
                render(ref, depth + 1)
            elif ref in by_id:
                lines.append(f"{pad}  [{ref}] ?? not an earlier step")
            elif ref in leaves:
                lines.append(f"{pad}  {ref} {_leaf_line(leaves[ref])}")
            else:
                lines.append(f"{pad}  {ref} ?? unresolved")

    for r in roots:
        render(r, 0)
    return {"ok": not problems, "problems": problems, "root": roots[0] if len(roots) == 1 else None,
            "tree": "\n".join(lines)}
