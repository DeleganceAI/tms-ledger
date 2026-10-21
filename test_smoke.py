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


def fake_embed(texts, query=False):
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
    pub([terms(BOB), sign(BOB, E.PROFILE, {"name": "Bob", "about": "agent"})])
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
    return [c1["id"]]


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

    with L.connect() as conn:
        rows = conn.execute("SELECT tool, pubkey, collection, ok FROM mcp_calls WHERE method = 'tools/call'").fetchall()
    assert any(r["tool"] == "search_claims" and r["pubkey"] == PK[BOB] and r["collection"] == "smoke" and r["ok"] for r in rows)
    assert any(r["tool"] == "publish" and r["pubkey"] == PK[BOB] for r in rows)
    assert any(not r["ok"] and r["pubkey"] is None for r in rows), "failed auth logs no pubkey"


if __name__ == "__main__":
    main()
