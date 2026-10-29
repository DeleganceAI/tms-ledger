"""/office.json: anonymous, hourly data for the office animation (OFFICE.md sections 2 and 4).
/stats.json: the six global counts for the ticker, at most a minute old.
/showcase.json: collections their owners chose to show: name, topic and record counts only.

Anonymous by construction. The output holds only counts, buckets, node kinds, local indices,
relation letters, and seconds-into-the-hour. No slugs, pubkeys, record ids, text or timestamps.
Board and slice ids are random every hour, and the boards are shuffled.
"""
from __future__ import annotations

import gzip
import json
import random
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import ledger as L

MIN_RECORDS = 10       # a smaller collection counts toward totals but gets no board
SLICE_NODES = 40       # cards plus papers on one board
BRANCH = 6             # nodes taken from any one node, so a hub can't fill a slice
IDLE_SLICES = 3        # per board, rooted at its most recently active claims
MAX_REPLAY = 200       # events from the previous hour
MAX_OFF_EDGE = 6       # strings drawn running off the board from one node
REL = {"SUPPORTS": "S", "REBUTS": "R", "QUALIFIES": "Q"}
# contributors: pubkeys that have published at least one record, human or agent
TOTALS_SQL = """SELECT
  (SELECT count(*) FROM events WHERE kind = 4701) AS evidence,
  (SELECT count(*) FROM events WHERE kind = 4702) AS claims,
  (SELECT count(*) FROM events WHERE kind = 4703) AS links,
  (SELECT count(*) FROM events WHERE kind = 4704) AS contradictions,
  (SELECT count(*) FROM collections) AS collections,
  (SELECT count(DISTINCT pubkey) FROM events WHERE kind IN (4701, 4702, 4703, 4704)) AS contributors"""


def confusion(claims: int, contradictions: int) -> int:
    """0-4 floating question marks: a bucket of contradictions per claim, never the raw number."""
    if not claims or not contradictions:
        return 0
    r = contradictions / claims
    return 1 if r < .05 else 2 if r < .15 else 3 if r < .3 else 4


class Graph:
    """One collection: claims and evidence are nodes; links and contradictions join them."""

    def __init__(self, nodes: dict, links: list, contradictions: list):
        self.kind = nodes  # id -> "claim" | "evidence"
        self.adj: dict[str, list] = {}  # id -> [(neighbour, relation letter, this node is the link's from)]
        for f, t, rel in links:
            if f in nodes and t in nodes:  # links to links or contradictions (disputes) aren't drawn
                self.adj.setdefault(f, []).append((t, rel, True))
                self.adj.setdefault(t, []).append((f, rel, False))
        self.groups = [[c for c in g if c in nodes] for g in contradictions]
        self.groups_of: dict[str, list[int]] = {}
        for gi, g in enumerate(self.groups):
            for c in g:
                self.groups_of.setdefault(c, []).append(gi)

    def neighbours(self, n: str) -> list[str]:
        return [m for m, _, _ in self.adj.get(n, ())] + [
            m for gi in self.groups_of.get(n, ()) for m in self.groups[gi] if m != n]

    def slice(self, roots: list[str], rng: random.Random) -> tuple[dict, dict]:
        """Breadth-first from the roots to about SLICE_NODES nodes, at most BRANCH per node.
        Returns the slice and a map from record id to local index (kept server-side only)."""
        order: list[str] = []
        for r in roots:
            if r in self.kind and r not in order and len(order) < SLICE_NODES:
                order.append(r)
        seen, q = set(order), deque(order)
        while q and len(order) < SLICE_NODES:
            n = q.popleft()
            nbrs = self.neighbours(n)
            rng.shuffle(nbrs)
            taken = 0
            for m in nbrs:
                if taken >= BRANCH or len(order) >= SLICE_NODES:
                    break
                if m not in seen:
                    seen.add(m)
                    order.append(m)
                    q.append(m)
                    taken += 1
        idx = {n: i for i, n in enumerate(order)}
        edges, off = [], []
        for n in order:
            outside = 0
            for m, rel, is_from in self.adj.get(n, ()):
                if m not in idx:
                    outside += 1
                elif is_from:
                    edges.append([idx[n], idx[m], rel])
            if outside:
                off.append([idx[n], min(outside, MAX_OFF_EDGE)])
        contras = []
        for gi in sorted({gi for n in order for gi in self.groups_of.get(n, ())}):
            members = [idx[c] for c in self.groups[gi] if c in idx]
            if len(members) >= 2:
                contras.append(members)
        return ({"id": "s_" + secrets.token_hex(4), "nodes": [{"i": i, "t": self.kind[n]} for i, n in enumerate(order)],
                 "edges": edges, "contradictions": contras, "off_edge": off}, idx)


def compute(conn, now: datetime | None = None) -> dict:
    """The payload for the hour containing `now`. Replay covers the hour before it."""
    now = now or datetime.now(UTC)
    hour = now.replace(minute=0, second=0, microsecond=0)
    start = hour - timedelta(hours=1)
    rng = random.Random(secrets.randbits(64))
    totals = conn.execute(TOTALS_SQL).fetchone()
    sizes = conn.execute("""SELECT collection, count(*) AS n FROM events
                            WHERE kind IN (4701, 4702, 4703, 4704) GROUP BY collection""").fetchall()
    boards, replay = [], []
    # ponytail: loads every node and link id of each eligible collection once an hour; move the
    # breadth-first walk into SQL when a collection reaches millions of links.
    for row in sizes:
        if row["n"] < MIN_RECORDS:
            continue
        col = row["collection"]
        nodes, recent, added = {}, {}, []
        for r in conn.execute("""SELECT id, kind, received_at FROM events
                                 WHERE collection = %s AND kind IN (4701, 4702)""", (col,)):
            nodes[r["id"]] = "claim" if r["kind"] == 4702 else "evidence"
            if r["kind"] == 4702:
                recent[r["id"]] = r["received_at"]
            if start <= r["received_at"] < hour:
                added.append((r["received_at"], nodes[r["id"]], [r["id"]], None))
        links = []
        for r in conn.execute("SELECT from_id, to_id, relation, received_at FROM links WHERE collection = %s", (col,)):
            rel = REL.get(r["relation"])
            if rel is None:  # an unknown relation never takes the office down
                continue
            links.append((r["from_id"], r["to_id"], rel))
            if r["to_id"] in recent:
                recent[r["to_id"]] = max(recent[r["to_id"]], r["received_at"])
            if start <= r["received_at"] < hour:
                added.append((r["received_at"], "link", [r["from_id"], r["to_id"]], rel))
        groups = []
        for r in conn.execute("SELECT claim_ids, received_at FROM contradictions WHERE collection = %s", (col,)):
            groups.append(r["claim_ids"])
            if start <= r["received_at"] < hour:
                added.append((r["received_at"], "contradiction", list(r["claim_ids"]), None))
        g = Graph(nodes, links, groups)
        roots = sorted(recent, key=recent.get, reverse=True)[:IDLE_SLICES] or list(nodes)[:1]
        board = {"id": "b_" + secrets.token_hex(4), "confusion": confusion(len(recent), len(groups)),
                 "slices": [g.slice([r], rng)[0] for r in roots]}
        boards.append(board)
        for at, kind, ids, rel in added:
            replay.append((at, board, g, kind, ids, rel))
    rng.shuffle(boards)

    replay.sort(key=lambda x: x[0])
    if len(replay) > MAX_REPLAY:  # keep the hour's shape: an even sample, in order
        replay = [replay[round(i * (len(replay) - 1) / (MAX_REPLAY - 1))] for i in range(MAX_REPLAY)]
    events = []
    for at, board, g, kind, ids, rel in replay:
        sl, idx = g.slice(ids, rng)
        if ids[0] not in idx:
            continue
        ev = {"board": board["id"], "slice": sl["id"], "kind": kind, "node": idx[ids[0]],
              "claims": 0, "t": int((at - start).total_seconds())}
        if kind == "link":
            ev["relation"] = rel
            ev["to"] = idx.get(ids[1])  # None when the link disputes a link or contradiction
        if kind == "contradiction":
            ev["claims"] = len(ids)
            ev["c"] = next((i for i, m in enumerate(sl["contradictions"]) if idx[ids[0]] in m), None)
        board["slices"].append(sl)
        events.append(ev)
    return {"generated_at": hour.isoformat().replace("+00:00", "Z"), "totals": dict(totals),
            "boards": boards, "replay": events}


_cache: dict = {}
_lock = threading.Lock()


def cached() -> tuple[bytes, bytes]:
    """Recomputed once per hour, on the first request after the hour turns. Kept as JSON bytes
    and their gzip, so a few hundred replay slices cost one compression an hour."""
    hour = int(time.time() // 3600)
    with _lock:
        if _cache.get("hour") != hour:
            with L.connect() as conn:
                body = json.dumps(compute(conn), separators=(",", ":")).encode()
            _cache.update(hour=hour, body=body, gz=gzip.compress(body, 6))
        return _cache["body"], _cache["gz"]


async def office_json(request) -> Response:
    body, gz = await run_in_threadpool(cached)
    headers = {"Cache-Control": "public, max-age=300", "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gz, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(body, media_type="application/json", headers=headers)


_stats: dict = {}
_stats_lock = threading.Lock()


def stats() -> dict:
    """The six global counts for the ticker, at most a minute old."""
    # ponytail: six count(*) scans once a minute; keep a counters table updated by publish
    # when events reach the millions.
    minute = int(time.time() // 60)
    with _stats_lock:
        if _stats.get("minute") != minute:
            with L.connect() as conn:
                _stats.update(minute=minute, body=dict(conn.execute(TOTALS_SQL).fetchone()))
        return _stats["body"]


async def stats_json(request) -> JSONResponse:
    return JSONResponse(await run_in_threadpool(stats), headers={"Cache-Control": "public, max-age=60"})


_showcase: dict = {}
_shapes: dict = {}


def shape(conn, slug: str) -> dict:
    """A public collection's board as the office draws it: one slice from its most recent claims,
    node kinds, local indices, relation letters and contradiction groups only. Anonymous like
    /office.json: no ids, text, keys or times."""
    nodes, recent, links, groups = {}, {}, [], []
    for r in conn.execute("SELECT id, kind, received_at FROM events WHERE collection = %s AND kind IN (4701, 4702)", (slug,)):
        nodes[r["id"]] = "claim" if r["kind"] == 4702 else "evidence"
        if r["kind"] == 4702:
            recent[r["id"]] = r["received_at"]
    for r in conn.execute("SELECT from_id, to_id, relation FROM links WHERE collection = %s", (slug,)):
        if r["relation"] in REL:
            links.append((r["from_id"], r["to_id"], REL[r["relation"]]))
    for r in conn.execute("SELECT claim_ids FROM contradictions WHERE collection = %s", (slug,)):
        groups.append(r["claim_ids"])
    # Start from the best-connected claims (the newest claim often has no links yet, which drew a
    # single pin), then fill the board from the rest, best-connected first, up to SLICE_NODES.
    g, rng = Graph(nodes, links, groups), random.Random(slug)
    ranked = sorted(nodes, key=lambda n: (len(g.neighbours(n)), nodes[n] == "claim", recent[n].timestamp() if n in recent else 0), reverse=True)
    sl, idx = g.slice(ranked[:2], rng)
    if len(idx) < SLICE_NODES:
        sl, _ = g.slice(list(idx) + [n for n in ranked if n not in idx], rng)
    return {k: sl[k] for k in ("nodes", "edges", "contradictions")}


_showcase_lock = threading.Lock()


def _refresh_showcase() -> None:
    """Recompute the public collections and their outlines (outlines every six hours: they read
    every node and link of the collection, seconds for a big one)."""
    minute, period = int(time.time() // 60), int(time.time() // (6 * 3600))
    try:
        with L.connect() as conn:
            rows = L.showcase(conn)
            for r in rows:
                key = (r["slug"], period)
                if key not in _shapes:
                    _shapes[key] = shape(conn, r["slug"])
                r["shape"] = _shapes[key]
        for k in [k for k in _shapes if k[1] != period]:
            del _shapes[k]
        _showcase.update(minute=minute, body=rows)
    finally:
        _showcase.pop("refreshing", None)


def showcase() -> list[dict]:
    """Collections their owners made public, at most about a minute old. Only the first request
    after a start waits; after that a stale minute is served at once and refreshed in a thread,
    so nobody waits on the query, and it never holds the ticker's lock."""
    with _showcase_lock:
        if "body" not in _showcase:
            _showcase["refreshing"] = True
            _refresh_showcase()
        elif _showcase["minute"] != int(time.time() // 60) and not _showcase.get("refreshing"):
            _showcase["refreshing"] = True
            threading.Thread(target=_refresh_showcase, daemon=True).start()
        return _showcase["body"]


async def showcase_json(request) -> JSONResponse:
    return JSONResponse({"collections": await run_in_threadpool(showcase)}, headers={"Cache-Control": "no-cache"})


routes = [Route("/office.json", office_json), Route("/stats.json", stats_json), Route("/showcase.json", showcase_json)]
