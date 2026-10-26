"""Structured claim lines the scorer can check.

A claim is one line, fields separated by tabs, so entity names may contain spaces:

    PAIR<TAB>category<TAB>entity<TAB>category<TAB>entity
    NOT<TAB>category<TAB>entity<TAB>category<TAB>entity
    REL<TAB>category<TAB>entity<TAB>relation<TAB>category<TAB>entity
"""
from __future__ import annotations

from evals.murdle.model import RELATIONS, Atom


def encode_pair(left: Atom, right: Atom) -> str:
    return "\t".join(("PAIR", left.category, left.entity, right.category, right.entity))


def encode_not(left: Atom, right: Atom) -> str:
    return "\t".join(("NOT", left.category, left.entity, right.category, right.entity))


def encode_rel(left: Atom, relation: str, right: Atom) -> str:
    return "\t".join(("REL", left.category, left.entity, relation, right.category, right.entity))


def parse_claim(text: str):
    """Return ``(kind, left, right)`` or ``(REL, left, relation, right)``, or None."""
    parts = text.split("\t")
    if len(parts) == 5 and parts[0] in ("PAIR", "NOT") and all(parts[1:]):
        return parts[0], Atom(parts[1], parts[2]), Atom(parts[3], parts[4])
    if len(parts) == 6 and parts[0] == "REL" and parts[3] in RELATIONS and all(parts[1:3]) and all(parts[4:]):
        return "REL", Atom(parts[1], parts[2]), parts[3], Atom(parts[4], parts[5])
    return None


def claim_line(clue) -> str | None:
    """The structured claim a clue asserts, or None for flavor text."""
    kind = clue.fact if clue.kind == "red_herring" else clue.kind
    if kind == "direct":
        return encode_pair(clue.left, clue.right)
    if kind == "negative":
        return encode_not(clue.left, clue.right)
    if kind == "relational":
        return encode_rel(clue.left, clue.relation, clue.right)
    return None
