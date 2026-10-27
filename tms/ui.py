"""Dashboard for watching the ledger and MCP activity, served at /dashboard behind the login cookie.

Read-only. Every query is scoped to the viewer's collections (EVENTS.md section 3), mcp_calls
included: a call row is visible when one of its collections is the viewer's, and a call with no
collection only to the key that made it. The page polls every two seconds on the Activity tab
and every thirty elsewhere, one request at a time, and not at all while the browser tab is hidden.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from . import events as E
from . import ledger as L
from .web import cookie_pubkey

# Display name: the latest kind-0 profile, else the first 12 hex chars of the key.
WHO = "coalesce((SELECT p.name FROM profiles p WHERE p.pubkey = {0}.pubkey), left({0}.pubkey, 12)) AS author"
# Calls the viewer may see. Publish logs join several collections with commas.
CALLS = """(SELECT * FROM mcp_calls WHERE string_to_array(collection, ',') && %(cols)s::text[]
            OR (collection IS NULL AND pubkey = %(pk)s))"""
# Show only the viewer's slugs from a comma-joined row, and drop the error text of a row that
# also names collections the viewer can't read (it may quote their IDs).
CALL_COLS = """id, at, method, tool, pubkey, ms, ok, {who},
    array_to_string(ARRAY(SELECT unnest(string_to_array(c.collection, ',')) INTERSECT SELECT unnest(%(cols)s::text[])), ',') AS collection,
    CASE WHEN c.collection IS NULL OR string_to_array(c.collection, ',') <@ %(cols)s::text[] THEN left(error, 240) END AS error"""
SUMMARY = """CASE x.kind
    WHEN 4701 THEN coalesce(x.content::jsonb ->> 'title', x.content::jsonb ->> 'url', left(x.content::jsonb ->> 'text', 160))
    WHEN 4702 THEN left(x.content::jsonb ->> 'text', 240)
    WHEN 4703 THEN (x.content::jsonb ->> 'relation') || ' ' || left(x.content::jsonb ->> 'to', 12) || ' · ' || left(x.content::jsonb ->> 'quote', 160)
    WHEN 4704 THEN left(x.content::jsonb ->> 'reason', 240)
    WHEN 4705 THEN jsonb_array_length(x.content::jsonb -> 'members') || ' members'
    WHEN 4710 THEN jsonb_array_length(x.content::jsonb -> 'admins') || ' admins'
    WHEN 4712 THEN 'opened for ' || left(x.content::jsonb ->> 'owner', 12)
  END AS summary"""


def _rows(conn, sql: str, params) -> list[dict]:
    return [L._clean(r) for r in conn.execute(sql, params)]


def _kinds(rows: list[dict], field: str = "kind") -> list[dict]:
    for r in rows:
        r[field] = E.NAMES.get(r[field], r[field])
    return rows


def snapshot(conn, pk: str, cols: list[str], limit: int = 100) -> dict:
    p = {"pk": pk, "cols": cols, "limit": limit}
    return {
        "now": datetime.now(UTC).isoformat(),
        "counts": L._clean(conn.execute("""SELECT cardinality(%(cols)s::text[]) AS collections,
              count(*) FILTER (WHERE kind = 4701) AS evidence, count(*) FILTER (WHERE kind = 4702) AS claims,
              count(*) FILTER (WHERE kind = 4703) AS links, count(*) FILTER (WHERE kind = 4704) AS contradictions,
              count(DISTINCT pubkey) AS contributors
            FROM events WHERE collection = ANY(%(cols)s)""", p).fetchone()),
        "collections": _rows(conn, """SELECT c.slug, count(*) FILTER (WHERE e.kind = 4701) AS evidence,
              count(*) FILTER (WHERE e.kind = 4702) AS claims, count(*) FILTER (WHERE e.kind = 4703) AS links,
              count(*) FILTER (WHERE e.kind = 4704) AS contradictions
            FROM collections c LEFT JOIN events e ON e.collection = c.slug
            WHERE c.slug = ANY(%(cols)s) GROUP BY c.slug, c.created_at ORDER BY c.created_at, c.slug""", p),
        "calls": L._clean(conn.execute(f"""SELECT count(*) AS total, count(*) FILTER (WHERE NOT ok) AS errors,
              count(*) FILTER (WHERE at > now() - interval '1 hour') AS last_hour,
              count(*) FILTER (WHERE at > now() - interval '5 minutes') AS last_5m,
              count(*) FILTER (WHERE tool = 'publish') AS writes,
              count(DISTINCT pubkey) FILTER (WHERE at > now() - interval '5 minutes') AS active_authors
            FROM {CALLS} c""", p).fetchone()),
        "calls_per_min": _rows(conn, f"""SELECT date_trunc('minute', at) AS m, count(*) AS n, count(*) FILTER (WHERE NOT ok) AS errors
            FROM {CALLS} c WHERE at > now() - interval '60 minutes' GROUP BY 1 ORDER BY 1""", p),
        "records_per_min": _rows(conn, """SELECT date_trunc('minute', received_at) AS m, count(*) AS n FROM events
            WHERE collection = ANY(%(cols)s) AND received_at > now() - interval '60 minutes' GROUP BY 1 ORDER BY 1""", p),
        "by_tool": _rows(conn, f"""SELECT coalesce(tool, method) AS name, count(*) AS n, count(*) FILTER (WHERE NOT ok) AS errors,
              round(avg(ms))::int AS avg_ms FROM {CALLS} c GROUP BY 1 ORDER BY n DESC, 1""", p),
        "by_author": _rows(conn, f"""SELECT c.pubkey, {WHO.format('c')}, count(*) AS n,
              count(*) FILTER (WHERE tool = 'publish') AS writes, count(*) FILTER (WHERE NOT ok) AS errors, max(at) AS last_at
            FROM {CALLS} c WHERE c.pubkey IS NOT NULL GROUP BY c.pubkey ORDER BY max(at) DESC""", p),
        "recent_calls": _rows(conn, f"""SELECT {CALL_COLS.format(who=WHO.format('c'))} FROM {CALLS} c
            ORDER BY at DESC, id DESC LIMIT %(limit)s""", p),
        "recent_records": _kinds(_rows(conn, f"""SELECT x.id, x.kind, x.collection, x.pubkey, {WHO.format('x')},
              x.received_at, {SUMMARY}
            FROM events x WHERE x.collection = ANY(%(cols)s) ORDER BY x.received_at DESC, x.id LIMIT %(limit)s""", p)),
    }


# kind -> (view, columns for the list, expression a text filter applies to)
BROWSE = {
    "claim": ("claims", f"x.text AS summary, {L.CLAIM_COUNTS}", "x.text"),
    "evidence": ("evidence", """coalesce(x.title, x.url, left(x.text, 200)) AS summary, x.source, x.url,
                 char_length(x.text) AS chars, (SELECT count(*) FROM links l WHERE l.from_id = x.id) AS link_count""",
                 "concat_ws(' ', x.title, x.url, x.source, x.text)"),
    "link": ("links", "x.relation || ' · ' || left(x.quote, 200) AS summary, x.relation, x.to_id, x.from_id",
             "x.quote || ' ' || x.reason"),
    "contradiction": ("contradictions", "x.reason AS summary, cardinality(x.claim_ids) AS members", "x.reason"),
}


def browse(conn, pk: str, cols: list[str], kind: str, q: str, collection: str, method: str, page: int,
           sort: str = "recent", size: int = 50) -> dict:
    if kind not in BROWSE:
        raise ValueError(f"kind must be one of {sorted(BROWSE)}")
    scope = [collection] if collection in cols else [] if collection else cols
    view, extra, searchable = BROWSE[kind]
    base = f"x.id, x.collection, x.pubkey, {WHO.format('x')}, x.received_at"
    if method == "vector" and kind == "claim" and q:
        vec = L.embed([q], query=True, pubkey=pk, collection=collection or None, conn=conn)[0]
        items = _rows(conn, f"""SELECT {base}, {extra}, round((v.vector <=> %s::vector)::numeric, 3)::float8 AS distance
            FROM claims x JOIN embeddings v ON v.event_id = x.id WHERE x.collection = ANY(%s)
            ORDER BY v.vector <=> %s::vector, x.id LIMIT %s""", (vec, scope, vec, size))
        return {"items": items, "more": False, "method": "vector"}
    where, params = ["x.collection = ANY(%s)"], [scope]
    if q:
        where.append(f"({searchable}) ILIKE %s")
        params.append(f"%{q}%")
    order = L.CLAIM_SORTS.get(sort, L.CLAIM_SORTS["recent"]) if kind == "claim" else L.CLAIM_SORTS["recent"]
    items = _rows(conn, f"""SELECT * FROM (SELECT {base}, {extra} FROM {view} x WHERE {' AND '.join(where)}) b
        ORDER BY {order} LIMIT %s OFFSET %s""", (*params, size + 1, page * size))
    return {"items": items[:size], "more": len(items) > size, "method": "keyword"}


LINK_COLS = f"""x.id, x.pubkey, {WHO.format('x')}, x.from_id, x.to_id, x.relation, x.quote, x.reason, x.received_at,
    (SELECT kind FROM events t WHERE t.id = x.to_id) AS to_kind"""
RAW_MAX = 20000


def record(conn, cols: list[str], id: str) -> dict | None:
    """One event (if it is in the viewer's collections) plus the records around it, for the drawer."""
    row = conn.execute("SELECT * FROM events WHERE id = %s AND collection = ANY(%s)", (id, cols)).fetchone()
    if row is None:
        return None
    col, kind = row["collection"], row["kind"]
    data = json.loads(row["content"])
    raw = {k: row[k] for k in ("id", "pubkey", "created_at", "kind")} | {"tags": row["tags"], "content": row["content"], "sig": row["sig"]}
    rec = L._clean({k: row[k] for k in ("id", "pubkey", "collection", "created_at", "received_at")})
    rec |= {"kind": E.NAMES[kind], "raw": raw, "author": conn.execute(
        f"SELECT {WHO.format('e')} FROM events e WHERE e.id = %s", (id,)).fetchone()["author"]}
    if len(row["content"]) > RAW_MAX:  # ponytail: drawer only; the export has every byte
        raw["content"], rec["raw_truncated"] = row["content"][:RAW_MAX], True
    if kind == E.EVIDENCE:
        rec["chars"] = len(data["text"])
        data["text"] = data["text"][:6000]
        rec["links_from"] = _kinds(_rows(conn, f"SELECT {LINK_COLS} FROM links x WHERE x.from_id = %s AND x.collection = %s ORDER BY x.received_at, x.id", (id, col)), "to_kind")
    rec["content"] = data
    # Links that target this record: evidence on a claim, or a dispute of a link or contradiction.
    rec["links"] = _kinds(_rows(conn, f"SELECT {LINK_COLS} FROM links x WHERE x.to_id = %s AND x.collection = %s ORDER BY x.received_at, x.id", (id, col)), "to_kind")
    if kind == E.CLAIM:
        rec["contradictions"] = _rows(conn, """SELECT x.id, x.reason, x.claim_ids, x.received_at,
              (SELECT count(*) FROM links l WHERE l.to_id = x.id) AS link_count
            FROM contradictions x WHERE x.collection = %s AND %s = ANY(x.claim_ids) ORDER BY x.received_at, x.id""", (col, id))
    elif kind == E.CONTRADICTION:
        rec["claims"] = _rows(conn, f"SELECT x.id, x.pubkey, {WHO.format('x')}, x.text FROM claims x WHERE x.id = ANY(%s) AND x.collection = %s ORDER BY x.id", (data["claims"], col))
    elif kind == E.LINK:
        rec["evidence"] = L._clean(conn.execute(f"""SELECT x.id, x.pubkey, {WHO.format('x')}, x.title, x.url, x.source, x.received_at,
              char_length(x.text) AS chars FROM evidence x WHERE x.id = %s AND x.collection = %s""", (data["from"], col)).fetchone())
        target = _kinds(_rows(conn, f"SELECT x.id, x.kind, {SUMMARY} FROM events x WHERE x.id = %s AND x.collection = %s",
                              (data["to"], col)))
        rec["target"] = target[0] if target else None
    return rec


DOMAIN = r"lower(regexp_replace(%s, '^([a-z]+://)?(www\.)?([^/:]+).*$', '\3'))"  # scheme optional


def agents(conn, pk: str, cols: list[str]) -> dict:
    """Every key the viewer can see (signers and members of their collections, plus callers in their
    visible calls) with event counts by kind, call counts and a 60-minute series."""
    p = {"pk": pk, "cols": cols}
    rows = _rows(conn, f"""
        WITH vis AS {CALLS},
        ev AS (SELECT pubkey, kind, received_at FROM events WHERE collection = ANY(%(cols)s)),
        keys AS (SELECT pubkey FROM ev UNION SELECT pubkey FROM vis WHERE pubkey IS NOT NULL
                 UNION SELECT pubkey FROM members WHERE collection = ANY(%(cols)s)),
        calls AS (SELECT pubkey, count(*) AS calls, count(*) FILTER (WHERE tool = 'publish') AS writes,
                         count(*) FILTER (WHERE tool IS NOT NULL AND tool <> 'publish') AS reads,
                         count(*) FILTER (WHERE NOT ok) AS errors, max(at) AS last_call, round(avg(ms))::int AS avg_ms
                  FROM vis WHERE pubkey IS NOT NULL GROUP BY pubkey),
        recs AS (SELECT pubkey, count(*) AS records, max(received_at) AS last_record_at,
                        count(*) FILTER (WHERE kind = 4701) AS evidence, count(*) FILTER (WHERE kind = 4702) AS claims,
                        count(*) FILTER (WHERE kind = 4703) AS links, count(*) FILTER (WHERE kind = 4704) AS contradictions,
                        count(*) FILTER (WHERE kind = 4705) AS members
                 FROM ev GROUP BY pubkey)
        SELECT k.pubkey AS id, pr.name, pr.about, pr.received_at AS profile_at,
               coalesce(r.records, 0) AS records, r.last_record_at, coalesce(r.evidence, 0) AS evidence,
               coalesce(r.claims, 0) AS claims, coalesce(r.links, 0) AS links,
               coalesce(r.contradictions, 0) AS contradictions, coalesce(r.members, 0) AS members,
               coalesce(c.calls, 0) AS calls, coalesce(c.writes, 0) AS writes, coalesce(c.reads, 0) AS reads,
               coalesce(c.errors, 0) AS errors, c.last_call, c.avg_ms
        FROM keys k LEFT JOIN profiles pr USING (pubkey) LEFT JOIN calls c USING (pubkey) LEFT JOIN recs r USING (pubkey)
        ORDER BY greatest(coalesce(c.last_call, 'epoch'), coalesce(r.last_record_at, 'epoch')) DESC, 1""", p)
    per_min: dict[str, list] = {}
    for r in conn.execute(f"""SELECT pubkey, date_trunc('minute', at) AS m, count(*) AS n, count(*) FILTER (WHERE NOT ok) AS errors
                              FROM {CALLS} c WHERE at > now() - interval '60 minutes' AND pubkey IS NOT NULL
                              GROUP BY 1, 2 ORDER BY 1, 2""", p):
        per_min.setdefault(r["pubkey"], []).append(L._clean(r))
    return {"agents": rows, "per_min": per_min}


def npubs(conn, pk: str, cols: list[str]):
    """Every key known to the system with its cached profile, for admins and collection owners.
    Admins see every collection a key belongs to; an owner sees memberships in their own
    collections only, so other private collections' names never reach them."""
    if not L.is_admin(conn, pk) and conn.execute("SELECT 1 FROM collections WHERE owner = %s", (pk,)).fetchone() is None:
        return JSONResponse({"error": "admins and collection owners only"}, status_code=403)
    # Only site admins see every collection; added admins, like owners, see their own.
    admin = pk in L.ADMINS
    scope = [r["slug"] for r in conn.execute("SELECT slug FROM collections")] if admin else cols
    env = sorted(L.APPROVED | L.ADMINS)
    rows = _rows(conn, """
        WITH keys AS (SELECT pubkey FROM events UNION SELECT pubkey FROM members
                      UNION SELECT pubkey FROM approvals UNION SELECT pubkey FROM admins UNION SELECT unnest(%(env)s::text[])),
        mem AS (SELECT m.pubkey,
                       array_agg(m.collection ORDER BY m.collection) FILTER (WHERE c.owner = m.pubkey) AS owns,
                       array_agg(m.collection ORDER BY m.collection) FILTER (WHERE c.owner <> m.pubkey) AS member_of
                FROM members m JOIN collections c ON c.slug = m.collection
                WHERE m.collection = ANY(%(scope)s) GROUP BY 1),
        rec AS (SELECT pubkey, count(*) AS records, max(received_at) AS last_at FROM events
                WHERE collection = ANY(%(scope)s) AND kind BETWEEN 4701 AND 4704 GROUP BY 1)
        SELECT k.pubkey, p.name, p.about, p.picture, p.received_at AS profile_at,
               (k.pubkey = ANY(%(env)s::text[]) OR EXISTS (SELECT 1 FROM approvals a WHERE a.pubkey = k.pubkey)) AS approved,
               coalesce(mem.owns, '{}') AS owns, coalesce(mem.member_of, '{}') AS member_of,
               coalesce(rec.records, 0) AS records, rec.last_at
        FROM keys k LEFT JOIN profiles p USING (pubkey) LEFT JOIN mem USING (pubkey) LEFT JOIN rec USING (pubkey)
        ORDER BY rec.last_at DESC NULLS LAST, lower(p.name) NULLS LAST, k.pubkey""", {"env": env, "scope": scope})
    for r in rows:
        r["npub"] = E.bech32_encode("npub", r["pubkey"])
    return {"admin": admin, "npubs": rows}


SOURCE_SORTS = {
    "evidence": "evidence DESC, links DESC, source",
    "links": "links DESC, evidence DESC, source",
    "recent": "last_at DESC NULLS LAST, source",
    "name": "lower(source) NULLS LAST",
}


def sources(conn, cols: list[str], q: str = "", sort: str = "evidence", limit: int = 300) -> dict:
    """Evidence grouped by its free-text source field, plus a rollup of evidence URL domains."""
    order = SOURCE_SORTS.get(sort, SOURCE_SORTS["evidence"])
    p = {"cols": cols, "like": f"%{q}%", "limit": limit}
    rows = _rows(conn, f"""
        SELECT * FROM (
          SELECT x.source, count(*) AS evidence, max(x.received_at) AS last_at, count(DISTINCT x.pubkey) AS contributors,
                 string_agg(DISTINCT x.collection, ', ') AS collections, min({DOMAIN % 'x.url'}) AS domain,
                 (SELECT count(*) FROM links l WHERE l.from_id = ANY(array_agg(x.id))) AS links,
                 (SELECT count(DISTINCT l.to_id) FROM links l JOIN events t ON t.id = l.to_id AND t.kind = 4702
                   WHERE l.from_id = ANY(array_agg(x.id))) AS claims
          FROM evidence x WHERE x.collection = ANY(%(cols)s)
            AND (coalesce(x.source, '') ILIKE %(like)s OR coalesce(x.url, '') ILIKE %(like)s)
          GROUP BY x.source) b
        ORDER BY {order} LIMIT %(limit)s""", p)
    domains = _rows(conn, f"""
        SELECT {DOMAIN % 'x.url'} AS domain, count(*) AS evidence, count(DISTINCT x.source) AS sources,
               (SELECT count(*) FROM links l WHERE l.from_id = ANY(array_agg(x.id))) AS links
        FROM evidence x WHERE x.collection = ANY(%(cols)s) AND x.url IS NOT NULL
        GROUP BY 1 ORDER BY evidence DESC, 1 LIMIT 40""", p)
    totals = L._clean(conn.execute(f"""
        SELECT count(DISTINCT x.source) AS sources, count(*) FILTER (WHERE x.source IS NULL) AS unsourced,
               count(DISTINCT {DOMAIN % 'x.url'}) AS domains, count(*) AS evidence,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM links l WHERE l.from_id = x.id)) AS grounding
        FROM evidence x WHERE x.collection = ANY(%(cols)s)""", p).fetchone())
    return {"sources": rows, "domains": domains, "totals": totals}


def collections(conn, pk: str, cols: list[str]) -> dict:
    """The landing page: each of the viewer's collections with what it holds, who wrote it and what it weighs."""
    # ponytail: bytes are row data as stored (compressed, no indexes), summed per collection; no global DB figures.
    # Sized column by column: a whole-row pg_column_size(e.*) fetches every out-of-line (TOAST) document
    # and vector to build the row. Leaves out the tuple header and fixed-width columns, ~40 bytes a row.
    rows = _rows(conn, """
        SELECT c.slug, c.owner, coalesce((SELECT p.name FROM profiles p WHERE p.pubkey = c.owner), left(c.owner, 12)) AS owner_name,
               c.created_at, (SELECT count(*) FROM members m WHERE m.collection = c.slug) AS members,
               s.evidence, s.claims, s.links, s.contradictions, s.contributors, s.last_at, s.bytes,
               (SELECT coalesce(sum(pg_column_size(v.vector)), 0) FROM embeddings v JOIN events e ON e.id = v.event_id
                 WHERE e.collection = c.slug) AS vector_bytes
        FROM collections c, LATERAL (
          SELECT count(*) FILTER (WHERE e.kind = 4701) AS evidence, count(*) FILTER (WHERE e.kind = 4702) AS claims,
                 count(*) FILTER (WHERE e.kind = 4703) AS links, count(*) FILTER (WHERE e.kind = 4704) AS contradictions,
                 count(DISTINCT e.pubkey) AS contributors, max(e.received_at) AS last_at,
                 coalesce(sum(pg_column_size(e.id) + pg_column_size(e.pubkey) + pg_column_size(e.sig)
                              + pg_column_size(e.tags) + pg_column_size(e.content) + pg_column_size(e.collection)), 0) AS bytes
          FROM events e WHERE e.collection = c.slug) s
        WHERE c.slug = ANY(%s) ORDER BY c.created_at, c.slug""", (cols,))
    return {"collections": rows, "can_create": L.is_approved(conn, pk) or L.has_account(conn, pk) or bool(L.ledger_human(conn, pk))}


# ------------------------------------------------------------------ HTTP

PAGE_FILE = Path(__file__).with_name("ui.html")


def index(request: Request):
    if cookie_pubkey(request) is None:
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(PAGE_FILE.read_text(encoding="utf-8"))  # re-read so edits show on refresh


def _api(fn):
    """Cookie check, a pooled connection and the viewer's collections for each JSON endpoint.
    Sync handlers: Starlette runs them in its threadpool, so psycopg never blocks the event loop."""
    def handler(request: Request) -> JSONResponse:
        pk = cookie_pubkey(request)
        if pk is None:
            return JSONResponse({"error": "not logged in"}, status_code=401)
        try:
            with L.connect() as conn:
                out = fn(conn, pk, L.my_collections(conn, pk), request)
        except Exception as err:  # embedding service down, bad kind: show it on the page
            return JSONResponse({"error": str(err)[:500]}, status_code=400)
        return out if isinstance(out, JSONResponse) else JSONResponse(out)
    return handler


def _browse(conn, pk, cols, request):
    qp = request.query_params
    return browse(conn, pk, cols, qp.get("kind", "claim"), qp.get("q", "").strip(), qp.get("collection", ""),
                  qp.get("method", "keyword"), max(0, int(qp.get("page", "0") or 0)), qp.get("sort", "recent"))


def _record(conn, pk, cols, request):
    rec = record(conn, cols, request.path_params["id"])
    return rec or JSONResponse({"error": "not found"}, status_code=404)


routes = [
    Route("/dashboard", index),
    Route("/dashboard/api/snapshot", _api(lambda conn, pk, cols, r: snapshot(conn, pk, cols))),
    Route("/dashboard/api/browse", _api(_browse)),
    Route("/dashboard/api/agents", _api(lambda conn, pk, cols, r: agents(conn, pk, cols))),
    Route("/dashboard/api/npubs", _api(lambda conn, pk, cols, r: npubs(conn, pk, cols))),
    Route("/dashboard/api/sources", _api(lambda conn, pk, cols, r: sources(
        conn, cols, r.query_params.get("q", "").strip(), r.query_params.get("sort", "evidence")))),
    Route("/dashboard/api/collections", _api(lambda conn, pk, cols, r: collections(conn, pk, cols))),
    Route("/dashboard/api/record/{id}", _api(_record)),
]
