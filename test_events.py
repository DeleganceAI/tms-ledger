"""Phase 1 check: tms/events.py agrees with nostr-tools on IDs and signatures.

    (cd check && npm install) && uv run python test_events.py
"""
import json
import subprocess

from tms import events as E

SK = "7f7ff03d123792d6ac594bfa67bf6d0c0ab55b6b1fdb6249303fe861f1ccba9a"
PROFILE_TAGS = [["alt", "User profile: Ünï \n"], ["client", "Damus", "31990:abc"], ["i", "github:x", "proof"]]
PROFILE = '{"name":"Tagged","about":"from a relay"}'
TRICKY = [
    "plain ascii",
    "Ünïcödé — “quotes” ﬁ ligature 中文 עברית 🧪👩🏽‍🔬",
    "controls: \x00\x01\x07\x08\t\n\x0b\x0c\r\x1b\x1f\x7f end",
    'quote " backslash \\ slash /     ﻿ ­',
    json.dumps({"collection": "mcas", "text": "Line one\nLine two\ttab \"q\" \\ \x1f 💥"}, ensure_ascii=False),
    "",
]


def main() -> None:
    py = [E.sign(SK, k, c, created_at=1792454400 + i) for i, (k, c) in enumerate(
        [(1, t) for t in TRICKY] + [(E.CLAIM, {"collection": "smoke", "text": "Ünï\x01\n🧪"})])]
    py.append(E.sign(SK, E.PROFILE, PROFILE, created_at=1792454400, tags=PROFILE_TAGS))
    todo = [{"sk": SK, "kind": 1, "content": t, "created_at": 1792454400} for t in TRICKY]
    todo.append({"sk": SK, "kind": 0, "content": PROFILE, "created_at": 1792454400, "tags": PROFILE_TAGS})
    res = json.loads(subprocess.run(["node", "check/nostr.mjs"], input=json.dumps({"python": py, "sign": todo}),
                                    capture_output=True, text=True, check=True).stdout)
    for ev, js in zip(py, res["python"]):
        assert js["id"] == ev["id"] and js["ok"], (ev, js)
    for ev in res["signed"]:
        assert ev["id"] == E.event_id(ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]), ev
        assert ev["pubkey"] == E.pubkey_of(SK)
        if ev["kind"] == E.PROFILE:  # a tagged profile signed by nostr-tools verifies in full
            assert E.verify(ev)["name"] == "Tagged" and ev["tags"] == PROFILE_TAGS
            continue
        try:
            E.verify(ev)
        except E.Invalid as err:  # kind 1 is not a TMS kind: everything before content must pass
            assert "kind 1 is not a TMS kind" in str(err), err

    # Python's own checks
    claim = E.sign(SK, E.CLAIM, {"collection": "smoke", "text": "x"})
    assert E.verify(claim) == {"collection": "smoke", "text": "x"}
    for bad, why in [
        ({**claim, "sig": claim["sig"][:-1] + ("0" if claim["sig"][-1] != "0" else "1")}, "signature"),
        ({**claim, "content": claim["content"].replace("x", "y")}, "id does not match"),
        ({**claim, "tags": [["t", "x"]]}, "only profiles may carry tags"),
        (E.sign(SK, E.PROFILE, {"name": "n"}, tags=[["t", 1]]), "profile tags must be"),
        (E.sign(SK, E.PROFILE, {"name": "n"}, tags=[[]]), "profile tags must be"),
        (E.sign(SK, E.PROFILE, {"name": "n"}, tags=[["t", "a\x00"]]), "profile tags must be"),
        (E.sign(SK, E.CLAIM, {"collection": "smoke", "text": "x", "extra": 1}), "unknown fields"),
        (E.sign(SK, E.CLAIM, {"collection": "Bad Slug", "text": "x"}), "'collection'"),
        (E.sign(SK, E.CLAIM, {"collection": "smoke", "text": "  "}), "'text'"),
        (E.sign(SK, E.CLAIM, '{"collection":"smoke","text":"a\\u0000b"}'), "U+0000"),
        (E.sign(SK, E.CLAIM, "[1]"), "JSON object"),
        (E.sign(SK, E.CLAIM, '{"collection":"smoke","text":NaN}'), "not JSON"),
        (E.sign(SK, E.CONTRADICTION, {"collection": "s", "claims": ["a" * 64, "a" * 64], "reason": "r"}), "'claims'"),
        (E.sign(SK, E.LINK, {"collection": "s", "from": "a" * 64, "to": "b" * 64, "relation": "CAUSES",
                             "quote": "q", "reason": "r"}), "'relation'"),
        (E.sign(SK, 4720, {}), "not a TMS kind"),
        (E.sign(SK, E.ADMINS, {"collection": "s", "admins": ["aa"]}), "'admins'"),
        (E.sign(SK, E.ADMINS, {"collection": "s", "admins": ["ab" * 32, "ab" * 32]}), "'admins'"),
        (E.sign(SK, E.STEWARDS, {"stewards": ["not-a-key"]}), "'stewards'"),
        (E.sign(SK, E.FOUND, {"collection": "s", "owner": "zz"}), "'owner'"),
    ]:
        try:
            E.verify(bad)
        except E.Invalid as err:
            assert why in str(err), (why, err)
        else:
            raise AssertionError(f"accepted: {why}")
    assert E.verify(E.sign(SK, E.PROFILE, {"name": "n", "display_name": "extra fields allowed"}))
    pk = "ab" * 32
    assert E.verify(E.sign(SK, E.ADMINS, {"collection": "s", "admins": []}))["admins"] == []
    assert E.verify(E.sign(SK, E.ADMINS, {"collection": "s", "admins": [pk]}))["admins"] == [pk]
    assert E.verify(E.sign(SK, E.STEWARDS, {"stewards": [pk]}))["stewards"] == [pk]
    assert E.verify(E.sign(SK, E.FOUND, {"collection": "s", "owner": pk}))["owner"] == pk

    # NIP-19: the published test vector, and a round trip
    npub = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptg"
    assert E.pubkey_hex(npub) == "7e7e9c42a91bfef19fa929e5fda1b72e0ebc1a4c1141673e2794234d86addf4e"
    assert E.bech32_encode("npub", E.pubkey_hex(npub)) == npub
    nsec = E.bech32_encode("nsec", SK)
    assert E.secret_bytes(nsec).hex() == SK
    print("PASS: events match nostr-tools")


if __name__ == "__main__":
    main()
