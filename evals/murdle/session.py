"""One puzzle's collection, held in memory as signed TMS events.

The records are real kind 4701–4704 events: ``tms.events`` signs and verifies them.
Acceptance matches the mechanical rules in EVENTS.md and db/init.sql: the signature
checks, a link quotes its evidence verbatim (same folding as ``normalize_quote``),
and references point at earlier records in this collection. A failed event rolls
the whole batch back.

This is not the Postgres ledger. It does not check terms, approval, or membership,
it does not embed claims, and ``search_claims(method="vector")`` falls back to
keyword overlap. Those gaps are deliberate so the eval runs with no database and
no API key. The README lists them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from coincurve import PrivateKey

from tms import events as E

from evals.murdle.quote import normalize_quote, quote_in_evidence

_STORED = (E.PROFILE, E.EVIDENCE, E.CLAIM, E.LINK, E.CONTRADICTION)
_LINK_TARGETS = (E.EVIDENCE, E.CLAIM, E.LINK, E.CONTRADICTION)
_SORTS = ("recent", "oldest", "links", "unsupported", "unchallenged", "contested")


@dataclass
class _Rec:
    event: dict
    content: dict
    received_at: int


def _bound(name: str, value, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer from {lo} to {hi}")
    return value


class EvalCollection:
    """The tool surface an agent sees for one puzzle."""

    def __init__(self, collection: str, secret: bytes | str | None = None):
        if not isinstance(collection, str) or E.SLUG.match(collection) is None:
            raise ValueError(f"collection slug {collection!r} is not a tms slug")
        if secret is None:
            secret = PrivateKey().secret
        elif isinstance(secret, str):
            secret = E.secret_bytes(secret)
        self.collection = collection
        self.secret = secret
        self.pubkey = E.pubkey_of(secret)
        self.tool_calls = 0
        self.rejected_links = 0
        self.loaded_clues = 0
        self._time = 1_800_000_000
        self._order: list[str] = []
        self._by_id: dict[str, _Rec] = {}
        self._commit([self._sign(E.PROFILE, {"name": "eval-agent", "about": "agent"})])

    # ----------------------------------------------------------------- signing

    def _sign(self, kind: int, content: dict) -> dict:
        self._time += 1
        return E.sign(self.secret, kind, content, created_at=self._time)

    def _commit(self, events: list) -> dict:
        if not isinstance(events, list) or not events:
            raise E.Invalid("events must be a non-empty list of signed events")
        saved_order, saved_map = list(self._order), dict(self._by_id)
        accepted, skipped = [], []
        try:
            for ev in events:
                if isinstance(ev, dict) and ev.get("id") in self._by_id:
                    skipped.append(ev["id"])
                    continue
                self._check(ev)
                content = json.loads(ev["content"])
                self._by_id[ev["id"]] = _Rec(ev, content, ev["created_at"])
                self._order.append(ev["id"])
                accepted.append(ev["id"])
        except Exception:
            self._order, self._by_id = saved_order, saved_map
            raise
        return {"accepted": accepted, "skipped": skipped, "collections": [self.collection]}

    def _check(self, ev: dict) -> None:
        content = E.verify(ev)
        kind = ev["kind"]
        if kind not in _STORED:
            raise E.Invalid(f"{ev['id']}: this eval collection stores evidence, claims, links, contradictions, and a profile")
        if kind == E.PROFILE:
            return
        if content["collection"] != self.collection:
            raise E.Invalid(f"{ev['id']}: collection must be {self.collection}")
        if kind == E.LINK:
            self._check_link(ev["id"], content)
        elif kind == E.CONTRADICTION:
            for cid in content["claims"]:
                target = self._by_id.get(cid)
                if target is None or target.event["kind"] != E.CLAIM or target.content["collection"] != self.collection:
                    raise E.Invalid(f"contradiction {ev['id']}: {cid} is not a claim in collection {self.collection}")

    def _check_link(self, eid: str, content: dict) -> None:
        try:
            source = self._by_id.get(content["from"])
            if source is None or source.event["kind"] != E.EVIDENCE or source.content["collection"] != self.collection:
                raise E.Invalid(f"link {eid}: from must be an evidence event in collection {self.collection}")
            if normalize_quote(content["quote"]) == "":
                raise E.Invalid(f"link {eid}: quote is blank after normalisation")
            if not quote_in_evidence(content["quote"], source.content["text"]):
                raise E.Invalid(f"link {eid}: quote not found verbatim in evidence {content['from']}")
            target = self._by_id.get(content["to"])
            if target is None or target.event["kind"] not in _LINK_TARGETS or target.content.get("collection") != self.collection:
                raise E.Invalid(f"link {eid}: to must be an evidence, claim, link, or contradiction in collection {self.collection}")
            if content["relation"] == "QUALIFIES" and target.event["kind"] != E.CLAIM:
                raise E.Invalid(f"link {eid}: QUALIFIES may only target a claim")
        except E.Invalid:
            self.rejected_links += 1
            raise

    def signed_events(self) -> list[dict]:
        return [self._by_id[i].event for i in self._order]

    def records(self, kind: int | None = None) -> list[dict]:
        """Parsed records in arrival order. Not an agent tool."""
        out = []
        for eid in self._order:
            rec = self._by_id[eid]
            if kind is not None and rec.event["kind"] != kind:
                continue
            out.append({"id": eid, "kind": rec.event["kind"], "pubkey": rec.event["pubkey"],
                        "content": rec.content, "received_at": rec.received_at})
        return out

    def _kind(self, kind: int) -> list[_Rec]:
        return [self._by_id[i] for i in self._order if self._by_id[i].event["kind"] == kind]

    def _author(self, pubkey: str) -> str | None:
        name = None
        for rec in self._kind(E.PROFILE):
            if rec.event["pubkey"] == pubkey and rec.content.get("name"):
                name = rec.content["name"]
        return name

    def _touch(self, count: bool) -> None:
        if count:
            self.tool_calls += 1

    # ------------------------------------------------------------------- setup

    def load_puzzle(self, puzzle) -> list[str]:
        """Store each clue as an evidence document. Setup, not an agent tool call."""
        ids = []
        for clue in puzzle.clues:
            ev = self._sign(E.EVIDENCE, {
                "collection": self.collection, "title": f"Clue {clue.id}",
                "source": puzzle.id, "text": clue.text})
            self._commit([ev])
            ids.append(ev["id"])
        self.loaded_clues = len(ids)
        return ids

    # -------------------------------------------------------------------- tools

    def publish(self, events: list) -> dict:
        """Append a batch of already-signed events, all or nothing."""
        self.tool_calls += 1
        return self._commit(events)

    def add_claim(self, text: str) -> dict:
        """Sign and store a claim. Returns the event view, including its id."""
        self.tool_calls += 1
        ev = self._sign(E.CLAIM, {"collection": self.collection, "text": text})
        self._commit([ev])
        return self.get_event(ev["id"], count=False)

    def add_link(self, from_id: str, to_id: str, relation: str, quote: str, reason: str) -> dict:
        """Sign and store a link. ``quote`` must appear in the evidence ``from_id``."""
        self.tool_calls += 1
        ev = self._sign(E.LINK, {
            "collection": self.collection, "from": from_id, "to": to_id,
            "relation": relation, "quote": quote, "reason": reason})
        self._commit([ev])
        return self.get_event(ev["id"], count=False)

    def add_contradiction(self, claim_ids: list[str], reason: str) -> dict:
        """Sign and store a contradiction naming at least two claim ids."""
        self.tool_calls += 1
        ev = self._sign(E.CONTRADICTION, {"collection": self.collection, "claims": list(claim_ids), "reason": reason})
        self._commit([ev])
        return self.get_event(ev["id"], count=False)

    def get_event(self, id: str = "", offset: int = 0, max_chars: int = 20000, *, count: bool = True):
        """One event by id. Evidence text is a window; ``chars`` is the full length."""
        self._touch(count)
        if not isinstance(id, str) or not id:
            raise ValueError("id is required")
        rec = self._by_id.get(id)
        if rec is None:
            return None
        data = dict(rec.content)
        out = {
            "id": rec.event["id"], "pubkey": rec.event["pubkey"], "kind": rec.event["kind"],
            "collection": data.get("collection"), "created_at": rec.event["created_at"],
            "received_at": rec.received_at, "kind_name": E.NAMES[rec.event["kind"]],
            "author": self._author(rec.event["pubkey"]), "content": data,
        }
        if rec.event["kind"] == E.EVIDENCE:
            offset = _bound("offset", offset, 0, 1_000_000)
            max_chars = _bound("max_chars", max_chars, 0, 50_000)
            text = rec.content["text"]
            data["text"] = text[offset:offset + max_chars]
            out["chars"] = len(text)
            out["offset"] = offset
        return out

    def list_evidence(self, ungrounded_only: bool = False, source: str = "", limit: int = 50,
                      offset: int = 0, *, count: bool = True) -> list[dict]:
        """Evidence documents, oldest first, without their text."""
        self._touch(count)
        if not isinstance(ungrounded_only, bool):
            raise ValueError("ungrounded_only must be a boolean")
        limit, offset = _bound("limit", limit, 1, 500), _bound("offset", offset, 0, 1_000_000)
        cited = {rec.content["from"] for rec in self._kind(E.LINK)}
        rows = []
        for rec in self._kind(E.EVIDENCE):
            src = rec.content.get("source") or ""
            if source and source.lower() not in src.lower():
                continue
            if ungrounded_only and rec.event["id"] in cited:
                continue
            rows.append({
                "id": rec.event["id"], "pubkey": rec.event["pubkey"], "author": self._author(rec.event["pubkey"]),
                "title": rec.content.get("title") or "", "url": rec.content.get("url") or "", "source": src,
                "received_at": rec.received_at, "chars": len(rec.content["text"]),
                "link_count": sum(1 for link in self._kind(E.LINK) if link.content["from"] == rec.event["id"]),
            })
        return rows[offset:offset + limit]

    def _link_view(self, rec: _Rec, trim: bool) -> dict:
        quote = rec.content["quote"]
        if trim and len(quote) > 300:
            quote = quote[:300] + "…"
        return {
            "id": rec.event["id"], "pubkey": rec.event["pubkey"], "author": self._author(rec.event["pubkey"]),
            "from": rec.content["from"], "to": rec.content["to"], "relation": rec.content["relation"],
            "quote": quote, "reason": rec.content["reason"], "received_at": rec.received_at,
        }

    def _claim_counts(self, cid: str) -> dict[str, int]:
        supports = qualifies = rebuts = 0
        for link in self._kind(E.LINK):
            if link.content["to"] != cid:
                continue
            if link.content["relation"] == "SUPPORTS":
                supports += 1
            elif link.content["relation"] == "QUALIFIES":
                qualifies += 1
            elif link.content["relation"] == "REBUTS":
                rebuts += 1
        findings = sum(1 for rec in self._kind(E.CONTRADICTION) if cid in rec.content["claims"])
        return {"supports": supports, "qualifies": qualifies, "rebuts": rebuts, "findings": findings}

    def _claim_item(self, rec: _Rec, *, inline: bool) -> dict:
        item = {
            "id": rec.event["id"], "pubkey": rec.event["pubkey"], "author": self._author(rec.event["pubkey"]),
            "text": rec.content["text"], "received_at": rec.received_at,
        }
        if inline:
            item["links"] = [self._link_view(link, trim=True) for link in self._kind(E.LINK)
                             if link.content["to"] == rec.event["id"]]
            item["contradiction_ids"] = [c.event["id"] for c in self._kind(E.CONTRADICTION)
                                          if rec.event["id"] in c.content["claims"]]
        else:
            item.update(self._claim_counts(rec.event["id"]))
        return item

    def search_claims(self, text: str = "", method: str = "keyword", limit: int = 10, *, count: bool = True) -> dict:
        """Keyword overlap over claim text. ``vector`` uses the same overlap and says so."""
        self._touch(count)
        if method not in ("keyword", "vector"):
            raise ValueError("method must be 'vector' or 'keyword'")
        limit = _bound("limit", limit, 1, 200)
        query = set(_tokens(text))
        scored = []
        for rec in self._kind(E.CLAIM):
            if not query:
                continue
            overlap = query & set(_tokens(rec.content["text"]))
            if not overlap and text.lower() not in rec.content["text"].lower():
                continue
            scored.append((len(overlap) / len(query), rec))
        scored.sort(key=lambda item: (-item[0], item[1].event["id"]))
        items = []
        for rank, rec in scored[:limit]:
            item = self._claim_item(rec, inline=True)
            item["rank"] = rank
            items.append(item)
        note = "Distances and ranks are retrieval aids, not confidence."
        if method == "vector":
            note += " This eval collection has no embedding index; keyword overlap was used."
        return {"method": method, "note": note, "items": items}

    def list_claims(self, sort: str = "unsupported", limit: int = 50, offset: int = 0, *, count: bool = True) -> list[dict]:
        """Claims with link counts. Sorts match the ledger's worklists; counts are not verdicts."""
        self._touch(count)
        if sort not in _SORTS:
            raise ValueError(f"sort must be one of {', '.join(_SORTS)}")
        limit, offset = _bound("limit", limit, 1, 200), _bound("offset", offset, 0, 1_000_000)
        rows = []
        for rec in self._kind(E.CLAIM):
            item = self._claim_item(rec, inline=False)
            counts = item
            total = counts["supports"] + counts["qualifies"] + counts["rebuts"]
            if sort == "recent":
                key = (-rec.received_at, rec.event["id"])
            elif sort == "oldest":
                key = (rec.received_at, rec.event["id"])
            elif sort == "links":
                key = (-total, -rec.received_at, rec.event["id"])
            elif sort == "unsupported":
                key = (total, -rec.received_at, rec.event["id"])
            elif sort == "unchallenged":
                key = (counts["rebuts"] + counts["qualifies"], -counts["supports"], -rec.received_at, rec.event["id"])
            else:
                key = (-counts["rebuts"], -counts["findings"], -rec.received_at, rec.event["id"])
            rows.append((key, item))
        rows.sort(key=lambda item: item[0])
        return [item for _, item in rows[offset:offset + limit]]

    def get_links(self, to_id: str = "", from_id: str = "", relation: str = "", limit: int = 100,
                  offset: int = 0, *, count: bool = True) -> list[dict]:
        """Links, oldest first, filtered by target, evidence, or relation."""
        self._touch(count)
        limit, offset = _bound("limit", limit, 1, 1000), _bound("offset", offset, 0, 1_000_000)
        if relation and relation not in E.RELATIONS:
            raise ValueError("relation must be SUPPORTS, REBUTS, or QUALIFIES")
        rows = []
        for rec in self._kind(E.LINK):
            if to_id and rec.content["to"] != to_id:
                continue
            if from_id and rec.content["from"] != from_id:
                continue
            if relation and rec.content["relation"] != relation:
                continue
            rows.append(self._link_view(rec, trim=False))
        return rows[offset:offset + limit]

    def search_contradictions(self, claim: str = "", text: str = "", limit: int = 20, *, count: bool = True) -> list[dict]:
        """Contradictions, optionally naming a claim or matching words in the reason."""
        self._touch(count)
        limit = _bound("limit", limit, 1, 200)
        query = set(_tokens(text))
        rows = []
        for rec in self._kind(E.CONTRADICTION):
            if claim and claim not in rec.content["claims"]:
                continue
            if query and not (query & set(_tokens(rec.content["reason"]))) and text.lower() not in rec.content["reason"].lower():
                continue
            members = []
            for cid in sorted(rec.content["claims"]):
                member = self._by_id.get(cid)
                if member is None:
                    continue
                members.append({
                    "id": cid, "pubkey": member.event["pubkey"], "author": self._author(member.event["pubkey"]),
                    "text": member.content.get("text", ""),
                })
            rows.append({
                "id": rec.event["id"], "pubkey": rec.event["pubkey"], "author": self._author(rec.event["pubkey"]),
                "reason": rec.content["reason"], "claim_ids": list(rec.content["claims"]),
                "received_at": rec.received_at, "claims": members,
                "links": [self._link_view(link, trim=False) for link in self._kind(E.LINK) if link.content["to"] == rec.event["id"]],
            })
        return rows[:limit]

    def check_proof(self, proof: dict | None = None, *, count: bool = True) -> dict:
        """Validate a thinking proof against this collection. Same three rules as the server."""
        self._touch(count)
        steps = proof.get("steps") if isinstance(proof, dict) else None
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "problems": ["proof.steps must be a non-empty list"], "tree": "", "root": None}
        problems: list[str] = []
        by_id: dict[str, dict] = {}
        premises: dict[str, list[str]] = {}
        grounded: dict[str, bool] = {}
        leaves: dict[str, _Rec] = {}
        referenced: set[str] = set()
        all_ids = {s.get("id") for s in steps if isinstance(s, dict) and isinstance(s.get("id"), str)}
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                problems.append(f"step {i}: not an object")
                continue
            sid = step.get("id")
            if not isinstance(sid, str) or not sid or sid in by_id:
                problems.append(f"step {i}: missing, non-string or duplicate id")
                continue
            by_id[sid] = step
            if not isinstance(step.get("say"), str) or not step["say"].strip():
                problems.append(f"{sid}: 'say' must be a non-empty string")
            frm = step.get("from") or []
            if not isinstance(frm, list) or not all(isinstance(ref, str) for ref in frm):
                problems.append(f"{sid}: 'from' must be a list of id strings")
                frm = []
            premises[sid] = frm
            ok = False
            for ref in frm:
                if ref in grounded:
                    referenced.add(ref)
                    ok = ok or grounded[ref]
                elif ref in all_ids:
                    problems.append(f"{sid}: cites step {ref}, which is not an earlier step; list premises before conclusions")
                else:
                    rec = self._by_id.get(ref)
                    if rec is None or rec.content.get("collection") != self.collection:
                        problems.append(f"{sid}: {ref} is not an event in collection '{self.collection}'")
                        continue
                    leaves[ref] = rec
                    ok = True
            if not ok and not step.get("gap"):
                problems.append(f"{sid}: no ledger event in its ancestry and not marked gap")
            grounded[sid] = ok
        roots = [sid for sid in by_id if sid not in referenced]
        if len(roots) != 1:
            problems.append(f"expected exactly one root step, found {roots}")
        lines: list[str] = []
        order = {sid: i for i, sid in enumerate(by_id)}
        shown: set[str] = set()

        def render(sid: str, depth: int) -> None:
            pad = "  " * depth
            if sid in shown:
                lines.append(f"{pad}[{sid}] (see above)")
                return
            shown.add(sid)
            step = by_id[sid]
            tag = " (gap)" if step.get("gap") else ""
            lines.append(f"{pad}[{sid}]{tag} {step.get('say', '')}")
            for ref in premises[sid]:
                if ref in by_id and order[ref] < order[sid]:
                    render(ref, depth + 1)
                elif ref in by_id:
                    lines.append(f"{pad}  [{ref}] ?? not an earlier step")
                elif ref in leaves:
                    lines.append(f"{pad}  {ref} {_leaf(leaves[ref])}")
                else:
                    lines.append(f"{pad}  {ref} ?? unresolved")

        for root in roots:
            render(root, 0)
        return {"ok": not problems, "problems": problems, "root": roots[0] if len(roots) == 1 else None,
                "tree": "\n".join(lines)}


def _tokens(text: str) -> list[str]:
    return [tok for tok in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split(" ") if tok]


def _leaf(rec: _Rec) -> str:
    content, kind = rec.content, rec.event["kind"]
    if kind == E.CLAIM:
        return f"claim: {content['text']}"
    if kind == E.LINK:
        return f"link {content['relation']} {content['to']} from {content['from']}: \"{content['quote']}\""
    if kind == E.CONTRADICTION:
        return f"contradiction among {', '.join(content['claims'])}: {content['reason']}"
    if kind == E.EVIDENCE:
        title = f"\"{content['title']}\" " if content.get("title") else ""
        return f"evidence {title}by {rec.event['pubkey'][:12]}"
    return f"{E.NAMES[kind]} by {rec.event['pubkey'][:12]}"
