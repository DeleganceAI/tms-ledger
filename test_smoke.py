"""End-to-end check of the ledger module against a live database and Ollama.

    TMS_DATABASE_URL=postgresql://tmsv2:tmsv2@localhost:5432/tmsv2_check uv run python test_smoke.py

Everything runs in one transaction and rolls back. Needs db/init.sql applied and Ollama serving
the embedding model. The one thing that must fail is a quote that is not in the document.
"""
import json
import re
import tempfile

import psycopg

from tms import ledger as L

DOC = """Histamine intolerance (HIT) is thought to result from reduced diamine oxidase (DAO) activity.
Serum DAO activity correlates poorly with symptom severity in several cohorts.
In one 2019 trial, DAO supplementation reduced symptom scores in adults with low serum DAO."""

LONG = ("Serum tryptase remained within the reference range in most patients at every visit, while urinary "
        "N-methylhistamine rose above the upper limit of normal in a minority, and neither marker tracked the "
        "symptom scores that patients reported in the weekly diaries kept throughout the twelve-month follow-up "
        "period of the study.")
JATS = f"""<?xml version="1.0"?><article><front><journal-meta><journal-title>Biomolecules</journal-title></journal-meta>
<article-meta><title-group><article-title>Diagnostic criteria for <italic>MCAS</italic>: a comparison</article-title></title-group>
<abstract><p>Two criteria sets are compared.</p></abstract></article-meta></front>
<body><sec><title>Results</title><p>{LONG}</p>
<table><tr><td>MCAS: CD25 on mast cells</td><td>WHO SM: CD25 on mast cells</td></tr></table><p>After the table.</p></sec></body>
<back><ref-list><ref><mixed-citation>Cited paper about zebras.</mixed-citation></ref></ref-list></back></article>"""


def main() -> None:
    with L.connect(autocommit=False) as conn:
        try:
            run(conn)
        finally:
            conn.rollback()
    print("PASS: smoke")


def run(conn) -> None:
    L.add_author(conn, "smoke-agent", "Smoke test agent", "agent")
    assert L.add_author(conn, "smoke-agent", "Smoke test agent", "agent")["id"] == "smoke-agent"  # idempotent
    try:
        with conn.transaction():
            L.add_author(conn, "smoke-agent", "Someone else", "agent")
    except psycopg.errors.UniqueViolation:
        pass
    else:
        raise AssertionError("the same id with a different name must still fail")
    L.add_collection(conn, "smoke", "Smoke collection", "smoke-agent")
    L.add_collection(conn, "other", "Other collection", "smoke-agent")
    src = L.add_source(conn, "Example journal", "smoke-agent", "https://example.org")
    obs = L.add_observation(conn, "smoke", src["id"], "smoke-agent", "https://example.org/hit-review", DOC)
    assert obs["chars"] == len(DOC) and "content" not in obs
    assert obs["title"] == DOC.splitlines()[0]  # plain text: first line

    # JATS: title from <article-title>; journal metadata and bibliography dropped; table cells kept apart.
    with tempfile.NamedTemporaryFile("w", suffix=".xml") as f:
        f.write(JATS)
        f.flush()
        text, title = L.fetch_text(f.name)
        obs2 = L.add_observation(conn, "smoke", src["id"], "smoke-agent", f.name)
    assert title == "Diagnostic criteria for MCAS: a comparison" and obs2["title"] == title, (title, obs2)
    assert "zebras" not in text and "Biomolecules" not in text and "Two criteria sets" in text, text
    assert re.search(r"MCAS: CD25 on mast cells\t\s*WHO SM: CD25 on mast cells\t\s*\n", text), text
    assert L.get_record(conn, "observation", obs2["id"], max_chars=0)["title"] == title
    obs3 = L.add_observation(conn, "smoke", src["id"], "smoke-agent", "x", "body", title="Given")
    assert obs3["title"] == "Given"

    c1 = L.add_claim(conn, "smoke", "Histamine intolerance results from reduced DAO activity.", "smoke-agent")
    c2 = L.add_claim(conn, "smoke", "Serum DAO activity correlates poorly with symptom severity.", "smoke-agent")
    c3 = L.add_claim(conn, "other", "An unrelated claim in another collection.", "smoke-agent")

    e1 = L.add_evidence(conn, obs["id"], "claim", c1["id"], "SUPPORTS",
                        "thought to result from reduced diamine oxidase (DAO) activity",
                        "The review names reduced DAO activity as the proposed mechanism.", "smoke-agent")
    assert e1["target_id"] == c1["id"] and "target_claim_id" not in e1
    q1 = L.add_evidence(conn, obs["id"], "claim", c1["id"], "QUALIFIES",
                        "correlates poorly with symptom severity", "DAO level alone does not track symptoms.", "smoke-agent")
    e2 = L.add_evidence(conn, obs2["id"], "claim", c2["id"], "SUPPORTS", LONG, "Markers did not track symptoms.", "smoke-agent")

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
    short = next(e for e in kw["items"][0]["evidence"] if e["id"] == e2["id"])["quote"]
    assert short == LONG[:300] + "…" and L.get_record(conn, "evidence", e2["id"])["quote"] == LONG  # search truncates, reads do not

    assert [o["id"] for o in L.list_observations(conn, "smoke", ungrounded_only=True)] == [obs3["id"]]
    assert {o["title"] for o in L.list_observations(conn, "smoke")} == {obs["title"], title, "Given"}
    assert L.get_record(conn, "observation", obs["id"], offset=10, max_chars=20)["content"] == DOC[10:30]
    assert L.search_contradictions(conn, "smoke", claim_id=c2["id"])[0]["claim_ids"] == k1["claim_ids"]

    proof = {"question": "Does DAO deficiency cause HIT?", "steps": [
        {"id": "s1", "say": "One review proposes reduced DAO activity as the mechanism.", "from": [c1["id"], e1["id"], obs2["id"]]},
        {"id": "s2", "say": "A finding says this sits badly with poor serum correlation.", "from": [k1["id"]]},
        {"id": "s3", "say": "Nothing here covers children.", "from": [], "gap": True},
        {"id": "root", "say": "Proposed mechanism, not established; one finding is open on my reading.", "from": ["s1", "s2", "s3"]},
    ]}
    res = L.check_proof(conn, "smoke", proof)
    assert res["ok"], res["problems"]
    assert res["root"] == "root" and "(gap)" in res["tree"] and e1["quote"] in res["tree"]
    assert f'observation "{title}" ' in res["tree"], res["tree"]
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

    thin = L.list_claims(conn, "smoke", "unsupported")
    totals = [t["supports"] + t["qualifies"] + t["rebuts"] for t in thin]
    assert totals == sorted(totals) and {t["id"] for t in thin} == {c1["id"], c2["id"]}, thin
    top = L.list_claims(conn, "smoke", "unchallenged")[0]
    assert top["rebuts"] + top["qualifies"] == 0 and top["findings"] == 1, top

    # Telemetry and the dashboard's queries run against the same connection.
    from tms import ui
    L.log_call(conn, "tools/call", "add_claim", "smoke-agent", "smoke", True, None, 12)
    L.log_call(conn, "tools/call", "add_evidence", "smoke-agent", "smoke", False, "Quote not found verbatim", 8)
    snap = ui.snapshot(conn)
    assert snap["counts"]["claims"] >= 3 and snap["calls"]["errors"] >= 1
    assert any(t["name"] == "add_claim" for t in snap["by_tool"])
    assert snap["recent_records"][0]["kind"] in {"contradiction", "evidence", "claim", "observation", "source", "collection", "author"}
    assert any(r["author_id"] == "smoke-agent" for r in snap["by_author"])
    cols = ui.collections(conn)
    mine = next(c for c in cols["collections"] if c["id"] == "smoke")
    assert (mine["sources"], mine["observations"], mine["claims"], mine["evidence"], mine["contributors"]) == (1, 3, 2, 3, 1), mine
    assert mine["bytes"] > 0 and mine["last_at"] and cols["db_bytes"] > 0, mine
    assert any(t["name"] == "observations" and t["bytes"] > 0 for t in cols["tables"])


if __name__ == "__main__":
    main()
