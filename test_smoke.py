"""End-to-end check of the ledger module against a live database and Ollama.

    TMS_DATABASE_URL=postgresql://tmsv2:tmsv2@localhost:5432/tmsv2_check uv run python test_smoke.py

Everything runs in one transaction and rolls back. Needs db/init.sql applied and Ollama serving
the embedding model. The one thing that must fail is a quote that is not in the document.
"""
import json

import psycopg

from tms import ledger as L

DOC = """Histamine intolerance (HIT) is thought to result from reduced diamine oxidase (DAO) activity.
Serum DAO activity correlates poorly with symptom severity in several cohorts.
In one 2019 trial, DAO supplementation reduced symptom scores in adults with low serum DAO."""


def main() -> None:
    with L.connect(autocommit=False) as conn:
        try:
            run(conn)
        finally:
            conn.rollback()
    print("PASS: smoke")


def run(conn) -> None:
    L.add_author(conn, "smoke-agent", "Smoke test agent", "agent")
    L.add_collection(conn, "smoke", "Smoke collection", "smoke-agent")
    L.add_collection(conn, "other", "Other collection", "smoke-agent")
    src = L.add_source(conn, "Example journal", "smoke-agent", "https://example.org")
    obs = L.add_observation(conn, "smoke", src["id"], "smoke-agent", "https://example.org/hit-review", DOC)
    assert obs["chars"] == len(DOC) and "content" not in obs

    c1 = L.add_claim(conn, "smoke", "Histamine intolerance results from reduced DAO activity.", "smoke-agent")
    c2 = L.add_claim(conn, "smoke", "Serum DAO activity correlates poorly with symptom severity.", "smoke-agent")
    c3 = L.add_claim(conn, "other", "An unrelated claim in another collection.", "smoke-agent")

    e1 = L.add_evidence(conn, obs["id"], "claim", c1["id"], "SUPPORTS",
                        "thought to result from reduced diamine oxidase (DAO) activity",
                        "The review names reduced DAO activity as the proposed mechanism.", "smoke-agent")
    assert e1["target_id"] == c1["id"] and "target_claim_id" not in e1
    q1 = L.add_evidence(conn, obs["id"], "claim", c1["id"], "QUALIFIES",
                        "correlates poorly with symptom severity", "DAO level alone does not track symptoms.", "smoke-agent")

    # The citation guard: a quote absent from the document is rejected (savepoint keeps the rest).
    try:
        with conn.transaction():
            L.add_evidence(conn, obs["id"], "claim", c2["id"], "SUPPORTS",
                           "DAO deficiency causes every case of HIT", "Invented.", "smoke-agent")
    except psycopg.errors.CheckViolation as err:
        assert "Quote not found" in str(err)
    else:
        raise AssertionError("a quote absent from the document must be rejected")

    k1 = L.add_contradiction(conn, "smoke", [c1["id"], c2["id"]],
                             "If DAO activity caused HIT, serum DAO should track symptoms.", "smoke-agent")
    assert k1["claim_ids"] == sorted([c1["id"], c2["id"]])
    try:
        L.add_contradiction(conn, "smoke", [c1["id"], c3["id"]], "Members from two collections.", "smoke-agent")
    except ValueError as err:
        assert "collection 'smoke'" in str(err)
    else:
        raise AssertionError("contradiction members must live in the finding's collection")

    hits = L.search_claims(conn, "smoke", "what causes histamine intolerance?", "vector", 5)
    assert hits["items"][0]["id"] == c1["id"], hits
    assert {e["id"] for e in hits["items"][0]["evidence"]} == {e1["id"], q1["id"]}
    assert hits["items"][0]["contradiction_ids"] == [k1["id"]]
    assert all(h["collection_id"] == "smoke" for h in hits["items"])
    kw = L.search_claims(conn, "smoke", "serum symptom", "keyword", 5)
    assert [h["id"] for h in kw["items"]] == [c2["id"]]

    assert L.list_observations(conn, "smoke", ungrounded_only=True) == []
    assert len(L.list_observations(conn, "smoke")) == 1
    assert L.get_record(conn, "observation", obs["id"], offset=10, max_chars=20)["content"] == DOC[10:30]
    assert L.search_contradictions(conn, "smoke", claim_id=c2["id"])[0]["claim_ids"] == k1["claim_ids"]

    proof = {"question": "Does DAO deficiency cause HIT?", "steps": [
        {"id": "s1", "say": "One review proposes reduced DAO activity as the mechanism.", "from": [c1["id"], e1["id"]]},
        {"id": "s2", "say": "A finding says this sits badly with poor serum correlation.", "from": [k1["id"]]},
        {"id": "s3", "say": "Nothing here covers children.", "from": [], "gap": True},
        {"id": "root", "say": "Proposed mechanism, not established; one finding is open on my reading.", "from": ["s1", "s2", "s3"]},
    ]}
    res = L.check_proof(conn, "smoke", proof)
    assert res["ok"], res["problems"]
    assert res["root"] == "root" and "(gap)" in res["tree"] and e1["quote"] in res["tree"]
    print(res["tree"])

    bad = {"steps": [
        {"id": "s1", "say": "Cites a record from another collection.", "from": [c3["id"]]},
        {"id": "s2", "say": "Cites nothing and is not a gap.", "from": []},
        {"id": "s3", "say": "Cites a made-up id.", "from": ["c_nope"]},
        {"id": "root", "say": "Answer.", "from": ["s1", "s2", "s3", "s5"]},
        {"id": "s5", "say": "Defined after it is used.", "from": [c1["id"]]},
    ]}
    res = L.check_proof(conn, "smoke", bad)
    text = "\n".join(res["problems"])
    for needle in ("belongs to collection 'other'", "s2: no ledger record", "c_nope is not a ledger record",
                   "not an earlier step", "exactly one root"):
        assert needle in text, (needle, res["problems"])
    print(json.dumps(res["problems"], indent=1))

    # Hostile or malformed shapes must come back as problems, never crash or loop.
    for shape in ([{"id": "a", "say": "x", "from": ["a"], "gap": True}],
                  [{"id": "a", "say": "x", "from": ["b"]}, {"id": "b", "say": "y", "from": ["a"]}],
                  [{"id": "a", "say": "x", "from": 5}, {"id": ["b"], "say": "y"}, {"id": "c", "say": 3, "from": [1]}],
                  [{"id": "a", "say": "x", "from": "c_abc"}]):
        res = L.check_proof(conn, "smoke", {"steps": shape})
        assert not res["ok"] and res["problems"], shape
    shared = [{"id": "s0", "say": "base", "from": [c1["id"]]}, {"id": "s1", "say": "one", "from": ["s0"]}]
    shared += [{"id": f"s{i}", "say": str(i), "from": [f"s{i-1}", f"s{i-2}"]} for i in range(2, 30)]
    res = L.check_proof(conn, "smoke", {"steps": shared})
    assert res["ok"] and res["tree"].count("\n") < 200, res["tree"].count("\n")


if __name__ == "__main__":
    main()
