"""Score a finished run against the answer key and the records the agent wrote.

``accuracy`` is the fraction of non-anchor cells that match, rows lined up on the
ordered category (or the first category when nothing is ordered). ``exact_match``
requires the same set of rows. ``answer_accuracy`` is the fraction of asked
questions whose entity is right.

In tms mode ``trail_score`` is the mean of four rates: link integrity (accepted
links over accepted plus rejected), pair recall (true PAIR claims over the gold
pairs), whether check_proof passed, and how many false claims were either named
in a contradiction or targeted by a REBUTS link. Baseline runs have no trail;
``trail_score`` is null there.
"""
from __future__ import annotations

from evals.murdle.claims import parse_claim
from evals.murdle.model import RELATIONS, Puzzle
from tms import events as E


def score_run(puzzle: Puzzle, result, session, seconds: float) -> dict:
    rows = _rows(getattr(result, "solution", None))
    answers = _answers(getattr(result, "answers", None))
    gold = puzzle.solution_dicts()
    anchor = puzzle.anchor()
    cell = _cell_accuracy(gold, rows, anchor)
    exact = _row_set(rows, puzzle) == _row_set(gold, puzzle) and len(rows) == len(gold)
    key = puzzle.answer_key()
    if key:
        answer_accuracy = sum(1 for ask, entity in key.items() if answers.get(ask) == entity) / len(key)
    else:
        answer_accuracy = 1.0 if exact else 0.0
    trail = _trail(puzzle, session)
    proof_ok = getattr(result, "proof_ok", None)
    steps = getattr(result, "steps", 0) or 0
    if session is not None and steps == 0 and session.tool_calls:
        steps = session.tool_calls
    false_claims = trail["false_claims"]
    addressed = 1.0 if false_claims == 0 else 1.0 - trail["unaddressed_false_claims"] / false_claims
    if session is None:
        trail_score = None
    else:
        trail_score = (trail["link_integrity"] + trail["pair_recall"] + (1.0 if proof_ok else 0.0) + addressed) / 4
    return {
        "mode": "tms" if session is not None else "baseline",
        "accuracy": cell,
        "cell_accuracy": cell,
        "exact_match": exact,
        "answer_accuracy": answer_accuracy,
        "solved": bool(exact and answer_accuracy == 1.0),
        "answers_expected": puzzle.answer_key(),
        "answers": answers,
        "evidence": trail["evidence"],
        "loaded_clues": trail["loaded_clues"],
        "claims": trail["claims"],
        "structured_claims": trail["structured_claims"],
        "unparsed_claims": trail["unparsed_claims"],
        "links": trail["links"],
        "rejected_links": trail["rejected_links"],
        "link_integrity": trail["link_integrity"],
        "contradictions": trail["contradictions"],
        "contradictions_valid": trail["contradictions_valid"],
        "contradictions_spurious": trail["contradictions_spurious"],
        "contradictions_weak": trail["contradictions_weak"],
        "false_claims": false_claims,
        "unaddressed_false_claims": trail["unaddressed_false_claims"],
        "pair_recall": trail["pair_recall"],
        "proof_ok": proof_ok,
        "trail_score": trail_score,
        "steps": steps,
        "tool_calls": session.tool_calls if session is not None else 0,
        "tokens": getattr(result, "tokens", 0) or 0,
        "seconds": round(seconds, 6),
        "error": getattr(result, "error", None),
    }


def _trail(puzzle: Puzzle, session) -> dict:
    empty = {
        "evidence": 0, "loaded_clues": 0, "claims": 0, "structured_claims": 0, "unparsed_claims": 0,
        "links": 0, "rejected_links": 0, "link_integrity": 1.0, "contradictions": 0,
        "contradictions_valid": 0, "contradictions_spurious": 0, "contradictions_weak": 0,
        "false_claims": 0, "unaddressed_false_claims": 0, "pair_recall": 0.0,
    }
    if session is None:
        return empty
    evidence = session.records(E.EVIDENCE)
    claims = session.records(E.CLAIM)
    links = session.records(E.LINK)
    contradictions = session.records(E.CONTRADICTION)
    parsed = []
    unparsed = 0
    for rec in claims:
        item = parse_claim(rec["content"].get("text", ""))
        if item is None:
            unparsed += 1
        else:
            parsed.append((rec["id"], item, _holds(puzzle, item)))
    false_ids = [cid for cid, _, ok in parsed if not ok]
    rebutted = {rec["content"]["to"] for rec in links if rec["content"]["relation"] == "REBUTS"}
    named = set()
    valid = spurious = weak = 0
    by_id = {rec["id"]: rec["content"].get("text", "") for rec in claims}
    for rec in contradictions:
        members = []
        readable = True
        for cid in rec["content"]["claims"]:
            named.add(cid)
            item = parse_claim(by_id.get(cid, ""))
            if item is None:
                readable = False
            else:
                members.append(item)
        if not readable or len(members) < 2:
            weak += 1
        elif _conflict(members):
            valid += 1
        elif all(_holds(puzzle, item) for item in members):
            spurious += 1
        else:
            weak += 1
    gold = _gold_pairs(puzzle)
    claimed = {_sig(item[1], item[2]) for _, item, ok in parsed if ok and item[0] == "PAIR"}
    attempted = len(links) + session.rejected_links
    return {
        "evidence": len(evidence),
        "loaded_clues": session.loaded_clues,
        "claims": len(claims),
        "structured_claims": len(parsed),
        "unparsed_claims": unparsed,
        "links": len(links),
        "rejected_links": session.rejected_links,
        "link_integrity": 1.0 if attempted == 0 else len(links) / attempted,
        "contradictions": len(contradictions),
        "contradictions_valid": valid,
        "contradictions_spurious": spurious,
        "contradictions_weak": weak,
        "false_claims": len(false_ids),
        "unaddressed_false_claims": sum(1 for cid in false_ids if cid not in named and cid not in rebutted),
        "pair_recall": (len(claimed & gold) / len(gold)) if gold else 0.0,
    }


def _holds(puzzle: Puzzle, parsed) -> bool:
    pos = {}
    for r, row in enumerate(puzzle.solution):
        for c, cat in enumerate(puzzle.categories):
            pos[(cat.name, row[c])] = r
    if parsed[0] in ("PAIR", "NOT"):
        _, left, right = parsed
        if (left.category, left.entity) not in pos or (right.category, right.entity) not in pos:
            return False
        same = pos[(left.category, left.entity)] == pos[(right.category, right.entity)]
        return same if parsed[0] == "PAIR" else not same
    _, left, relation, right = parsed
    if relation not in RELATIONS:
        return False
    if (left.category, left.entity) not in pos or (right.category, right.entity) not in pos:
        return False
    lp, rp = pos[(left.category, left.entity)], pos[(right.category, right.entity)]
    return {
        "immediately_left_of": lp + 1 == rp,
        "immediately_right_of": lp == rp + 1,
        "next_to": abs(lp - rp) == 1,
        "left_of": lp < rp,
        "right_of": lp > rp,
    }[relation]


def _gold_pairs(puzzle: Puzzle) -> set[tuple]:
    pairs = set()
    for row in puzzle.solution:
        atoms = [(cat.name, row[i]) for i, cat in enumerate(puzzle.categories)]
        for i in range(len(atoms)):
            for j in range(i + 1, len(atoms)):
                pairs.add(tuple(sorted((atoms[i], atoms[j]))))
    return pairs


def _sig(left, right) -> tuple:
    return tuple(sorted(((left.category, left.entity), (right.category, right.entity))))


def _conflict(members) -> bool:
    pairs, nots = [], []
    for item in members:
        if item[0] == "PAIR":
            pairs.append((item[1], item[2]))
        elif item[0] == "NOT":
            nots.append((item[1], item[2]))
    for left, right in pairs:
        key = _sig(left, right)
        if any(_sig(a, b) == key for a, b in nots):
            return True
    for i, (a, b) in enumerate(pairs):
        for c, d in pairs[i + 1:]:
            if _exclusive(a, b, c, d):
                return True
    return False


def _exclusive(a, b, c, d) -> bool:
    left = {(a.category, a.entity), (b.category, b.entity)}
    right = {(c.category, c.entity), (d.category, d.entity)}
    shared = left & right
    if len(shared) != 1:
        return False
    rest_l, rest_r = (left - shared).pop(), (right - shared).pop()
    return rest_l[0] == rest_r[0] and rest_l != rest_r


def _rows(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    rows = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        clean = {}
        for key, value in row.items():
            entity = _entity(value)
            if isinstance(key, str) and entity is not None:
                clean[key] = entity
        rows.append(clean)
    return rows


def _answers(raw) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        entity = _entity(value)
        if isinstance(key, str) and entity is not None:
            out[key.strip()] = entity
    return out


def _entity(value):
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return str(value)


def _cell_accuracy(gold: list[dict], pred: list[dict], anchor: str) -> float:
    by_anchor = {row[anchor]: row for row in pred if anchor in row}
    cells = correct = 0
    for row in gold:
        for key, value in row.items():
            if key == anchor:
                continue
            cells += 1
            got = by_anchor.get(row[anchor])
            if got is not None and got.get(key) == value:
                correct += 1
    return correct / cells if cells else 0.0


def _row_set(rows: list[dict], puzzle: Puzzle) -> set[tuple]:
    return {tuple(row.get(cat.name) for cat in puzzle.categories) for row in rows}
