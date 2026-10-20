"""TMS v2 ledger: append-only writes, raw reads, retrieval, proof checking.

Every function takes an open psycopg connection. The ledger stores assertions
and relationships; it never decides what is true. The only mechanical guards
are structural (schema constraints) and citational (a quote must exist in the
observation it cites; a proof may only cite records that exist).
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime
from urllib.parse import urlparse

import httpx
import psycopg
from psycopg.rows import dict_row

DB_URL = os.environ.get("TMS_DATABASE_URL", "postgresql://tmsv2:tmsv2@localhost:5432/tmsv2")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.environ.get("TMS_EMBED_MODEL", "qwen3-embedding:8b")
EMBED_MODEL_LABEL = "Qwen/Qwen3-Embedding-8B"
EMBED_DIM = 4096
MAX_CONTENT = 2_000_000  # chars; ponytail: one cap for everything, split documents if it ever binds
MAX_BYTES = 50_000_000   # download/file cap before extraction
ALLOW_LOCAL = True       # the HTTP entry point sets this False: remote callers get http(s) only
QUERY_PREFIX = "Instruct: Given a question or statement, retrieve claims relevant to it\nQuery: "
FETCH_HEADERS = {
    # ponytail: a browser-like UA gets past most publishers; for the rest the caller
    # fetches the text itself (Firecrawl, a browser) and passes it as content.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/pdf,text/html,application/xml,text/plain;q=0.9,*/*;q=0.8",
}

TARGET_KINDS = ("claim", "contradiction", "evidence", "source", "observation")
RELATIONS = ("SUPPORTS", "REBUTS", "QUALIFIES")
TABLES = {
    "author": "authors", "collection": "collections", "source": "sources",
    "observation": "observations", "claim": "claims",
    "contradiction": "contradictions", "evidence": "evidence",
}
PREFIX_KIND = {"src": "source", "o": "observation", "c": "claim", "k": "contradiction", "e": "evidence"}


def connect(autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(DB_URL, autocommit=autocommit, row_factory=dict_row)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _clean(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = dict(row)
    row.pop("embedding", None)
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def _tidy_evidence(row: dict) -> dict:
    row = _clean(row)
    kind = row["target_kind"]
    row["target_id"] = row.pop(f"target_{kind}_id")
    for k in TARGET_KINDS:
        row.pop(f"target_{k}_id", None)
    return row


# ---------------------------------------------------------------- embeddings

def embed(text: str, query: bool = False) -> str:
    """Return the vector as a pgvector literal. Queries get the Qwen3 instruct prefix."""
    payload = {"model": EMBED_MODEL, "input": (QUERY_PREFIX + text) if query else text}
    r = httpx.post(f"{OLLAMA}/api/embed", json=payload, timeout=120)
    r.raise_for_status()
    vec = r.json()["embeddings"][0]
    if len(vec) != EMBED_DIM:
        raise RuntimeError(f"{EMBED_MODEL} returned {len(vec)} dims, schema expects {EMBED_DIM}")
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


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


# ------------------------------------------------------------------ appends

def add_author(conn, id: str, name: str, kind: str) -> dict:
    row = conn.execute("SELECT * FROM authors WHERE id = %s", (id,)).fetchone()
    if row and (row["name"], row["kind"]) == (name, kind):
        return _clean(row)  # re-registering the same identity is a no-op, not a duplicate-key error
    return _clean(conn.execute(
        "INSERT INTO authors (id, name, kind) VALUES (%s, %s, %s) RETURNING *", (id, name, kind)).fetchone())


def add_collection(conn, id: str, name: str, author_id: str) -> dict:
    return _clean(conn.execute(
        "INSERT INTO collections (id, name, author_id) VALUES (%s, %s, %s) RETURNING *",
        (id, name, author_id)).fetchone())


def add_source(conn, name: str, author_id: str, uri: str | None = None) -> dict:
    return _clean(conn.execute(
        "INSERT INTO sources (id, name, uri, author_id) VALUES (%s, %s, %s, %s) RETURNING *",
        (new_id("src"), name, uri, author_id)).fetchone())


def add_observation(conn, collection: str, source_id: str, author_id: str, uri: str,
                    content: str | None = None, title: str | None = None) -> dict:
    if content is None:
        content, fetched = fetch_text(uri)
        title = title or fetched
    if len(content) > MAX_CONTENT:
        raise ValueError(f"content is {len(content)} chars; cap is {MAX_CONTENT}")
    if not title:  # plain text and PDF: the first non-empty line
        title = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    title = title[:200] or None
    digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    row = conn.execute(
        """INSERT INTO observations (id, collection_id, source_id, uri, title, content, content_hash, author_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING id, collection_id, source_id, uri, title, content_hash, author_id, asserted_at,
                     char_length(content) AS chars, left(content, 300) AS preview""",
        (new_id("o"), collection, source_id, uri, title, content, digest, author_id)).fetchone()
    return _clean(row)


def add_claim(conn, collection: str, text: str, author_id: str) -> dict:
    vec = embed(text)
    return _clean(conn.execute(
        """INSERT INTO claims (id, collection_id, text, author_id, embedding, embedding_model)
           VALUES (%s, %s, %s, %s, %s::vector, %s) RETURNING *""",
        (new_id("c"), collection, text, author_id, vec, EMBED_MODEL_LABEL)).fetchone())


def add_evidence(conn, from_observation_id: str, target_kind: str, target_id: str, relation: str,
                 quote: str, reason: str, author_id: str) -> dict:
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind must be one of {TARGET_KINDS}")
    if relation not in RELATIONS:
        raise ValueError(f"relation must be one of {RELATIONS}")
    row = conn.execute(
        f"""INSERT INTO evidence (id, relation, from_observation_id, target_kind, target_{target_kind}_id,
                                  quote, reason, author_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (new_id("e"), relation, from_observation_id, target_kind, target_id, quote, reason, author_id)).fetchone()
    return _tidy_evidence(row)


def add_contradiction(conn, collection: str, claim_ids: list[str], reason: str, author_id: str) -> dict:
    ids = sorted(dict.fromkeys(claim_ids))
    if len(ids) < 2:
        raise ValueError("a contradiction names at least two distinct claims")
    n = conn.execute("SELECT count(*) AS n FROM claims WHERE id = ANY(%s) AND collection_id = %s",
                     (ids, collection)).fetchone()["n"]
    if n != len(ids):
        raise ValueError(f"every member claim must exist in collection '{collection}'")
    kid = new_id("k")
    with conn.transaction():
        row = conn.execute(
            """INSERT INTO contradictions (id, collection_id, reason, claim_count, author_id)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""", (kid, collection, reason, len(ids), author_id)).fetchone()
        conn.cursor().executemany(
            "INSERT INTO contradiction_claims (contradiction_id, claim_id) VALUES (%s, %s)",
            [(kid, c) for c in ids])
    return {**_clean(row), "claim_ids": ids}


# -------------------------------------------------------------------- reads

def list_collections(conn) -> list[dict]:
    return [_clean(r) for r in conn.execute(
        """SELECT c.*, (SELECT count(*) FROM observations o WHERE o.collection_id = c.id) AS observations,
                  (SELECT count(*) FROM claims k WHERE k.collection_id = c.id) AS claims
           FROM collections c ORDER BY c.asserted_at, c.id""")]


def search_sources(conn, text: str, limit: int = 20) -> list[dict]:
    like = f"%{text}%"
    return [_clean(r) for r in conn.execute(
        "SELECT * FROM sources WHERE name ILIKE %s OR uri ILIKE %s ORDER BY asserted_at, id LIMIT %s",
        (like, like, limit))]


def _members(conn, contradiction_ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in contradiction_ids}
    for r in conn.execute(
            "SELECT contradiction_id, claim_id FROM contradiction_claims WHERE contradiction_id = ANY(%s) ORDER BY claim_id",
            (contradiction_ids,)):
        out[r["contradiction_id"]].append(r["claim_id"])
    return out


def get_record(conn, kind: str, id: str, offset: int = 0, max_chars: int = 20000) -> dict | None:
    table = TABLES.get(kind)
    if table is None:
        raise ValueError(f"kind must be one of {sorted(TABLES)}")
    if kind == "observation":
        row = conn.execute(
            """SELECT id, collection_id, source_id, uri, title, content_hash, author_id, asserted_at,
                      char_length(content) AS chars, content IS NULL AS content_unavailable,
                      substr(content, %s + 1, %s) AS content
               FROM observations WHERE id = %s""", (offset, max_chars, id)).fetchone()
        if row:
            row = _clean(row)
            row["offset"] = offset
        return row
    row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (id,)).fetchone()
    if row is None:
        return None
    if kind == "evidence":
        return _tidy_evidence(row)
    row = _clean(row)
    if kind == "contradiction":
        row["claim_ids"] = _members(conn, [id])[id]
    return row


def get_evidence(conn, target_kind: str | None = None, target_id: str | None = None,
                 from_observation_id: str | None = None, relation: str | None = None, limit: int = 100) -> list[dict]:
    where, params = [], []
    if target_id and not target_kind:
        raise ValueError("target_id requires target_kind")
    if target_kind:
        if target_kind not in TARGET_KINDS:
            raise ValueError(f"target_kind must be one of {TARGET_KINDS}")
        where.append("target_kind = %s")
        params.append(target_kind)
        if target_id:
            where.append(f"target_{target_kind}_id = %s")
            params.append(target_id)
    if from_observation_id:
        where.append("from_observation_id = %s")
        params.append(from_observation_id)
    if relation:
        where.append("relation = %s")
        params.append(relation)
    sql = "SELECT * FROM evidence" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY asserted_at, id LIMIT %s"
    return [_tidy_evidence(r) for r in conn.execute(sql, (*params, limit))]


def _attach_claim_context(conn, claims: list[dict]) -> list[dict]:
    """Inline each claim's evidence and contradiction memberships. Raw records, no verdicts."""
    ids = [c["id"] for c in claims]
    if not ids:
        return claims
    ev: dict[str, list] = {i: [] for i in ids}
    for r in conn.execute(
            "SELECT * FROM evidence WHERE target_claim_id = ANY(%s) ORDER BY asserted_at, id", (ids,)):
        ev[r["target_claim_id"]].append(_tidy_evidence(r))
    ks: dict[str, list] = {i: [] for i in ids}
    for r in conn.execute(
            "SELECT claim_id, contradiction_id FROM contradiction_claims WHERE claim_id = ANY(%s) ORDER BY contradiction_id", (ids,)):
        ks[r["claim_id"]].append(r["contradiction_id"])
    for c in claims:
        c["evidence"] = ev[c["id"]]
        c["contradiction_ids"] = ks[c["id"]]
    return claims


def search_claims(conn, collection: str, text: str, method: str = "vector", limit: int = 10) -> dict:
    if method == "vector":
        rows = conn.execute(
            """SELECT id, collection_id, text, author_id, asserted_at, embedding <=> %s::vector AS distance
               FROM claims WHERE collection_id = %s AND embedding IS NOT NULL
               ORDER BY distance, id LIMIT %s""", (embed(text, query=True), collection, limit))
    elif method == "keyword":
        rows = conn.execute(
            """SELECT id, collection_id, text, author_id, asserted_at,
                      ts_rank_cd(to_tsvector('simple', text), plainto_tsquery('simple', %s)) AS rank
               FROM claims WHERE collection_id = %s
                 AND to_tsvector('simple', text) @@ plainto_tsquery('simple', %s)
               ORDER BY rank DESC, id LIMIT %s""", (text, collection, text, limit))
    else:
        raise ValueError("method must be 'vector' or 'keyword'")
    items = _attach_claim_context(conn, [_clean(r) for r in rows])
    for e in (e for c in items for e in c["evidence"]):  # search results stay skimmable; get_evidence has the whole quote
        if len(e["quote"]) > 300:
            e["quote"] = e["quote"][:300] + "…"
    return {"method": method, "note": "Distances and ranks are retrieval aids, not confidence.", "items": items}


def list_observations(conn, collection: str, ungrounded_only: bool = False, limit: int = 50) -> list[dict]:
    extra = "AND NOT EXISTS (SELECT 1 FROM evidence e WHERE e.from_observation_id = o.id)" if ungrounded_only else ""
    rows = conn.execute(
        f"""SELECT o.id, o.source_id, s.name AS source_name, o.title, o.uri, o.author_id, o.asserted_at,
                   char_length(o.content) AS chars, o.content IS NULL AS content_unavailable,
                   (SELECT count(*) FROM evidence e WHERE e.from_observation_id = o.id) AS evidence_count
            FROM observations o JOIN sources s ON s.id = o.source_id
            WHERE o.collection_id = %s {extra}
            ORDER BY o.asserted_at, o.id LIMIT %s""", (collection, limit))
    return [_clean(r) for r in rows]


def search_contradictions(conn, collection: str, claim_id: str | None = None, text: str | None = None,
                          limit: int = 20) -> list[dict]:
    where, params = ["k.collection_id = %s"], [collection]
    if claim_id:
        where.append("EXISTS (SELECT 1 FROM contradiction_claims m WHERE m.contradiction_id = k.id AND m.claim_id = %s)")
        params.append(claim_id)
    if text:
        where.append("to_tsvector('simple', k.reason) @@ plainto_tsquery('simple', %s)")
        params.append(text)
    rows = [_clean(r) for r in conn.execute(
        f"SELECT k.* FROM contradictions k WHERE {' AND '.join(where)} ORDER BY k.asserted_at, k.id LIMIT %s",
        (*params, limit))]
    if not rows:
        return rows
    members = _members(conn, [r["id"] for r in rows])
    ev: dict[str, list] = {r["id"]: [] for r in rows}
    for e in conn.execute(
            "SELECT * FROM evidence WHERE target_contradiction_id = ANY(%s) ORDER BY asserted_at, id", (list(ev),)):
        ev[e["target_contradiction_id"]].append(_tidy_evidence(e))
    for r in rows:
        r["claim_ids"] = members[r["id"]]
        r["claims"] = [_clean(c) for c in conn.execute(
            "SELECT id, text, author_id, asserted_at FROM claims WHERE id = ANY(%s) ORDER BY id", (r["claim_ids"],))]
        r["evidence"] = ev[r["id"]]
    return rows


# -------------------------------------------------------------- proof check

def _lookup(conn, ref: str) -> tuple[str, dict] | None:
    kind = PREFIX_KIND.get(ref.split("_", 1)[0]) if "_" in ref else None
    if kind is None:
        return None
    row = get_record(conn, kind, ref, max_chars=0)
    if row is None:
        return None
    if kind == "evidence":
        obs = conn.execute("SELECT collection_id FROM observations WHERE id = %s", (row["from_observation_id"],)).fetchone()
        row["collection_id"] = obs["collection_id"] if obs else None
    return kind, row


def _leaf_line(kind: str, row: dict) -> str:
    if kind == "claim":
        return f"claim: {row['text']}"
    if kind == "evidence":
        return f"evidence {row['relation']} {row['target_kind']} {row['target_id']} from {row['from_observation_id']}: \"{row['quote']}\""
    if kind == "contradiction":
        return f"contradiction among {', '.join(row['claim_ids'])}: {row['reason']}"
    if kind == "observation":
        title = f'"{row["title"]}" ' if row.get("title") else ""
        return f"observation {title}{row['uri']} (source {row['source_id']}, author {row['author_id']})"
    return f"source: {row['name']} {row.get('uri') or ''}".rstrip()


def check_proof(conn, collection: str, proof: dict) -> dict:
    """Validate a thinking proof: steps cite real ledger records in this collection or earlier
    steps; one root; every step is grounded or marked gap. Returns problems and an inspectable tree."""
    steps = proof.get("steps") if isinstance(proof, dict) else None
    if not isinstance(steps, list) or not steps:
        return {"ok": False, "problems": ["proof.steps must be a non-empty list"], "tree": ""}
    problems: list[str] = []
    by_id: dict[str, dict] = {}
    premises: dict[str, list[str]] = {}
    grounded: dict[str, bool] = {}
    leaves: dict[str, tuple[str, dict]] = {}
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
                found = _lookup(conn, ref)
                if found is None:
                    problems.append(f"{sid}: {ref} is not a ledger record")
                    continue
                kind, row = found
                rc = row.get("collection_id")
                if rc and rc != collection:
                    problems.append(f"{sid}: {ref} belongs to collection '{rc}', not '{collection}'")
                leaves[ref] = (kind, row)
                ok = True
        if not ok and not s.get("gap"):
            problems.append(f"{sid}: no ledger record in its ancestry and not marked gap")
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
                lines.append(f"{pad}  {ref} {_leaf_line(*leaves[ref])}")
            else:
                lines.append(f"{pad}  {ref} ?? unresolved")

    for r in roots:
        render(r, 0)
    return {"ok": not problems, "problems": problems, "root": roots[0] if len(roots) == 1 else None,
            "tree": "\n".join(lines)}
