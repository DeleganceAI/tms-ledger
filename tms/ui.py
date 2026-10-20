"""Local dashboard for watching the ledger and MCP activity.

    tms-ui   ->  http://127.0.0.1:8780

Read-only, localhost only, no auth: never put it behind the tunnel. Polls the
database every two seconds; the server's `mcp_calls` table supplies call stats.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from . import ledger as L

COUNTS_SQL = """SELECT
  (SELECT count(*) FROM collections) AS collections, (SELECT count(*) FROM authors) AS authors,
  (SELECT count(*) FROM sources) AS sources, (SELECT count(*) FROM observations) AS observations,
  (SELECT count(*) FROM claims) AS claims, (SELECT count(*) FROM evidence) AS evidence,
  (SELECT count(*) FROM contradictions) AS contradictions"""

RECENT_SQL = """SELECT kind, id, collection_id, author_id, asserted_at, summary FROM (
  SELECT 'observation' AS kind, id, collection_id, author_id, asserted_at, coalesce(title, left(uri, 160)) AS summary FROM observations
  UNION ALL SELECT 'claim', id, collection_id, author_id, asserted_at, left(text, 240) FROM claims
  UNION ALL SELECT 'evidence', id, NULL, author_id, asserted_at,
    relation || ' ' || target_kind || ' ' || coalesce(target_claim_id, target_contradiction_id, target_evidence_id,
                                                      target_source_id, target_observation_id)
    || ' · ' || left(quote, 160) FROM evidence
  UNION ALL SELECT 'contradiction', id, collection_id, author_id, asserted_at, left(reason, 240) FROM contradictions
  UNION ALL SELECT 'source', id, NULL, author_id, asserted_at, name FROM sources
  UNION ALL SELECT 'collection', id, id, author_id, asserted_at, name FROM collections
  UNION ALL SELECT 'author', id, NULL, id, asserted_at, name || ' (' || kind || ')' FROM authors
) r ORDER BY asserted_at DESC, id LIMIT %s"""

RECORDS_PER_MIN_SQL = """SELECT date_trunc('minute', asserted_at) AS m, count(*) AS n FROM (
  SELECT asserted_at FROM observations UNION ALL SELECT asserted_at FROM claims
  UNION ALL SELECT asserted_at FROM evidence UNION ALL SELECT asserted_at FROM contradictions
  UNION ALL SELECT asserted_at FROM sources) r
  WHERE asserted_at > now() - interval '60 minutes' GROUP BY 1 ORDER BY 1"""


def snapshot(conn, limit: int = 100) -> dict:
    rows = lambda sql, *params: [L._clean(r) for r in conn.execute(sql, params or None)]
    return {
        "now": datetime.now(UTC).isoformat(),
        "counts": L._clean(conn.execute(COUNTS_SQL).fetchone()),
        "collections": rows("""SELECT c.id, c.name,
              (SELECT count(*) FROM observations o WHERE o.collection_id = c.id) AS observations,
              (SELECT count(*) FROM claims k WHERE k.collection_id = c.id) AS claims,
              (SELECT count(*) FROM contradictions x WHERE x.collection_id = c.id) AS contradictions
            FROM collections c ORDER BY c.asserted_at, c.id"""),
        "calls": L._clean(conn.execute("""SELECT count(*) AS total, count(*) FILTER (WHERE NOT ok) AS errors,
              count(*) FILTER (WHERE at > now() - interval '1 hour') AS last_hour,
              count(*) FILTER (WHERE at > now() - interval '5 minutes') AS last_5m,
              count(*) FILTER (WHERE tool LIKE 'add_%') AS writes,
              count(DISTINCT author_id) FILTER (WHERE at > now() - interval '5 minutes') AS active_authors
            FROM mcp_calls""").fetchone()),
        "calls_per_min": rows("""SELECT date_trunc('minute', at) AS m, count(*) AS n, count(*) FILTER (WHERE NOT ok) AS errors
            FROM mcp_calls WHERE at > now() - interval '60 minutes' GROUP BY 1 ORDER BY 1"""),
        "records_per_min": rows(RECORDS_PER_MIN_SQL),
        "by_tool": rows("""SELECT coalesce(tool, method) AS name, count(*) AS n, count(*) FILTER (WHERE NOT ok) AS errors,
              round(avg(ms))::int AS avg_ms FROM mcp_calls GROUP BY 1 ORDER BY n DESC, 1"""),
        "by_author": rows("""SELECT coalesce(author_id, '—') AS author_id, count(*) AS n,
              count(*) FILTER (WHERE tool LIKE 'add_%') AS writes, count(*) FILTER (WHERE NOT ok) AS errors, max(at) AS last_at
            FROM mcp_calls GROUP BY 1 ORDER BY max(at) DESC"""),
        "recent_calls": rows("""SELECT id, at, method, tool, author_id, collection, ok, left(error, 240) AS error, ms
            FROM mcp_calls ORDER BY at DESC, id DESC LIMIT %s""", limit),
        "recent_records": rows(RECENT_SQL, limit),
    }


CLAIM_COUNTS, SORTS = L.CLAIM_COUNTS, L.CLAIM_SORTS

# kind -> (table, columns for the list, expression a text filter applies to)
BROWSE = {
    "observation": ("observations", "id, collection_id, author_id, asserted_at, coalesce(title, uri) AS summary",
                    "coalesce(title, '') || ' ' || uri || ' ' || coalesce(content, '')"),
    "claim": ("claims", "id, collection_id, author_id, asserted_at, text AS summary, " + CLAIM_COUNTS, "text"),
    "contradiction": ("contradictions", "id, collection_id, author_id, asserted_at, reason AS summary", "reason"),
    "evidence": ("evidence", "id, NULL::text AS collection_id, author_id, asserted_at, "
                 "relation || ' ' || target_kind || ' · ' || left(quote, 200) AS summary", "quote || ' ' || reason"),
    "source": ("sources", "id, NULL::text AS collection_id, author_id, asserted_at, name || coalesce(' · ' || uri, '') AS summary",
               "name || ' ' || coalesce(uri, '')"),
    "author": ("authors", "id, NULL::text AS collection_id, id AS author_id, asserted_at, name || ' (' || kind || ')' AS summary",
               "id || ' ' || name"),
}


def browse(conn, kind: str, q: str, collection: str, method: str, page: int, sort: str = "recent", size: int = 50) -> dict:
    if kind not in BROWSE:
        raise ValueError(f"kind must be one of {sorted(BROWSE)}")
    table, cols, searchable = BROWSE[kind]
    if method == "vector" and kind == "claim" and q:
        vec = L.embed(q, query=True)
        extra, params = ("AND collection_id = %s", [collection]) if collection else ("", [])
        items = [L._clean(r) for r in conn.execute(
            f"""SELECT id, collection_id, author_id, asserted_at, text AS summary, {CLAIM_COUNTS},
                       round((embedding <=> %s::vector)::numeric, 3)::float8 AS distance
                FROM claims WHERE embedding IS NOT NULL {extra}
                ORDER BY embedding <=> %s::vector, id LIMIT %s""", (vec, *params, vec, size))]
        return {"items": items, "more": False, "method": "vector"}
    where, params = [], []
    if collection and kind in ("observation", "claim", "contradiction"):
        where.append("collection_id = %s")
        params.append(collection)
    if q:
        where.append(f"({searchable}) ILIKE %s")
        params.append(f"%{q}%")
    order = SORTS.get(sort, SORTS["recent"]) if kind == "claim" else SORTS["recent"]
    sql = f"SELECT * FROM (SELECT {cols} FROM {table}" + (" WHERE " + " AND ".join(where) if where else "") \
        + f") b ORDER BY {order} LIMIT %s OFFSET %s"
    items = [L._clean(r) for r in conn.execute(sql, (*params, size + 1, page * size))]
    return {"items": items[:size], "more": len(items) > size, "method": "keyword"}


def record(conn, kind: str, id: str) -> dict | None:
    """One record plus the records it links to, for the drawer."""
    rec = L.get_record(conn, kind, id, max_chars=6000)
    if rec is None:
        return None
    if kind == "claim":
        rec["evidence"] = L.get_evidence(conn, "claim", id)
        rec["contradictions"] = L.search_contradictions(conn, rec["collection_id"], claim_id=id)
    elif kind == "contradiction":
        rec["evidence"] = L.get_evidence(conn, "contradiction", id)
        rec["claims"] = [L._clean(r) for r in conn.execute(
            "SELECT id, text, author_id FROM claims WHERE id = ANY(%s) ORDER BY id", (rec["claim_ids"],))]
    elif kind == "observation":
        rec["evidence_from"] = L.get_evidence(conn, from_observation_id=id)
    elif kind == "evidence":
        rec["observation"] = L.get_record(conn, "observation", rec["from_observation_id"], max_chars=0)
        rec["target"] = L.get_record(conn, rec["target_kind"], rec["target_id"], max_chars=0)
    elif kind == "source":
        rec["observations"] = [L._clean(r) for r in conn.execute(
            "SELECT id, title, uri, collection_id, asserted_at FROM observations WHERE source_id = %s ORDER BY asserted_at DESC LIMIT 200", (id,))]
    elif kind == "author":
        rec["recent"] = [L._clean(r) for r in conn.execute(
            RECENT_SQL.replace(") r ORDER BY", ") r WHERE author_id = %s ORDER BY"), (id, 100))]
    return rec


async def index(request) -> HTMLResponse:
    return HTMLResponse(PAGE)


async def api_snapshot(request) -> JSONResponse:
    with L.connect() as conn:  # ponytail: sync psycopg on the event loop; one local viewer
        return JSONResponse(snapshot(conn))


async def api_browse(request) -> JSONResponse:
    qp = request.query_params
    try:
        page = max(0, int(qp.get("page", "0") or 0))
        with L.connect() as conn:
            return JSONResponse(browse(conn, qp.get("kind", "claim"), qp.get("q", "").strip(),
                                       qp.get("collection", ""), qp.get("method", "keyword"), page, qp.get("sort", "recent")))
    except Exception as err:  # Ollama down, bad kind: show it on the page
        return JSONResponse({"error": str(err)}, status_code=400)


async def api_record(request) -> JSONResponse:
    kind, id = request.path_params["kind"], request.path_params["id"]
    with L.connect() as conn:
        try:
            rec = record(conn, kind, id)
        except ValueError as err:
            return JSONResponse({"error": str(err)}, status_code=400)
    return JSONResponse(rec or {"error": "not found"}, status_code=200 if rec else 404)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/snapshot", api_snapshot),
    Route("/api/browse", api_browse),
    Route("/api/record/{kind}/{id}", api_record),
])


PAGE = (Path(__file__).with_name("ui.html")).read_text(encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8780)
    a = p.parse_args()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
