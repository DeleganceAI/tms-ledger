"""End-to-end check of the signed-event ledger against a scratch Postgres.

    TMS_SMOKE_URL=postgresql://tmsv2:tmsv2@localhost:5432/tmsv2_smoke uv run python test_smoke.py

Drops and recreates that database (its name must end in _smoke), applies db/init.sql, and runs
every PLAN.md test. Embeddings are faked with a bag of words, so no model is needed.
"""
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

import psycopg

URL = os.environ.get("TMS_SMOKE_URL", "postgresql://tmsv2:tmsv2@localhost:5432/tmsv2_smoke")
NAME = URL.rsplit("/", 1)[1]
assert NAME.endswith("_smoke"), f"refusing to drop {NAME}: the smoke database name must end in _smoke"
os.environ["DATABASE_URL"] = URL
OWNER, BOB, OUTSIDER, STRANGER, SERVER = (hashlib.sha256(n.encode()).hexdigest() for n in
                                          ("owner", "bob", "outsider", "stranger", "server"))
os.environ["TMS_SERVER_NSEC"] = SERVER
os.environ["TMS_SECRET"] = "smoke-cookie-secret"

from tms import events as E  # noqa: E402
from tms import ledger as L  # noqa: E402

PK = {k: E.pubkey_of(k) for k in (OWNER, BOB, OUTSIDER, STRANGER, SERVER)}
L.APPROVED = {PK[OWNER], PK[OUTSIDER]}

DOC = """Histamine intolerance (HIT) is thought to result from reduced diamine oxidase (DAO) activity.
Serum DAO activity correlates poorly with symptom severity in several cohorts.
In one 2019 trial, DAO supplementation reduced symptom scores in adults with low serum DAO."""


REAL_EMBED = L.embed


def fake_embed(texts, query=False, pubkey=None, collection=None, conn=None):
    out = []
    for t in texts:
        v = [0.0] * L.EMBED_DIM
        for w in re.findall(r"[a-z]+", t.lower().replace(L.QUERY_PREFIX.lower(), "")):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % L.EMBED_DIM] += 1.0
        out.append("[" + ",".join(map(str, v)) + "]")
    return out


L.embed = fake_embed


def recreate() -> None:
    with psycopg.connect(URL.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{NAME}"')
        c.execute(f'CREATE DATABASE "{NAME}"')
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(Path(__file__).with_name("db").joinpath("init.sql").read_text())


def sign(sk, kind, content, **kw):
    return E.sign(sk, kind, content, **kw)


def terms(sk):
    return sign(sk, E.TERMS, L.TERMS)


def rejects(fn, needle):
    try:
        fn()
    except (ValueError, psycopg.Error) as err:
        assert needle in str(err), (needle, str(err))
    else:
        raise AssertionError(f"accepted, expected rejection: {needle}")


def no_db_on_event_loop(root: Path = Path(__file__).parent / "tms") -> None:
    """Async handlers reach the pool only from a worker thread (web.db): a checkout on the event loop
    waits up to 30 s when the pool is full, and every request, MCP included, waits with it.
    ponytail: lexical, so it misses a sync helper that connects, called straight from an async def."""
    import ast

    def walk(path, node, in_async):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                walk(path, child, isinstance(child, ast.AsyncFunctionDef))
                continue
            f = getattr(child, "func", None)
            assert not (in_async and getattr(f, "attr", getattr(f, "id", None)) == "connect"), \
                f"{path}:{child.lineno}: connect() inside an async def; use web.db or run_in_threadpool"
            walk(path, child, in_async)
    for path in sorted(root.glob("*.py")):
        walk(path, ast.parse(path.read_text()), False)


def apply_sql(url: str, name: str) -> None:
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(Path(__file__).with_name("db").joinpath(name).read_text())


def assert_fresh_migration(url: str) -> None:
    """migrate_embedding_index.sql on a database created from init.sql is a no-op."""
    apply_sql(url, "migrate_embedding_index.sql")
    with psycopg.connect(url, autocommit=True) as c:
        assert c.execute("SELECT to_regclass('public.embeddings') IS NOT NULL").fetchone()[0] is False
        assert c.execute("SELECT to_regclass('public.embedding_index') IS NOT NULL").fetchone()[0] is True


def legacy_migration() -> None:
    """A database that still has embeddings keeps every vector and every event byte."""
    name = "tmsv2_migrate_smoke"
    assert name.endswith("_smoke")
    admin = URL.rsplit("/", 1)[0] + "/postgres"
    url = URL.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}"')
    try:
        apply_sql(url, "init.sql")
        owner, eid = "ab" * 32, "cd" * 32
        content = '{"collection": "mig", "text": "migrated claim"}'
        sig = "0" * 128
        vec = "[" + ",".join(["1"] + ["0"] * 4095) + "]"
        with psycopg.connect(url, autocommit=True) as c:
            c.execute("DROP TABLE embedding_index")
            c.execute("""CREATE TABLE embeddings (
                event_id text PRIMARY KEY REFERENCES events(id),
                vector vector(4096) NOT NULL,
                model text NOT NULL)""")
            c.execute("INSERT INTO collections (slug, owner) VALUES ('mig', %s)", (owner,))
            c.execute("""INSERT INTO events (id, pubkey, created_at, kind, content, sig, collection)
                         VALUES (%s, %s, 1792454400, 4702, %s, %s, 'mig')""", (eid, owner, content, sig))
            c.execute("INSERT INTO embeddings (event_id, vector, model) VALUES (%s, %s::vector, %s)",
                      (eid, vec, "Qwen/Qwen3-Embedding-8B"))
            before = c.execute("SELECT content, sig FROM events WHERE id = %s", (eid,)).fetchone()
        apply_sql(url, "migrate_embedding_index.sql")
        with psycopg.connect(url, autocommit=True) as c:
            assert c.execute("SELECT to_regclass('public.embeddings') IS NOT NULL").fetchone()[0] is False
            row = c.execute("""SELECT model, dimensions, vector_dims(vector) AS d
                               FROM embedding_index WHERE event_id = %s""", (eid,)).fetchone()
            assert row == ("Qwen/Qwen3-Embedding-8B", 4096, 4096), row
            assert c.execute("SELECT content, sig FROM events WHERE id = %s", (eid,)).fetchone() == before
        apply_sql(url, "migrate_embedding_index.sql")
        with psycopg.connect(url, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM embedding_index").fetchone()[0] == 1
            assert c.execute("SELECT content FROM events WHERE id = %s", (eid,)).fetchone()[0] == content
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def main() -> None:
    no_db_on_event_loop()
    recreate()
    assert_fresh_migration(URL)
    with L.connect() as conn:
        ids = ledger(conn)
    legacy_migration()
    embed_calls()
    server(ids)
    print("PASS: smoke")


def ledger(conn) -> list[str]:
    pub = lambda evs: L.publish(conn, evs)  # noqa: E731
    count = lambda: conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"]  # noqa: E731

    # A write from a key that hasn't signed the terms is rejected.
    pub([sign(OWNER, E.PROFILE, {"name": "Owner", "about": "human"})])
    rejects(lambda: pub([sign(OWNER, E.CLAIM, {"collection": "smoke", "text": "too early"})]), "sign the current terms")
    rejects(lambda: pub([sign(OWNER, E.TERMS, {**L.TERMS, "version": "0"})]), "terms must be version")

    # A signed batch is accepted: terms, evidence, claims and the links between them.
    doc = sign(OWNER, E.EVIDENCE, {"collection": "smoke", "text": DOC, "title": "HIT review",
                                   "url": "https://example.org/hit", "source": "Example journal"})
    c1 = sign(OWNER, E.CLAIM, {"collection": "smoke", "text": "Histamine intolerance results from reduced DAO activity."})
    c2 = sign(OWNER, E.CLAIM, {"collection": "smoke", "text": "Serum DAO activity correlates poorly with symptom severity."})
    l1 = sign(OWNER, E.LINK, {"collection": "smoke", "from": doc["id"], "to": c1["id"], "relation": "SUPPORTS",
                              "quote": "thought to result from reduced diamine oxidase (DAO) activity",
                              "reason": "The review names reduced DAO activity as the proposed mechanism."})
    q1 = sign(OWNER, E.LINK, {"collection": "smoke", "from": doc["id"], "to": c1["id"], "relation": "QUALIFIES",
                              "quote": "correlates  poorly with symptom severity", "reason": "DAO alone does not track symptoms."})
    k1 = sign(OWNER, E.CONTRADICTION, {"collection": "smoke", "claims": [c1["id"], c2["id"]],
                                       "reason": "If DAO activity caused HIT, serum DAO should track symptoms."})
    batch = [terms(OWNER), doc, c1, c2, l1, q1, k1]
    res = pub(batch)
    assert res["accepted"] == [e["id"] for e in batch] and res["embedded"] == 2 and res["collections"] == ["smoke"], res
    assert conn.execute("SELECT owner FROM collections WHERE slug = 'smoke'").fetchone()["owner"] == PK[OWNER]
    stored = dict(conn.execute(
        "SELECT model, dimensions FROM embedding_index WHERE event_id = %s", (c1["id"],)).fetchone())
    assert stored == {"model": L.EMBED_MODEL, "dimensions": L.EMBED_DIM}, stored
    assert conn.execute("""SELECT count(*) AS n FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name IN ('events', 'collections')
          AND column_name IN ('embedding', 'embeddings', 'vector')""").fetchone()["n"] == 0

    # A duplicate ID is a no-op.
    n = count()
    assert pub(batch)["skipped"] == [e["id"] for e in batch] and count() == n

    # A bad quote rolls back the whole batch.
    c3 = sign(OWNER, E.CLAIM, {"collection": "smoke", "text": "DAO deficiency causes every case of HIT."})
    bad = sign(OWNER, E.LINK, {"collection": "smoke", "from": doc["id"], "to": c3["id"], "relation": "SUPPORTS",
                               "quote": "DAO deficiency causes every case", "reason": "Invented."})
    rejects(lambda: pub([c3, bad]), "quote not found verbatim")
    assert count() == n and L.get_event(conn, PK[OWNER], c3["id"]) is None

    # A tampered signature is rejected.
    forged = dict(c3, sig=c3["sig"][:-2] + ("00" if not c3["sig"].endswith("00") else "11"))
    rejects(lambda: pub([forged]), "signature does not verify")
    rejects(lambda: pub([dict(c3, content=c3["content"].replace("every", "any"))]), "id does not match")

    # References stay inside one collection; QUALIFIES only targets claims.
    o1 = sign(OWNER, E.CLAIM, {"collection": "other", "text": "An unrelated claim in another collection."})
    pub([o1])
    rejects(lambda: pub([sign(OWNER, E.CONTRADICTION, {"collection": "smoke", "claims": [c1["id"], o1["id"]],
                                                       "reason": "two collections"})]), "is not a claim in collection")
    rejects(lambda: pub([sign(OWNER, E.LINK, {"collection": "smoke", "from": doc["id"], "to": k1["id"],
                                              "relation": "QUALIFIES", "quote": "DAO", "reason": "r"})]),
            "QUALIFIES may only target a claim")

    # Requests are never published; snapshots come only from the server key.
    rejects(lambda: pub([E.request(OWNER, "list_collections")]), "never published")
    snap = {"date": "2026-10-20", "cid": "bafy", "sha256": "0" * 64, "count": 1, "last_received_at": "2026-10-20T00:00:00Z"}
    rejects(lambda: pub([sign(OWNER, E.SNAPSHOT, snap)]), "snapshots are signed by the server")
    rejects(lambda: pub([sign(SERVER, E.CLAIM, {"collection": "smoke", "text": "server claim"})]), "nothing else is")
    assert pub([sign(SERVER, E.SNAPSHOT, snap)])["accepted"]

    # A non-member write is rejected, even from an approved key; approved keys may create collections.
    pub([terms(OUTSIDER)])
    rejects(lambda: pub([sign(OUTSIDER, E.CLAIM, {"collection": "smoke", "text": "intrusion"})]), "not a member of collection 'smoke'")
    pub([sign(OUTSIDER, E.CLAIM, {"collection": "outside", "text": "my own collection"})])
    rejects(lambda: L.list_claims(conn, PK[OUTSIDER], "smoke"), "not a member")
    assert L.get_event(conn, PK[OUTSIDER], c1["id"]) is None
    assert [c["slug"] for c in L.list_collections(conn, PK[OUTSIDER])] == ["outside"]

    # An unapproved non-member gets nothing.
    rejects(lambda: pub([sign(STRANGER, E.PROFILE, {"name": "Stranger"})]), "is not approved")
    rejects(lambda: pub([terms(STRANGER)]), "is not approved")
    assert not L.allowed(conn, PK[STRANGER]) and L.list_collections(conn, PK[STRANGER]) == []

    # A member added by an owner gets in without approval, but cannot create collections or change members.
    rejects(lambda: pub([terms(BOB)]), "is not approved")
    rejects(lambda: pub([sign(OUTSIDER, E.MEMBERS, {"collection": "smoke", "members": [PK[OUTSIDER]]})]), "not a member")
    pub([sign(OWNER, E.MEMBERS, {"collection": "smoke", "members": [PK[BOB]]})])
    tagged = sign(BOB, E.PROFILE, '{"name":"Bob","about":"agent"}', tags=[["client", "Some Nostr app"], ["alt", "profile"]])
    pub([terms(BOB), tagged])
    rejects(lambda: pub([sign(BOB, E.CLAIM, {"collection": "smoke", "text": "tagged"}, tags=[["t", "x"]])]),
            "only profiles may carry tags")
    # A tagged profile is stored verbatim, so the stored copy still verifies.
    row = conn.execute("SELECT id, pubkey, created_at, kind, tags, content, sig FROM events WHERE id = %s",
                       (tagged["id"],)).fetchone()
    assert dict(row) == tagged and E.verify(dict(row))["name"] == "Bob"
    b1 = sign(BOB, E.CLAIM, {"collection": "smoke", "text": "Bob adds a claim about DAO supplementation."})
    pub([b1])
    rejects(lambda: pub([sign(BOB, E.CLAIM, {"collection": "bobs", "text": "new collection"})]), "only approved pubkeys create")
    rejects(lambda: pub([sign(BOB, E.MEMBERS, {"collection": "smoke", "members": []})]), "only the owner")
    mine = L.list_collections(conn, PK[BOB])
    assert [c["slug"] for c in mine] == ["smoke"] and set(mine[0]["members"]) == {PK[OWNER], PK[BOB]}, mine

    # Reads, scoped to the caller's collections.
    hits = L.search_claims(conn, PK[BOB], "smoke", "what causes histamine intolerance?", "vector", 5)
    assert hits["items"][0]["id"] == c1["id"], hits
    assert {e["id"] for e in hits["items"][0]["links"]} == {l1["id"], q1["id"]}
    assert hits["items"][0]["contradiction_ids"] == [k1["id"]] and hits["items"][0]["author"] == "Owner"
    assert hits["items"][0]["author_model"] is None  # the author's profile has no model yet
    # A vector from another model, even an identical or shorter one, is not ranked with these.
    query = L.embed(["what causes histamine intolerance?"], query=True)[0]
    conn.execute("""INSERT INTO embedding_index (event_id, model, dimensions, vector) VALUES
                    (%s, 'other-model', %s, %s::vector),
                    (%s, 'small-model', 2, '[1,0]')""",
                 (c2["id"], L.EMBED_DIM, query, c1["id"]))
    trapped = L.search_claims(conn, PK[BOB], "smoke", "what causes histamine intolerance?", "vector", 5)
    assert trapped["items"][0]["id"] == c1["id"], trapped
    assert next(i for i in trapped["items"] if i["id"] == c2["id"])["distance"] > 0
    event_before = dict(conn.execute("SELECT content, sig FROM events WHERE id = %s", (c1["id"],)).fetchone())
    conn.execute("UPDATE embedding_index SET vector = %s::vector WHERE event_id = %s AND model = %s",
                 ("[" + ",".join(["0"] * L.EMBED_DIM) + "]", c1["id"], L.EMBED_MODEL))
    assert L.rebuild_embeddings(conn, PK[BOB]) >= 1
    fresh = L.embed([conn.execute("SELECT text FROM claims WHERE id = %s", (c1["id"],)).fetchone()["text"]])[0]
    assert conn.execute("""SELECT vector <=> %s::vector AS d FROM embedding_index
                           WHERE event_id = %s AND model = %s""",
                        (fresh, c1["id"], L.EMBED_MODEL)).fetchone()["d"] == 0
    assert conn.execute("SELECT count(*) AS n FROM embedding_index WHERE model = 'other-model'").fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM embedding_index WHERE model = 'small-model'").fetchone()["n"] == 1
    assert dict(conn.execute("SELECT content, sig FROM events WHERE id = %s", (c1["id"],)).fetchone()) == event_before
    kw = L.search_claims(conn, PK[BOB], "smoke", "serum symptom", "keyword", 5)
    assert [h["id"] for h in kw["items"]] == [c2["id"]]
    assert [e["id"] for e in L.list_evidence(conn, PK[BOB], "smoke")] == [doc["id"]]
    assert L.list_evidence(conn, PK[BOB], "smoke", ungrounded_only=True) == []
    assert L.list_evidence(conn, PK[BOB], "smoke", source="example")[0]["link_count"] == 2
    got = L.get_event(conn, PK[BOB], doc["id"], offset=10, max_chars=20)
    assert got["content"]["text"] == DOC[10:30] and got["chars"] == len(DOC) and got["kind_name"] == "evidence"
    assert [x["id"] for x in L.get_links(conn, PK[BOB], "smoke", to_id=c1["id"], relation="QUALIFIES")] == [q1["id"]]
    ks = L.search_contradictions(conn, PK[BOB], "smoke", claim=c2["id"])
    assert ks[0]["claim_ids"] == [c1["id"], c2["id"]] and len(ks[0]["claims"]) == 2
    thin = L.list_claims(conn, PK[BOB], "smoke", "unsupported")
    assert thin[-1]["id"] == c1["id"] and thin[-1]["supports"] == 1 and thin[-1]["findings"] == 1, thin
    # Evidence can say where its text really came from (#7), and every list pages with offset (#11).
    arch = sign(OWNER, E.EVIDENCE, {"collection": "other", "text": "Archived article text.", "url": "https://example.org/a",
                                    "archive_url": "https://web.archive.org/web/2026/https://example.org/a",
                                    "retrieved_via": "Wayback"})
    more = [sign(OWNER, E.CLAIM, {"collection": "other", "text": f"Paging claim {i}."}, created_at=int(time.time()) + i)
            for i in range(3)]
    pub([arch, *more])
    ev = L.list_evidence(conn, PK[OWNER], "other")
    assert ev[0]["archive_url"].startswith("https://web.archive.org/") and ev[0]["retrieved_via"] == "Wayback", ev
    assert L.get_event(conn, PK[OWNER], arch["id"])["content"]["retrieved_via"] == "Wayback"
    every = [c["id"] for c in L.list_claims(conn, PK[OWNER], "other", "oldest", 200)]
    paged = [c["id"] for off in range(0, len(every), 2) for c in L.list_claims(conn, PK[OWNER], "other", "oldest", 2, off)]
    assert paged == every and len(every) == 4, (paged, every)
    assert L.list_evidence(conn, PK[OWNER], "other", offset=1) == [] and L.get_links(conn, PK[OWNER], "other", offset=5) == []
    acct = L.account(conn, PK[BOB])
    assert acct["allowed"] and acct["terms_signed"] and not acct["approved"] and acct["profile"]["name"] == "Bob"
    assert acct["profile"]["model"] is None
    described = "plain text, not an enum: 実験"
    claim_before = dict(conn.execute("SELECT content, sig FROM events WHERE id = %s", (c1["id"],)).fetchone())
    pub([sign(OWNER, E.PROFILE, {"name": "Owner", "about": "human", "model": described})])
    again = L.search_claims(conn, PK[BOB], "smoke", "what causes histamine intolerance?", "vector", 5)
    assert again["items"][0]["id"] == c1["id"] and again["items"][0]["author_model"] == described
    assert conn.execute("""SELECT p.model FROM claims c JOIN profiles p ON p.pubkey = c.pubkey
                           WHERE c.id = %s""", (c1["id"],)).fetchone()["model"] == described
    assert dict(conn.execute("SELECT content, sig FROM events WHERE id = %s", (c1["id"],)).fetchone()) == claim_before
    assert L.get_event(conn, PK[BOB], b1["id"])["author_model"] is None
    rejects(lambda: pub([sign(OWNER, E.PROFILE, {"name": "Owner", "model": {"provider": "x"}})]), "'model'")

    # check_proof looks events up by ID and never reveals other collections.
    proof = {"question": "Does DAO deficiency cause HIT?", "steps": [
        {"id": "s1", "say": "One review proposes reduced DAO activity.", "from": [c1["id"], l1["id"], doc["id"]]},
        {"id": "s2", "say": "A contradiction says this sits badly with serum data.", "from": [k1["id"]]},
        {"id": "s3", "say": "Nothing here covers children.", "from": [], "gap": True},
        {"id": "root", "say": "Proposed, not established.", "from": ["s1", "s2", "s3"]}]}
    res = L.check_proof(conn, PK[BOB], "smoke", proof)
    assert res["ok"] and res["root"] == "root" and '"HIT review"' in res["tree"] and l1["id"] in res["tree"], res
    res = L.check_proof(conn, PK[OWNER], "smoke", {"steps": [
        {"id": "s1", "say": "Cites another collection.", "from": [o1["id"]]},
        {"id": "s2", "say": "Not a gap.", "from": []},
        {"id": "root", "say": "Answer.", "from": ["s1", "s2", "s4"]},
        {"id": "s4", "say": "Later.", "from": [c1["id"]]}]})
    text = "\n".join(res["problems"])
    for needle in (f"{o1['id']} is not an event in collection 'smoke'", "s2: no ledger event", "not an earlier step",
                   "exactly one root"):
        assert needle in text, (needle, res["problems"])
    assert "other" not in text.replace("another", "")

    # Export: every collection event, each line verifies on its own.
    lines = [json.dumps(e) for e in L.export(conn, PK[BOB], "smoke", page=3)]
    assert len(lines) == conn.execute("SELECT count(*) AS n FROM events WHERE collection = 'smoke'").fetchone()["n"]
    for line in lines:
        E.verify(json.loads(line))
    rejects(lambda: list(L.export(conn, PK[OUTSIDER], "smoke")), "not a member")
    return [c1["id"], doc["id"]]


def embed_calls() -> None:
    """embed() logs each call with the tokens the endpoint reports; local endpoints cost nothing."""
    class Fake:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.0] * L.EMBED_DIM}],
                    "usage": {"prompt_tokens": 1_000_000, "total_tokens": 1_000_000}}

    post, url = L.httpx.post, L.EMBED_URL
    L.httpx.post = lambda *a, **k: Fake()
    try:
        L.EMBED_URL = "https://api.deepinfra.com/v1/openai"
        assert len(REAL_EMBED(["a claim"], pubkey=PK[BOB], collection="smoke")) == 1
        L.EMBED_URL = "http://localhost:11434/v1"
        REAL_EMBED(["a query"], query=True, pubkey=PK[OWNER], collection="smoke")
        with L.connect() as conn, conn.transaction():  # logged on the caller's connection, inside its transaction
            REAL_EMBED(["another"], pubkey=PK[BOB], collection="smoke", conn=conn)
    finally:
        L.httpx.post, L.EMBED_URL = post, url
    with L.connect() as conn:
        rows = conn.execute("SELECT pubkey, collection, model, tokens, cost_usd FROM embed_calls ORDER BY id").fetchall()
    assert [(r["pubkey"], r["collection"], r["tokens"], float(r["cost_usd"])) for r in rows] == [
        (PK[BOB], "smoke", 1_000_000, L.EMBED_PRICE_PER_MTOK), (PK[OWNER], "smoke", 1_000_000, 0.0),
        (PK[BOB], "smoke", 1_000_000, 0.0)], rows


def server(ids) -> None:
    """The MCP endpoint over HTTP, in process: signed requests, replay and staleness, login."""
    from starlette.testclient import TestClient

    from tms import server as S
    S.LOCAL_SECRET = None
    n = iter(range(1, 10**6))

    def call(name, arguments):
        r = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": next(n), "method": "tools/call",
                              "params": {"name": name, "arguments": arguments}})
        r.raise_for_status()
        res = r.json()["result"]
        text = res["content"][0]["text"] if res["content"] else ""
        if res.get("isError"):
            raise ValueError(text)
        return res.get("structuredContent", {}).get("result", json.loads(text) if text else None)

    def req(sk, tool, args=None, **kw):
        return E.sign(sk, E.REQUEST, {"tool": tool, "args": args or {}}, **kw)

    with TestClient(S.http_app()) as client:
        r = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
        tools = {t["name"] for t in r.json()["result"]["tools"]}  # the tool list is open to anyone
        assert {"publish", "fetch_url", "search_claims", "get_event", "check_proof"} <= tools, tools

        ok = req(BOB, "search_claims", {"collection": "smoke", "text": "histamine DAO", "method": "keyword"})
        assert call("search_claims", {"request": ok})["items"], "a signed request works"
        # A replayed request is rejected.
        rejects(lambda: call("search_claims", {"request": ok}), "already used")
        # Identical requests signed in the same second differ only by nonce, and both work (#6).
        now = int(time.time())
        twins = [E.sign(BOB, E.REQUEST, {"tool": "list_collections", "args": {}, "nonce": n}, created_at=now) for n in "ab"]
        assert twins[0]["id"] != twins[1]["id"] and all(call("list_collections", {"request": t}) for t in twins)
        # A stale request is rejected.
        stale = req(BOB, "list_collections", created_at=int(time.time()) - 120)
        rejects(lambda: call("list_collections", {"request": stale}), "from server time")
        # A request signed for one tool and sent to another is rejected.
        rejects(lambda: call("list_claims", {"request": req(BOB, "list_collections")}), "signed for tool 'list_collections'")
        # Arguments come only from the signed content.
        rejects(lambda: call("list_claims", {"request": req(BOB, "list_claims", {"collection": "smoke"}),
                                             "collection": "outside"}), "inside its signed content")
        rejects(lambda: call("list_claims", {"request": req(BOB, "list_claims", {"collection": "smoke", "x": 1})}),
                "unknown arguments")
        rejects(lambda: call("list_claims", {}), "request is required")
        tampered = req(BOB, "list_collections")
        rejects(lambda: call("list_collections", {"request": dict(tampered, pubkey=PK[OWNER])}), "id does not match")
        # An unapproved non-member gets nothing beyond the tool list.
        rejects(lambda: call("list_collections", {"request": req(STRANGER, "list_collections")}), "is not approved")
        rejects(lambda: call("fetch_url", {"request": req(STRANGER, "fetch_url", {"url": "https://example.org"})}),
                "is not approved")
        rejects(lambda: call("get_event", {"request": req(OUTSIDER, "get_event", {"id": ids[0]})}) or
                (_ for _ in ()).throw(ValueError("hidden")), "hidden")
        got = call("get_event", {"request": req(BOB, "get_event", {"id": ids[0]})})
        assert got["kind_name"] == "claim", got
        assert [c["slug"] for c in call("list_collections", {"request": req(BOB, "list_collections")})] == ["smoke"]
        res = call("publish", {"events": [sign(BOB, E.CLAIM, {"collection": "smoke", "text": "Published over HTTP."})]})
        assert len(res["accepted"]) == 1, res

        # Browser login: a signed "login" request buys a 12-hour cookie; strangers get none.
        assert client.post("/login", json=req(STRANGER, "login")).status_code == 403
        r = client.post("/login", json=req(BOB, "login"))
        assert r.status_code == 200 and r.json()["pubkey"] == PK[BOB] and "httponly" in r.headers["set-cookie"].lower()
        assert client.post("/login", json=req(BOB, "list_collections")).status_code == 400
        assert client.post("/login", content=b"not json").status_code == 400

        # Web pages: Bob is a member of smoke, not its owner; the owner manages members; export verifies.
        from tms import web as W
        assert "Connect" in client.get("/").text and client.get("/submit").status_code == 200
        me = client.get("/api/me").json()
        assert me["pubkey"] == PK[BOB] and [c["slug"] for c in me["collections"]] == ["smoke"] and "Version" in me["terms_text"]
        assert {m["name"] for m in client.get("/api/c/smoke").json()["members"]} == {"Owner", "Bob"}
        assert client.get("/api/c/outside").status_code == 403
        assert client.get("/c/smoke/members").status_code == 403
        lines = client.get("/c/smoke/export.jsonl").text.splitlines()
        assert lines and all(E.verify(json.loads(x)) for x in lines)
        assert client.get("/c/outside/export.jsonl").status_code == 403
        r = client.post("/api/publish", json={"events": [sign(BOB, E.CLAIM, {"collection": "smoke", "text": "From the web."})]})
        assert r.status_code == 200 and len(r.json()["accepted"]) == 1, r.text
        bad = sign(BOB, E.LINK, {"collection": "smoke", "from": ids[1], "to": ids[0], "relation": "SUPPORTS",
                                 "quote": "not in the text", "reason": "r"})
        r = client.post("/api/publish", json={"events": [bad]})
        assert r.status_code == 400 and "quote not found" in r.json()["error"], r.text
        client.cookies.set(W.COOKIE, W.make_cookie(PK[OWNER]))
        assert client.get("/c/smoke/members").status_code == 200
        # Admin page: TMS_ADMINS only; everyone else, logged out included, gets a 404.
        L.ADMINS = {PK[OWNER]}
        r = client.get("/admin")
        assert r.status_code == 200 and "DeepInfra spend" in r.text and E.bech32_encode("npub", PK[BOB]) in r.text, r.text[:300]
        assert "Bob" in r.text and "$0.0100" in r.text, "users table and embed spend"
        # Dashboard: scoped to the viewer's collections.
        assert client.get("/dashboard/api/collections").json()["can_create"], "an approved owner gets the + card"
        snap = client.get("/dashboard/api/snapshot").json()
        assert {c["slug"] for c in snap["collections"]} == {"smoke", "other"}, snap["collections"]
        # Npubs tab: an admin sees every key and every collection it belongs to.
        n = client.get("/dashboard/api/npubs").json()
        byk = {x["pubkey"]: x for x in n["npubs"]}
        assert n["admin"] and byk[PK[BOB]]["member_of"] == ["smoke"] and byk[PK[BOB]]["name"] == "Bob", byk[PK[BOB]]
        assert byk[PK[OUTSIDER]]["owns"] == ["outside"] and byk[PK[BOB]]["npub"] == E.bech32_encode("npub", PK[BOB])
        client.cookies.set(W.COOKIE, W.make_cookie(PK[OUTSIDER]))
        assert client.get("/dashboard").status_code == 200
        client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))  # a member, not approved: no + card
        assert not client.get("/dashboard/api/collections").json()["can_create"]
        client.cookies.set(W.COOKIE, W.make_cookie(PK[OUTSIDER]))
        for path in ("snapshot", "browse?kind=claim", "agents", "sources", "collections"):
            r = client.get(f"/dashboard/api/{path}")
            assert r.status_code == 200 and "smoke" not in r.text and ids[0] not in r.text, (path, r.text[:300])
        assert client.get(f"/dashboard/api/record/{ids[0]}").status_code == 404
        # An owner who isn't an admin sees every key, but memberships in their own collections only.
        n = client.get("/dashboard/api/npubs")
        assert n.status_code == 200 and not n.json()["admin"] and "smoke" not in n.text and "other" not in n.text, n.text[:300]
        assert PK[BOB] in n.text and {x["pubkey"]: x for x in n.json()["npubs"]}[PK[OUTSIDER]]["owns"] == ["outside"]
        client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))  # a member who owns nothing
        assert client.get("/dashboard/api/npubs").status_code == 403
        good = W.make_cookie(PK[OWNER])
        client.cookies.set(W.COOKIE, good[:-1] + ("1" if good.endswith("0") else "0"))
        assert client.get("/api/me").status_code == 401 and client.get("/c/smoke/export.jsonl").status_code == 401
        client.cookies.set(W.COOKIE, W.make_cookie(PK[STRANGER]))  # logged in, but neither approved nor a member
        assert client.get("/api/fetch?url=https://example.org/").status_code == 403
        client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))  # a member; tests allow local files, so no network
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
            f.write(DOC)
            f.flush()
            r = client.get("/api/fetch", params={"url": f.name})
            assert r.status_code == 200 and r.json()["text"].startswith("Histamine intolerance"), r.text
        client.cookies.clear()
        assert client.get("/api/me").status_code == 401
        assert client.get("/admin").status_code == 404
        client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))
        assert client.get("/admin").status_code == 404
        client.cookies.clear()
        # Admins from the admins table: a site admin adds one, who can do everything except manage admins
        # and sees only their own collections; removing them takes effect at once.
        bob_npub = E.bech32_encode("npub", PK[BOB])
        client.cookies.set(W.COOKIE, W.make_cookie(PK[OWNER]))
        assert client.post("/admin/admins", data={"npub": "not-a-key"}).status_code == 400
        assert client.post("/admin/admins", data={"npub": bob_npub}, follow_redirects=False).status_code == 303
        assert "Add admin" in client.get("/admin").text
        client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))
        page = client.get("/admin")
        assert page.status_code == 200 and "Only site admins" in page.text and "Add admin" not in page.text
        assert "<td>other</td>" not in page.text and "<td>outside</td>" not in page.text, "an admin sees spend for their own collections only"
        assert client.post("/admin/admins", data={"npub": bob_npub}).status_code == 404, "only site admins manage admins"
        n = client.get("/dashboard/api/npubs")
        assert n.status_code == 200 and not n.json()["admin"] and "outside" not in n.text and "other" not in n.text
        assert client.get("/dashboard/api/chat").json()["collections"] == ["smoke"]
        with L.connect() as conn:
            assert L.is_admin(conn, PK[BOB]) and L.is_approved(conn, PK[BOB])
        client.cookies.set(W.COOKIE, W.make_cookie(PK[OWNER]))
        assert client.post(f"/admin/admins/{PK[BOB]}/remove", follow_redirects=False).status_code == 303
        client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))
        assert client.get("/admin").status_code == 404 and client.get("/dashboard/api/chat").status_code == 404
        client.cookies.clear()
        # Docs are public, with the live base URL and terms hash filled in.
        r = client.get("/docs")
        assert r.status_code == 200 and "marked@15.0.12" in r.text and "{{" not in r.text
        md = client.get("/docs.md").text
        assert "## Philosophy" in md and "### What readers decide" in md and 'id="toc"' in r.text, "philosophy section and sidebar"
        bl = client.get("/docs/bitter-lesson")
        assert bl.status_code == 200 and "Bitter Lesson Applied to Knowledge Graphs" in bl.text and "{{" not in bl.text and "@" in bl.text
        assert "/docs/bitter-lesson" in md and client.get("/docs/nope").status_code == 404
        wn = client.get("/docs/why-nostr")
        assert wn.status_code == 200 and "Why Nostr Keys for Login" in wn.text and "/docs/why-nostr" in md
        assert "http://testserver/mcp" in md and L.TERMS["sha256"] in md and "publish" in md
        # The office is public and content-free: squiggles only, no ledger reads.
        office = client.get("/office")
        assert office.status_code == 200 and "window.botOffice" in office.text
        assert "prefers-reduced-motion" in office.text and "aria-describedby=\"office-desc\"" in office.text
        assert "smoke" not in office.text and ids[0] not in office.text
        landing = client.get("/")  # logged out: the office is the landing page
        assert landing.headers["cache-control"] == "private, no-store"
        assert 'id="landing"' in landing.text and "Request access" in landing.text and client.get("/connect").status_code == 200
        assert "<title>TMS · Your personal intelligence agency</title>" in landing.text
        assert 'property="og:title" content="TMS · Your personal intelligence agency"' in landing.text
        assert 'name="description" content="Your personal intelligence agency. A private evidence ledger for people and AI agents."' in landing.text
        assert 'name="twitter:card" content="summary"' in landing.text and 'name="twitter:title"' in landing.text
        r = client.get("/office.json", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200 and r.headers["cache-control"].startswith("public") and "totals" in r.json()
        # The ticker: six global counts and nothing else, at most a minute old.
        st = client.get("/stats.json")
        assert st.status_code == 200 and st.headers["cache-control"] == "public, max-age=60" and 'id="ticker"' in office.text
        assert set(st.json()) == {"contributors", "collections", "claims", "evidence", "links", "contradictions"}
        assert all(type(v) is int for v in st.json().values()) and st.json() == r.json()["totals"]
        access(client, W)

    office_data()
    fetch_stub()
    chat_agent()
    email_signin()
    showcase()

    with L.connect() as conn:
        rows = conn.execute("SELECT tool, pubkey, collection, ok FROM mcp_calls WHERE method = 'tools/call'").fetchall()
    assert any(r["tool"] == "search_claims" and r["pubkey"] == PK[BOB] and r["collection"] == "smoke" and r["ok"] for r in rows)
    assert any(r["tool"] == "publish" and r["pubkey"] == PK[BOB] for r in rows)
    assert any(not r["ok"] and r["pubkey"] is None for r in rows), "failed auth logs no pubkey"


def access(client, W) -> None:
    """Request access (unsigned, rate-limited, one pending request per npub); Approve in /admin
    grants access with no restart; Dismiss doesn't; only admins can decide."""
    visitor, other = hashlib.sha256(b"visitor").hexdigest(), hashlib.sha256(b"dismissed").hexdigest()
    vpk, opk = E.pubkey_of(visitor), E.pubkey_of(other)
    W._recent.clear()
    client.cookies.clear()
    ask = lambda key, note="", **kw: client.post("/api/access-request", json={"npub": key, "note": note}, **kw)  # noqa: E731
    assert client.post("/login", json=E.request(visitor, "login")).status_code == 403
    r = ask(E.bech32_encode("npub", vpk), "I read papers on histamine intolerance.")
    assert r.status_code == 201 and r.json()["status"] == "pending", r.text
    assert ask(vpk).status_code == 201, "a duplicate gets the same answer, so replies reveal nothing"
    with L.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM access_requests WHERE npub = %s",
                            (E.bech32_encode("npub", vpk),)).fetchone()["n"] == 1, "but only one request is stored"
    assert ask(opk, "x" * 501).status_code == 400 and ask("npub1nope").status_code == 400
    assert ask(opk).status_code == 201
    # Five requests per address per hour: these five calls used it up.
    sixth = E.pubkey_of(hashlib.sha256(b"sixth").hexdigest())
    assert ask(sixth).status_code == 429
    # A forged X-Forwarded-For doesn't help: the proxy's own (rightmost) entry is what counts.
    W._recent.clear()
    via = lambda forged: {"headers": {"X-Forwarded-For": f"{forged}, 203.0.113.7"}}  # noqa: E731
    for i in range(5):
        assert ask(E.pubkey_of(hashlib.sha256(f"spoof{i}".encode()).hexdigest()), **via(f"10.0.0.{i}")).status_code == 201
    assert ask(sixth, **via("10.0.0.99")).status_code == 429
    assert ask(sixth, headers={"X-Forwarded-For": "203.0.113.8"}).status_code == 201, "a different real address has its own limit"
    W._recent.clear()

    with L.connect() as conn:
        reqs = {r["npub"]: r["id"] for r in conn.execute("SELECT id, npub FROM access_requests WHERE status = 'pending'")}
    vid, oid = reqs[E.bech32_encode("npub", vpk)], reqs[E.bech32_encode("npub", opk)]
    client.cookies.set(W.COOKIE, W.make_cookie(PK[OWNER]))  # OWNER is the admin
    page = client.get("/admin").text
    assert "Access requests (8 pending)" in page and "histamine intolerance" in page
    assert client.post(f"/admin/requests/{vid}/approve", headers={"Origin": "https://evil.example"}).status_code == 403
    r = client.post(f"/admin/requests/{vid}/approve", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert client.post(f"/admin/requests/{oid}/dismiss", follow_redirects=False).status_code == 303
    assert client.post(f"/admin/requests/{oid}/burn").status_code == 404
    client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))
    assert client.post(f"/admin/requests/{vid}/approve").status_code == 404, "non-admins can't decide"
    client.cookies.clear()

    # Approved without a restart: the visitor logs in, and can now create a collection. (Back-dated a
    # few seconds: the 403 above used an identical request, and the server refuses replays.)
    login = lambda sk: E.sign(sk, E.REQUEST, {"tool": "login", "args": {}}, created_at=int(time.time()) - 5)  # noqa: E731
    assert client.post("/login", json=login(visitor)).status_code == 200
    assert client.post("/login", json=login(other)).status_code == 403
    client.cookies.clear()
    r = client.post("/api/publish", json={"events": [E.sign(visitor, E.TERMS, L.TERMS),
                                                     E.sign(visitor, E.CLAIM, {"collection": "visitor-col", "text": "Mine."})]})
    assert r.status_code == 200 and r.json()["collections"] == ["visitor-col"], r.text
    with L.connect() as conn:
        assert conn.execute("SELECT approved_by FROM approvals WHERE pubkey = %s", (vpk,)).fetchone()["approved_by"] == PK[OWNER]
        assert conn.execute("SELECT count(*) AS n FROM approvals WHERE pubkey = %s", (opk,)).fetchone()["n"] == 0
        assert {r["status"] for r in conn.execute("SELECT status FROM access_requests")} == {"approved", "dismissed", "pending"}


def showcase() -> None:
    """Owners can make a collection public: the home page shows its name, topic and counts, nothing else."""
    from starlette.testclient import TestClient

    from tms import office as O
    from tms import server as S
    with L.connect() as conn:
        rejects(lambda: L.publish(conn, [sign(BOB, E.ABOUT, {"collection": "smoke", "topic": "Mine now", "public": True})]),
                "only the owner")
        rejects(lambda: L.publish(conn, [sign(OWNER, E.ABOUT, {"collection": "smoke", "topic": "x" * 141, "public": True})]),
                "topic")
        L.publish(conn, [sign(OWNER, E.ABOUT, {"collection": "smoke", "topic": "Histamine intolerance and MCAS", "public": True})])
        mine = {c["slug"]: c for c in L.list_collections(conn, PK[OWNER])}
        assert mine["smoke"]["topic"].startswith("Histamine") and mine["smoke"]["public"] and not mine["other"]["public"], mine
        counts = conn.execute("""SELECT count(*) FILTER (WHERE kind = 4701) AS evidence, count(*) FILTER (WHERE kind = 4702) AS claims,
            count(*) FILTER (WHERE kind = 4703) AS links, count(*) FILTER (WHERE kind = 4704) AS contradictions
            FROM events WHERE collection = 'smoke'""").fetchone()
    O._showcase.clear()
    with TestClient(S.http_app()) as client:
        r = client.get("/showcase.json")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        cols = r.json()["collections"]
        assert [c["slug"] for c in cols] == ["smoke"], cols  # "other" and "outside" stay hidden
        assert set(cols[0]) == {"slug", "topic", "evidence", "claims", "links", "contradictions"}, "counts only, no records"
        assert all(cols[0][k] == counts[k] for k in counts), (cols, counts)
        page = client.get("/communities")  # public page, no login
        assert page.status_code == 200 and 'id="communities"' in page.text and "/showcase.json" in page.text
        assert 'href="/communities"' in client.get("/").text and "tab-communities" not in client.get("/").text
        with L.connect() as conn:
            L.publish(conn, [sign(OWNER, E.ABOUT, {"collection": "smoke", "topic": "Histamine intolerance and MCAS", "public": False},
                                  created_at=int(time.time()) + 1)])
        O._showcase.clear()
        assert client.get("/showcase.json").json()["collections"] == [], "the latest about wins"


def email_signin() -> None:
    """Email sign-in: codes, a held key that signs for the account, export, and forgetting it."""
    import re as _re

    from starlette.testclient import TestClient

    from tms import email_login as EL
    from tms import server as S
    from tms import web as W
    sent = []
    EL.send = lambda to, subject, text: sent.append((to, _re.search(r"\b(\d{6})\b", text).group(1)))
    EL.KEY_SECRET, EL.RESEND_API_KEY = "smoke-key-secret", "test"
    code = lambda: sent[-1][1]  # noqa: E731
    with TestClient(S.http_app()) as client:
        W._recent.clear()
        assert client.post("/api/email/start", json={"email": "not an email"}).status_code == 400
        assert client.post("/api/email/start", json={"email": "Ann@Example.com"}).json() == {"sent": True}
        assert sent[-1][0] == "ann@example.com"
        assert client.post("/api/email/verify", json={"email": "ann@example.com", "code": "000000" if code() != "000000" else "111111"}).status_code == 400
        r = client.post("/api/email/verify", json={"email": "ann@example.com", "code": code()})
        assert r.status_code == 403 and "waiting for an admin" in r.json()["error"], r.text  # new, not yet approved
        with L.connect() as conn:
            pk = conn.execute("SELECT pubkey FROM email_accounts WHERE email = 'ann@example.com'").fetchone()["pubkey"]
            assert conn.execute("SELECT note FROM access_requests WHERE npub = %s", (E.bech32_encode("npub", pk),)).fetchone()["note"].endswith("ann@example.com")
            conn.execute("INSERT INTO approvals (pubkey, approved_by) VALUES (%s, 'smoke')", (pk,))
            assert not conn.execute("SELECT 1 FROM events WHERE content LIKE '%%ann@example.com%%'").fetchone(), "the email never reaches a record"
        client.post("/api/email/start", json={"email": "ann@example.com"})
        me = client.post("/api/email/verify", json={"email": "ann@example.com", "code": code()}).json()
        assert me["pubkey"] == pk and me["custodial"] and me["email"] == "ann@example.com", me
        assert client.post("/api/email/verify", json={"email": "ann@example.com", "code": code()}).status_code == 400, "a code works once"
        # The held key signs; the event is a normal signed event and publishes like any other.
        ev = client.post("/api/sign", json={"kind": E.TERMS, "content": L.TERMS}).json()
        assert ev["pubkey"] == pk and E.verify(ev) is not None
        assert client.post("/api/publish", json={"events": [ev]}).json()["accepted"] == [ev["id"]]
        assert client.post("/api/sign", json={"kind": E.REQUEST, "content": {"tool": "login", "args": {}}}).status_code == 400
        assert client.post("/api/sign", json={"kind": E.CLAIM, "content": {"collection": "x", "text": "t"}},
                           headers={"Origin": "https://evil.example"}).status_code == 403
        # Wrong guesses use up a code.
        client.post("/api/email/start", json={"email": "ann@example.com"})
        good = code()
        for _ in range(EL.MAX_ATTEMPTS):
            client.post("/api/email/verify", json={"email": "ann@example.com", "code": "999999" if good != "999999" else "888888"})
        assert client.post("/api/email/verify", json={"email": "ann@example.com", "code": good}).status_code == 400
        W._recent.clear()
        for _ in range(EL.CODES_PER_HOUR):
            client.post("/api/email/start", json={"email": "ann@example.com"})
        assert client.post("/api/email/start", json={"email": "ann@example.com"}).status_code == 429
        with L.connect() as conn:
            conn.execute("DELETE FROM email_codes")
        # Export needs a fresh code, returns the same key, then the server can forget it.
        assert client.post("/api/key/forget").status_code == 400, "export first"
        assert client.post("/api/key/export", json={"code": "123456"}).status_code == 400
        client.post("/api/key/export-code")
        k = client.post("/api/key/export", json={"code": code()}).json()
        assert E.pubkey_of(k["nsec"]) == pk and k["npub"] == E.bech32_encode("npub", pk)
        assert client.post("/api/key/forget").json() == {"forgotten": True}
        assert client.get("/api/me").json()["custodial"] is False
        assert client.post("/api/sign", json={"kind": E.CLAIM, "content": {"collection": "x", "text": "t"}}).status_code == 403
        W._recent.clear()
        client.post("/api/email/start", json={"email": "ann@example.com"})
        assert client.post("/api/email/verify", json={"email": "ann@example.com", "code": code()}).status_code == 409
        # Keys that were never email accounts can't use /api/sign.
        client.cookies.set(W.COOKIE, W.make_cookie(PK[OWNER]))
        assert client.post("/api/sign", json={"kind": E.CLAIM, "content": {"collection": "x", "text": "t"}}).status_code == 403
        client.cookies.clear()
    with L.connect() as conn:
        assert conn.execute("SELECT nsec_enc FROM email_accounts WHERE pubkey = %s", (pk,)).fetchone()["nsec_enc"] is None


def chat_agent() -> None:
    """Admin chat: a scripted model calls a read tool, then answers; tools stay in the chat's collection."""
    from starlette.testclient import TestClient

    from tms import chat as C
    from tms import server as S
    from tms import web as W
    with L.connect() as conn:
        other = conn.execute("SELECT id FROM events WHERE collection = 'other' ORDER BY received_at LIMIT 1").fetchone()["id"]
    script = [  # first reply asks for two tools, the second answers
        {"tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "search_claims", "arguments": '{"text": "DAO", "method": "keyword"}'}},
            {"id": "t2", "type": "function", "function": {"name": "get_event", "arguments": json.dumps({"id": other})}}]},
        {"content": "Reduced DAO activity is the review's proposal."}]
    seen = []

    class Reply:
        status_code = 200

        def __init__(self, msg):
            self.msg = msg

        def json(self):
            return {"choices": [{"message": {"role": "assistant", **self.msg}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}

    def post(url, json=None, **kw):
        seen.append(json)
        return Reply(script[len(seen) - 1])
    real, C.httpx.post = C.httpx.post, post
    L.ADMINS = {PK[OWNER]}
    try:
        with TestClient(S.http_app()) as client:
            assert client.get("/dashboard/api/chat").status_code == 404  # logged out
            js = client.get("/chat.js")  # the launcher every page loads; it stays hidden unless the config answers
            assert js.status_code == 200 and "javascript" in js.headers["content-type"] and "/dashboard/api/chat" in js.text
            assert "marked@15.0.12" in js.text and "createElement('template')" in js.text, "answers render as markdown, cleaned in an inert template"
            assert all('src="/chat.js"' in client.get(p).text for p in ("/", "/office", "/docs", "/connect")), "on every page"
            assert all("github.com/DeleganceAI/tms-ledger" in client.get(p).text for p in ("/", "/office", "/docs", "/connect", "/dashboard")), "GitHub link"
            client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))  # a member, not an admin
            assert client.get("/dashboard/api/chat").status_code == 404
            assert client.post("/dashboard/api/chat", json={}).status_code == 404
            client.cookies.set(W.COOKIE, W.make_cookie(PK[OWNER]))
            cfg = client.get("/dashboard/api/chat").json()
            assert cfg["model"] == C.CHAT_MODEL and "smoke" in cfg["collections"], cfg
            ask = [{"role": "user", "content": "What causes HIT?"}]
            assert client.post("/dashboard/api/chat", json={"collection": "outside", "messages": ask}).status_code == 403
            assert client.post("/dashboard/api/chat", json={"collection": "smoke", "messages": []}).status_code == 400
            r = client.post("/dashboard/api/chat", json={"collection": "smoke", "messages": ask})
            evs = [json.loads(x[6:]) for x in r.text.split("\n\n") if x.startswith("data: ")]
    finally:
        C.httpx.post = real
    assert [e["type"] for e in evs] == ["tool_call", "tool_result", "tool_call", "tool_result", "answer", "messages"], evs
    assert "Histamine intolerance" in evs[1]["result"] and evs[3]["result"] == "null", "pinned to the chat's collection"
    assert evs[4]["content"].startswith("Reduced DAO") and [m["role"] for m in evs[5]["messages"]] == ["user", "assistant", "tool", "tool", "assistant"]
    tools = {t["function"]["name"] for t in seen[0]["tools"]}
    assert seen[0]["model"] == C.CHAT_MODEL and "publish" not in tools and "search_claims" in tools and seen[0]["messages"][0]["role"] == "system"
    with L.connect() as conn:
        row = conn.execute("SELECT count(*) AS n, sum(cost_usd) AS c FROM embed_calls WHERE model = %s", (C.CHAT_MODEL,)).fetchone()
    assert row["n"] == 2 and abs(float(row["c"]) - 2 * (1000 * C.PRICE_IN + 100 * C.PRICE_OUT) / 1e6) < 1e-9, row


def fetch_stub() -> None:
    """fetch_url refuses captcha and near-empty pages instead of returning them as text (#2)."""
    import tempfile
    stub = ("<html><head><title>pmc.ncbi.nlm.nih.gov</title><script src='https://www.google.com/recaptcha/api.js'>"
            "</script></head><body><p>Please verify you are a human.</p></body></html>")
    real = "<html><head><title>A paper</title></head><body><article>" + "".join(
        f"<p>Paragraph {i}: mast cells release histamine and tryptase, and the levels vary.</p>" for i in range(30)) + "</article></body></html>"
    with tempfile.TemporaryDirectory() as d:
        for name, page in (("stub.html", stub), ("real.html", real)):
            Path(d, name).write_text(page)
        rejects(lambda: L.fetch_text(str(Path(d, "stub.html"))), "bot challenge or near-empty page")
        assert L.fetch_text(str(Path(d, "real.html")))[1] == "A paper"


def office_data() -> None:
    """/office.json: anonymous by construction, no boards for small collections, slices capped."""
    from datetime import UTC, datetime, timedelta

    from tms import office as O
    with L.connect() as conn:
        # Grow "smoke" past the board threshold, all in this hour so they replay next hour.
        before = conn.execute("SELECT count(*) AS n FROM events WHERE collection = 'smoke' AND kind BETWEEN 4701 AND 4704").fetchone()["n"]
        doc = sign(BOB, E.EVIDENCE, {"collection": "smoke", "text": "Office test paper about mast cells and tryptase.", "title": "Mast cells"})
        claims = [sign(BOB, E.CLAIM, {"collection": "smoke", "text": f"Office claim number {i} about tryptase."}) for i in range(3)]
        links = [sign(BOB, E.LINK, {"collection": "smoke", "from": doc["id"], "to": c["id"], "relation": rel,
                                    "quote": "mast cells", "reason": "office"}) for c, rel in zip(claims, ("SUPPORTS", "QUALIFIES"))]
        k = sign(BOB, E.CONTRADICTION, {"collection": "smoke", "claims": [claims[0]["id"], claims[2]["id"]], "reason": "office"})
        L.publish(conn, [doc, *claims, *links, k])
        assert before + 7 >= O.MIN_RECORDS
        data = O.compute(conn, now=datetime.now(UTC) + timedelta(hours=1))
        text = json.dumps(data)
        sizes = {r["collection"]: r["n"] for r in conn.execute(
            "SELECT collection, count(*) AS n FROM events WHERE kind BETWEEN 4701 AND 4704 GROUP BY 1")}
        secrets_ = [r["slug"] for r in conn.execute("SELECT slug FROM collections")]
        secrets_ += [x for r in conn.execute("SELECT id, pubkey FROM events") for x in (r["id"], r["id"][:12], r["pubkey"], r["pubkey"][:12])]
        secrets_ += [E.bech32_encode("npub", r["pubkey"]) for r in conn.execute("SELECT DISTINCT pubkey FROM events")]
        for r in conn.execute("""SELECT content::jsonb ->> 'text' AS t FROM events WHERE kind IN (4701, 4702)
                                 UNION SELECT reason FROM links UNION SELECT quote FROM links UNION SELECT reason FROM contradictions"""):
            secrets_.append(r["t"])
        totals = data["totals"]
        actual = conn.execute("""SELECT (SELECT count(*) FROM claims) AS claims, (SELECT count(*) FROM evidence) AS evidence,
            (SELECT count(*) FROM collections) AS collections, (SELECT count(*) FROM contradictions) AS contradictions""").fetchone()
    # Anonymous: no slug, pubkey, npub, record id (or its prefix) or text anywhere in the payload.
    leaks = [x for x in secrets_ if x and x in text]
    assert not leaks, leaks[:5]
    assert set(data) == {"generated_at", "totals", "boards", "replay"} and data["generated_at"].endswith(":00:00Z")
    assert all(totals[k] == actual[k] for k in actual), (totals, actual)  # small collections still count
    # Small collections count toward totals but get no board.
    assert len(data["boards"]) == sum(1 for n in sizes.values() if n >= O.MIN_RECORDS) == 1, (sizes, len(data["boards"]))
    board = data["boards"][0]
    assert 0 <= board["confusion"] <= 4 and board["id"].startswith("b_")
    # The previous hour (this one, from an hour ahead) replays: every kind, pointing into its own slice.
    kinds = {e["kind"] for e in data["replay"]}
    assert {"evidence", "claim", "link", "contradiction"} <= kinds, kinds
    slices = {sl["id"]: sl for sl in board["slices"]}
    for e in data["replay"]:
        sl = slices[e["slice"]]
        assert e["board"] == board["id"] and 0 <= e["node"] < len(sl["nodes"]) and 0 <= e["t"] < 3600
        if e["kind"] == "link" and e["to"] is not None:
            assert [e["node"], e["to"], e["relation"]] in sl["edges"]
        if e["kind"] == "contradiction":
            assert e["claims"] == 2 and e["node"] in sl["contradictions"][e["c"]]

    # Slices stop at about 40 nodes however big the collection: a tree of ~5,000 claims and papers.
    tree = {"n0": "claim"}
    tree_links = []
    for i in range(1, 5000):
        tree[f"n{i}"] = "evidence" if i % 2 else "claim"
        tree_links.append((f"n{i}", f"n{(i - 1) // 4}", "S"))
    sl, _ = O.Graph(tree, tree_links, []).slice(["n0"], O.random.Random(1))
    assert 35 <= len(sl["nodes"]) <= O.SLICE_NODES, len(sl["nodes"])
    assert sl["off_edge"], "a big collection spills strings off the board"
    # A hub contributes at most BRANCH neighbours; the rest of its strings run off the board.
    nodes = {"hub": "claim", **{f"e{i}": "evidence" for i in range(500)}, **{f"c{i}": "claim" for i in range(500)}}
    links_ = [(f"e{i}", "hub", "S") for i in range(500)] + [(f"e{i}", f"c{i}", "R") for i in range(500)]
    sl, idx = O.Graph(nodes, links_, [["hub", "c1", "c2"]]).slice(["hub"], O.random.Random(1))
    assert len([e for e in sl["edges"] if e[1] == idx["hub"]]) <= O.BRANCH
    assert any(i == idx["hub"] and n == O.MAX_OFF_EDGE for i, n in sl["off_edge"])
    assert len(sl["nodes"]) <= O.SLICE_NODES and all(len(m) >= 2 for m in sl["contradictions"])


if __name__ == "__main__":
    main()
