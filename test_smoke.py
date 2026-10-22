"""End-to-end check of the signed-event ledger against a scratch Postgres.

    TMS_SMOKE_URL=postgresql://tmsv2:tmsv2@localhost:5432/tmsv2_smoke uv run python test_smoke.py

Drops and recreates that database (its name must end in _smoke), applies db/init.sql, and runs
every PLAN.md test. Embeddings are faked with a bag of words, so no model is needed.
"""
import hashlib
import json
import os
import re
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


def fake_embed(texts, query=False, pubkey=None, collection=None):
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


def main() -> None:
    recreate()
    with L.connect() as conn:
        ids = ledger(conn)
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
    acct = L.account(conn, PK[BOB])
    assert acct["allowed"] and acct["terms_signed"] and not acct["approved"] and acct["profile"]["name"] == "Bob"

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
    finally:
        L.httpx.post, L.EMBED_URL = post, url
    with L.connect() as conn:
        rows = conn.execute("SELECT pubkey, collection, model, tokens, cost_usd FROM embed_calls ORDER BY id").fetchall()
    assert [(r["pubkey"], r["collection"], r["tokens"], float(r["cost_usd"])) for r in rows] == [
        (PK[BOB], "smoke", 1_000_000, L.EMBED_PRICE_PER_MTOK), (PK[OWNER], "smoke", 1_000_000, 0.0)], rows


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
        assert r.status_code == 200 and "Embedding spend" in r.text and E.bech32_encode("npub", PK[BOB]) in r.text, r.text[:300]
        assert "Bob" in r.text and "$0.0100" in r.text, "users table and embed spend"
        # Dashboard: scoped to the viewer's collections.
        snap = client.get("/dashboard/api/snapshot").json()
        assert {c["slug"] for c in snap["collections"]} == {"smoke", "other"}, snap["collections"]
        client.cookies.set(W.COOKIE, W.make_cookie(PK[OUTSIDER]))
        assert client.get("/dashboard").status_code == 200
        for path in ("snapshot", "browse?kind=claim", "agents", "sources", "collections"):
            r = client.get(f"/dashboard/api/{path}")
            assert r.status_code == 200 and "smoke" not in r.text and ids[0] not in r.text, (path, r.text[:300])
        assert client.get(f"/dashboard/api/record/{ids[0]}").status_code == 404
        good = W.make_cookie(PK[OWNER])
        client.cookies.set(W.COOKIE, good[:-1] + ("1" if good.endswith("0") else "0"))
        assert client.get("/api/me").status_code == 401 and client.get("/c/smoke/export.jsonl").status_code == 401
        client.cookies.clear()
        assert client.get("/api/me").status_code == 401
        assert client.get("/admin").status_code == 404
        client.cookies.set(W.COOKIE, W.make_cookie(PK[BOB]))
        assert client.get("/admin").status_code == 404
        client.cookies.clear()
        # Docs are public, with the live base URL and terms hash filled in.
        r = client.get("/docs")
        assert r.status_code == 200 and "marked@15.0.12" in r.text and "{{" not in r.text
        md = client.get("/docs.md").text
        assert "http://testserver/mcp" in md and L.TERMS["sha256"] in md and "publish" in md
        # The office is public and content-free: squiggles only, no ledger reads.
        office = client.get("/office")
        assert office.status_code == 200 and "window.botOffice" in office.text
        assert "prefers-reduced-motion" in office.text and "aria-describedby=\"office-desc\"" in office.text
        assert "smoke" not in office.text and ids[0] not in office.text
        landing = client.get("/")  # logged out: the office is the landing page
        assert landing.headers["cache-control"] == "private, no-store"
        assert 'id="landing"' in landing.text and "Request access" in landing.text and client.get("/connect").status_code == 200
        r = client.get("/office.json", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200 and r.headers["cache-control"].startswith("public") and "totals" in r.json()
        access(client, W)

    office_data()

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
