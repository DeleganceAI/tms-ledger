"""Signed events (EVENTS.md): NIP-01 envelope and ID, BIP-340 signatures, per-kind content rules.

    tms-sign keygen                       new key: nsec, npub and both as hex
    tms-sign pubkey                       the pubkey of TMS_NSEC
    tms-sign event KIND [CONTENT_JSON]    sign one event with TMS_NSEC (content from stdin if omitted)
    tms-sign request TOOL [ARGS_JSON]     sign a tool-call request (kind 4707) with TMS_NSEC

TMS_NSEC holds the signer's secret key, as nsec1... or 64 hex characters.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time

from coincurve import PrivateKey, PublicKeyXOnly

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX128 = re.compile(r"^[0-9a-f]{128}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RELATIONS = ("SUPPORTS", "REBUTS", "QUALIFIES")

PROFILE, EVIDENCE, CLAIM, LINK, CONTRADICTION, MEMBERS, TERMS, REQUEST, SNAPSHOT, ABOUT = (
    0, 4701, 4702, 4703, 4704, 4705, 4706, 4707, 4708, 4709)
# 4710 admins: per-collection managers. 4711 stewards: account-level create grant.
# 4712 found: a steward opens a collection owned by the grantor.
ADMINS, STEWARDS, FOUND = 4710, 4711, 4712
TOPIC_MAX = 140  # characters in a collection's public topic line


class Invalid(ValueError):
    """An event the server must not accept. The message says why."""


# ------------------------------------------------------------ field checks

def _text(v):
    return isinstance(v, str) and v.strip() != ""


def _opt_text(v):
    return isinstance(v, str)


def _slug(v):
    return isinstance(v, str) and SLUG.match(v) is not None


def _id(v):
    return isinstance(v, str) and HEX64.match(v) is not None


def _ids(v):  # contradiction members: at least two distinct event IDs
    return isinstance(v, list) and len(v) >= 2 and all(map(_id, v)) and len(set(v)) == len(v)


def _pubkeys(v):
    return isinstance(v, list) and all(map(_id, v))


def _distinct_pubkeys(v):  # admin and steward lists: no duplicates, so a role can't be listed twice
    return _pubkeys(v) and len(set(v)) == len(v)


def _relation(v):
    return v in RELATIONS


def _object(v):
    return isinstance(v, dict)


def _topic(v):
    return _text(v) and len(v) <= TOPIC_MAX


def _bool(v):
    return isinstance(v, bool)


def _count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


# kind -> (name, required fields, optional fields); each field maps to its check.
KINDS = {
    PROFILE: ("profile", {"name": _text}, {"about": _opt_text, "picture": _opt_text}),
    EVIDENCE: ("evidence", {"collection": _slug, "text": _text},
               {"url": _opt_text, "title": _opt_text, "source": _opt_text,
                "archive_url": _opt_text, "retrieved_via": _opt_text}),
    CLAIM: ("claim", {"collection": _slug, "text": _text}, {}),
    LINK: ("link", {"collection": _slug, "from": _id, "to": _id, "relation": _relation,
                    "quote": _text, "reason": _text}, {}),
    CONTRADICTION: ("contradiction", {"collection": _slug, "claims": _ids, "reason": _text}, {}),
    MEMBERS: ("members", {"collection": _slug, "members": _pubkeys}, {}),
    # owner only, latest wins: who may change members and about. The owner is never in this list.
    ADMINS: ("admins", {"collection": _slug, "admins": _distinct_pubkeys}, {}),
    # approved signer only, no collection, latest per signer wins: who may create collections they own
    STEWARDS: ("stewards", {"stewards": _distinct_pubkeys}, {}),
    # a steward opens a collection owned by the grantor named in `owner`; the signer becomes its admin
    FOUND: ("found", {"collection": _slug, "owner": _id}, {}),
    TERMS: ("terms", {"version": _text, "sha256": _id}, {}),
    # nonce: any string, so two identical calls signed in the same second get different ids
    REQUEST: ("request", {"tool": _text, "args": _object}, {"nonce": _opt_text}),
    SNAPSHOT: ("snapshot", {"date": _text, "cid": _text, "sha256": _id, "count": _count,
                            "last_received_at": _text}, {}),
    # owner only, latest wins: a one-line topic, and whether the Communities page may show the
    # collection's name, topic and record counts (never its records)
    ABOUT: ("about", {"collection": _slug, "topic": _topic, "public": _bool}, {}),
}
NAMES = {kind: spec[0] for kind, spec in KINDS.items()}
STORED = frozenset(KINDS) - {REQUEST}


def _no_constants(c):
    raise ValueError(f"{c} is not JSON")


def _tags_ok(v) -> bool:  # profiles only: a list of non-empty string lists, as NIP-01 shapes them
    return isinstance(v, list) and all(isinstance(t, list) and t and all(isinstance(x, str) for x in t) for t in v)


def _has_nul(v) -> bool:  # Postgres text and jsonb cannot hold U+0000
    if isinstance(v, str):
        return "\x00" in v
    if isinstance(v, dict):
        return any(_has_nul(k) or _has_nul(x) for k, x in v.items())
    if isinstance(v, list):
        return any(map(_has_nul, v))
    return False


def parse_content(kind: int, content: str) -> dict:
    """The content object for this kind, or Invalid. Unknown fields are rejected except on profiles."""
    if kind not in KINDS:
        raise Invalid(f"kind {kind} is not a TMS kind")
    name, required, optional = KINDS[kind]
    try:
        data = json.loads(content, parse_constant=_no_constants)
    except ValueError as err:
        raise Invalid(f"{name} content is not JSON: {err}") from None
    if not isinstance(data, dict):
        raise Invalid(f"{name} content must be a JSON object")
    if _has_nul(data):
        raise Invalid(f"{name} content contains U+0000")
    missing = [f for f in required if f not in data]
    if missing:
        raise Invalid(f"{name} content is missing {', '.join(missing)}")
    unknown = [f for f in data if f not in required and f not in optional]
    if unknown and kind != PROFILE:
        raise Invalid(f"{name} content has unknown fields: {', '.join(unknown)}")
    for f, ok in (required | optional).items():
        if f in data and not ok(data[f]):
            raise Invalid(f"{name} field '{f}' is invalid")
    return data


# --------------------------------------------------------------- envelope

def serialize(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> bytes:
    """NIP-01 serialization: no whitespace, JSON.stringify escaping, UTF-8."""
    return json.dumps([0, pubkey, created_at, kind, tags, content],
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def event_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    return hashlib.sha256(serialize(pubkey, created_at, kind, tags, content)).hexdigest()


def verify(ev) -> dict:
    """Check the envelope, ID, signature and content shape. Returns the parsed content."""
    if not isinstance(ev, dict):
        raise Invalid("an event must be a JSON object")
    eid = ev.get("id")
    label = eid if isinstance(eid, str) else "event"
    pubkey, created_at, kind, tags, content, sig = (
        ev.get(k) for k in ("pubkey", "created_at", "kind", "tags", "content", "sig"))
    if not (_id(eid) and _id(pubkey) and isinstance(sig, str) and HEX128.match(sig)):
        raise Invalid(f"{label}: id, pubkey and sig must be lowercase hex of 32, 32 and 64 bytes")
    if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at < 0:
        raise Invalid(f"{label}: created_at must be a non-negative integer")
    if not isinstance(kind, int) or isinstance(kind, bool) or not 0 <= kind <= 65535:
        raise Invalid(f"{label}: kind must be an integer 0-65535")
    if kind == PROFILE:  # profiles come from other clients; their tags are kept as signed and ignored
        if not _tags_ok(tags) or _has_nul(tags):
            raise Invalid(f"{label}: profile tags must be a list of non-empty lists of strings")
    elif tags != []:
        raise Invalid(f"{label}: tags must be [] (only profiles may carry tags)")
    if not isinstance(content, str):
        raise Invalid(f"{label}: content must be a string")
    try:
        computed = event_id(pubkey, created_at, kind, tags, content)
    except UnicodeEncodeError:
        raise Invalid(f"{label}: content is not valid Unicode") from None
    if computed != eid:
        raise Invalid(f"{label}: id does not match the event's serialization")
    try:
        good = PublicKeyXOnly(bytes.fromhex(pubkey)).verify(bytes.fromhex(sig), bytes.fromhex(eid))
    except ValueError:
        good = False
    if not good:
        raise Invalid(f"{label}: signature does not verify for pubkey {pubkey}")
    try:
        return parse_content(kind, content)
    except Invalid as err:
        raise Invalid(f"{label}: {err}") from None


def sign(secret: str | bytes, kind: int, content: dict | str, created_at: int | None = None,
         tags: list | None = None) -> dict:
    """A signed event. content may be an object (serialized compactly) or the exact string."""
    sk = PrivateKey(secret if isinstance(secret, bytes) else secret_bytes(secret))
    pubkey = PublicKeyXOnly.from_secret(sk.secret).format().hex()
    if not isinstance(content, str):
        content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)
    created_at = int(time.time()) if created_at is None else created_at
    tags = tags or []
    eid = event_id(pubkey, created_at, kind, tags, content)
    sig = sk.sign_schnorr(bytes.fromhex(eid), os.urandom(32)).hex()
    return {"id": eid, "pubkey": pubkey, "created_at": created_at, "kind": kind, "tags": tags,
            "content": content, "sig": sig}


def request(secret, tool: str, args: dict | None = None) -> dict:
    return sign(secret, REQUEST, {"tool": tool, "args": args or {}, "nonce": os.urandom(8).hex()})


def pubkey_of(secret) -> str:
    sk = PrivateKey(secret if isinstance(secret, bytes) else secret_bytes(secret))
    return PublicKeyXOnly.from_secret(sk.secret).format().hex()


# ------------------------------------------------------------------ bech32 (NIP-19 npub/nsec only)

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i, g in enumerate((0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)):
            chk ^= g if (top >> i) & 1 else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert(data, frm, to, pad):
    acc = bits = 0
    out = []
    for v in data:
        acc = (acc << frm) | v
        bits += frm
        while bits >= to:
            bits -= to
            out.append((acc >> bits) & ((1 << to) - 1))
    if pad and bits:
        out.append((acc << (to - bits)) & ((1 << to) - 1))
    elif not pad and (bits >= frm or (acc << (to - bits)) & ((1 << to) - 1)):
        raise ValueError("invalid bech32 padding")
    return out


def bech32_encode(hrp: str, hexkey: str) -> str:
    data = _convert(bytes.fromhex(hexkey), 8, 5, True)
    pm = _polymod(_hrp_expand(hrp) + data + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CHARSET[d] for d in data + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


def bech32_decode(hrp: str, s: str) -> str:
    s = s.strip().lower()
    if not s.startswith(hrp + "1"):
        raise ValueError(f"expected {hrp}1...")
    try:
        data = [_CHARSET.index(c) for c in s[len(hrp) + 1:]]
    except ValueError:
        raise ValueError("invalid bech32 character") from None
    if len(data) < 6 or _polymod(_hrp_expand(hrp) + data) != 1:
        raise ValueError("invalid bech32 checksum")
    raw = bytes(_convert(data[:-6], 5, 8, False))
    if len(raw) != 32:
        raise ValueError("expected a 32-byte key")
    return raw.hex()


def secret_bytes(s: str) -> bytes:
    s = s.strip()
    return bytes.fromhex(bech32_decode("nsec", s) if s.startswith("nsec") else s)


def pubkey_hex(s: str) -> str:
    """npub1... or hex -> lowercase hex pubkey."""
    s = s.strip()
    h = bech32_decode("npub", s) if s.startswith("npub") else s.lower()
    if not HEX64.match(h):
        raise ValueError(f"not a pubkey: {s}")
    return h


# --------------------------------------------------------------------- CLI

def _env_secret() -> str:
    s = os.environ.get("TMS_NSEC", "")
    if not s:
        sys.exit("set TMS_NSEC to your secret key (nsec1... or hex)")
    return s


def main(argv: list[str] | None = None) -> None:
    a = sys.argv[1:] if argv is None else argv
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    if a[0] == "keygen":
        sk = PrivateKey()
        pk = PublicKeyXOnly.from_secret(sk.secret).format().hex()
        print(json.dumps({"nsec": bech32_encode("nsec", sk.secret.hex()), "secret_hex": sk.secret.hex(),
                          "npub": bech32_encode("npub", pk), "pubkey": pk}, indent=1))
    elif a[0] == "pubkey":
        print(pubkey_of(_env_secret()))
    elif a[0] == "event" and len(a) in (2, 3):
        content = json.loads(a[2] if len(a) == 3 else sys.stdin.read())
        ev = sign(_env_secret(), int(a[1]), content)
        verify(ev)  # refuse to print an event the server would reject on shape alone
        print(json.dumps(ev, ensure_ascii=False))
    elif a[0] == "request" and len(a) in (2, 3):
        print(json.dumps(request(_env_secret(), a[1], json.loads(a[2]) if len(a) == 3 else {}), ensure_ascii=False))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
