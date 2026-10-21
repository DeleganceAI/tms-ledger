"""Smoke test against a running service (local or deployed), over plain HTTP.

    uv run python smoke_live.py https://tms.example.com            # open checks only
    TMS_NSEC=nsec1... uv run python smoke_live.py https://...      # plus signed reads as that key

The key in TMS_NSEC must be approved or a member of some collection. Nothing is written.
"""
import json
import sys

import httpx

from tms import events as E


def main() -> None:
    import os
    base = sys.argv[1].rstrip("/")
    http = httpx.Client(base_url=base, timeout=30)
    n = iter(range(1, 1000))

    def call(name, arguments):
        r = http.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                      json={"jsonrpc": "2.0", "id": next(n), "method": "tools/call",
                            "params": {"name": name, "arguments": arguments}})
        r.raise_for_status()
        return r.json()["result"]

    assert http.get("/healthz").text == "ok", "healthz"
    assert "Connect" in http.get("/").text, "home page"
    r = http.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                  json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
    tools = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"publish", "search_claims", "get_event"} <= tools, tools
    stranger = E.sign(os.urandom(32), E.REQUEST, {"tool": "list_collections", "args": {}})
    res = call("list_collections", {"request": stranger})
    assert res.get("isError") and "not approved" in res["content"][0]["text"], res
    assert http.post("/login", json=E.request(os.urandom(32), "login")).status_code == 403
    assert http.get("/api/me").status_code == 401 and http.get("/dashboard/api/snapshot").status_code == 401
    print(f"open checks passed: {len(tools)} tools")

    if os.environ.get("TMS_NSEC"):
        sk = os.environ["TMS_NSEC"]
        res = call("list_collections", {"request": E.request(sk, "list_collections")})
        assert not res.get("isError"), res
        cols = res["structuredContent"]["result"]
        print("collections:", [c["slug"] for c in cols])
        replay = E.request(sk, "list_collections")
        call("list_collections", {"request": replay})
        assert "already used" in call("list_collections", {"request": replay})["content"][0]["text"]
        r = http.post("/login", json=E.request(sk, "login"))
        assert r.status_code == 200 and http.get("/api/me").json()["pubkey"] == E.pubkey_of(sk)
        if cols:
            lines = http.get(f"/c/{cols[0]['slug']}/export.jsonl").text.splitlines()
            for line in lines:
                E.verify(json.loads(line))
            print(f"export of {cols[0]['slug']}: {len(lines)} events verify")
        assert http.get("/dashboard").status_code == 200
        print("signed checks passed")
    print("PASS: live smoke")


if __name__ == "__main__":
    main()
