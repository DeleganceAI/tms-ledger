"""Puzzle records shared by the generator, the solver, and the harness.

A puzzle is a Latin grid: every category has the same number of entities, and a
solution assigns exactly one entity from each category to each row. An ordered
category (houses, seats, times) fixes the row axis, which is what "left of" means.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

NAME = re.compile(r"^[a-z][a-z0-9_]*$")
RELATIONS = ("immediately_left_of", "immediately_right_of", "next_to", "left_of", "right_of")
KINDS = ("direct", "negative", "relational", "red_herring")
FACTS = ("direct", "negative", "relational", "flavor")


@dataclass(frozen=True)
class Atom:
    category: str
    entity: str


@dataclass(frozen=True)
class Category:
    name: str
    entities: tuple[str, ...]
    ordered: bool = False


@dataclass(frozen=True)
class Clue:
    """One statement the agent can read.

    ``kind`` is what the generator claims the clue is for. A red herring keeps the
    underlying statement in ``fact`` (or ``flavor`` when the sentence is not a grid
    constraint). The solver ignores red herrings unless asked to apply them.
    """

    id: str
    kind: str
    text: str
    left: Atom | None = None
    right: Atom | None = None
    relation: str | None = None
    fact: str | None = None

    def effective_kind(self, *, use_red_herrings: bool) -> str | None:
        if self.kind == "red_herring":
            if not use_red_herrings or self.fact in (None, "flavor"):
                return None
            return self.fact
        return self.kind


@dataclass(frozen=True)
class Ask:
    """One scored question: which entity of ``category`` shares a row with ``with_entity``."""

    id: str
    prompt: str
    category: str
    with_category: str
    with_entity: str


@dataclass(frozen=True)
class Puzzle:
    id: str
    title: str
    source: str
    memorization_risk: str
    categories: tuple[Category, ...]
    clues: tuple[Clue, ...]
    solution: tuple[tuple[str, ...], ...]
    question: str
    asks: tuple[Ask, ...]
    notes: str = ""
    meta: tuple[tuple[str, str], ...] = ()

    def meta_dict(self) -> dict[str, str]:
        return dict(self.meta)

    def category(self, name: str) -> Category:
        for cat in self.categories:
            if cat.name == name:
                return cat
        raise KeyError(name)

    def anchor(self) -> str:
        """Row label used to line a predicted grid up with the answer key."""
        for cat in self.categories:
            if cat.ordered:
                return cat.name
        return self.categories[0].name

    def solution_dicts(self) -> list[dict[str, str]]:
        names = [c.name for c in self.categories]
        return [{names[i]: row[i] for i in range(len(names))} for row in self.solution]

    def answer_key(self) -> dict[str, str]:
        rows = self.solution_dicts()
        out = {}
        for ask in self.asks:
            for row in rows:
                if row[ask.with_category] == ask.with_entity:
                    out[ask.id] = row[ask.category]
                    break
        return out

    def without_red_herrings(self) -> Puzzle:
        kept = tuple(c for c in self.clues if c.kind != "red_herring")
        return Puzzle(
            self.id, self.title, self.source, self.memorization_risk, self.categories, kept,
            self.solution, self.question, self.asks, self.notes, self.meta)


def describe(kind: str, left: Atom, right: Atom, relation: str | None = None) -> str:
    """Stable sentence for a generated clue. Hand-written puzzles use their own prose."""
    a, b = f"{left.category} {left.entity}", f"{right.category} {right.entity}"
    if kind == "direct":
        return f"The {a} is together with the {b}."
    if kind == "negative":
        return f"The {a} is not together with the {b}."
    phrase = {
        "immediately_left_of": f"The {a} is immediately left of the {b}.",
        "immediately_right_of": f"The {a} is immediately right of the {b}.",
        "next_to": f"The {a} is next to the {b}.",
        "left_of": f"The {a} is somewhere left of the {b}.",
        "right_of": f"The {a} is somewhere right of the {b}.",
    }[relation or ""]
    return phrase


def _clean_label(value: str, what: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\t" in value or "\n" in value:
        raise ValueError(f"{what} must be a single-line string without tabs")


def validate_structure(puzzle: Puzzle) -> None:
    if puzzle.source not in ("classic", "original", "generated"):
        raise ValueError("source must be classic, original, or generated")
    if puzzle.memorization_risk not in ("high", "low"):
        raise ValueError("memorization_risk must be high or low")
    if len(puzzle.categories) < 2:
        raise ValueError("a puzzle needs at least two categories")
    n = len(puzzle.categories[0].entities)
    if n < 2:
        raise ValueError("each category needs at least two entities")
    ordered = [c for c in puzzle.categories if c.ordered]
    if len(ordered) > 1:
        raise ValueError("at most one category may be ordered")
    seen_names = set()
    for cat in puzzle.categories:
        _clean_label(cat.name, "category")
        if not NAME.match(cat.name):
            raise ValueError(f"category name {cat.name!r} must match {NAME.pattern}")
        if cat.name in seen_names:
            raise ValueError(f"duplicate category {cat.name}")
        seen_names.add(cat.name)
        if len(cat.entities) != n or len(set(cat.entities)) != n:
            raise ValueError(f"category {cat.name} must have {n} distinct entities")
        for ent in cat.entities:
            _clean_label(ent, f"{cat.name} entity")
    known = {(c.name, e) for c in puzzle.categories for e in c.entities}
    needs_axis = False
    clue_ids = set()
    for clue in puzzle.clues:
        if clue.id in clue_ids:
            raise ValueError(f"duplicate clue id {clue.id}")
        clue_ids.add(clue.id)
        if clue.kind not in KINDS:
            raise ValueError(f"clue {clue.id} has unknown kind {clue.kind}")
        if not clue.text.strip():
            raise ValueError(f"clue {clue.id} has no text")
        kind = clue.fact if clue.kind == "red_herring" else clue.kind
        if clue.kind == "red_herring" and kind not in FACTS:
            raise ValueError(f"clue {clue.id} red herring needs a fact")
        if kind == "flavor":
            continue
        if kind == "relational":
            needs_axis = True
            if clue.relation not in RELATIONS:
                raise ValueError(f"clue {clue.id} has unknown relation {clue.relation}")
        elif clue.relation is not None:
            raise ValueError(f"clue {clue.id} is {kind} and must not set relation")
        if clue.left is None or clue.right is None:
            raise ValueError(f"clue {clue.id} needs two atoms")
        for atom in (clue.left, clue.right):
            if (atom.category, atom.entity) not in known:
                raise ValueError(f"clue {clue.id} names unknown {atom.category} {atom.entity}")
        if kind in ("direct", "negative") and clue.left.category == clue.right.category:
            raise ValueError(f"clue {clue.id} pairs two entities of {clue.left.category}")
        if clue.left == clue.right:
            raise ValueError(f"clue {clue.id} repeats one atom")
    if needs_axis and not ordered:
        raise ValueError("relational clues need an ordered category")
    for ask in puzzle.asks:
        if ask.category not in seen_names or ask.with_category not in seen_names:
            raise ValueError(f"ask {ask.id} names an unknown category")
        if (ask.with_category, ask.with_entity) not in known:
            raise ValueError(f"ask {ask.id} names an unknown entity")


def validate_solution(puzzle: Puzzle) -> None:
    validate_structure(puzzle)
    n = len(puzzle.categories[0].entities)
    if len(puzzle.solution) != n:
        raise ValueError("solution row count does not match the categories")
    columns = [set() for _ in puzzle.categories]
    for r, row in enumerate(puzzle.solution):
        if len(row) != len(puzzle.categories):
            raise ValueError(f"solution row {r} has the wrong width")
        for c, cat in enumerate(puzzle.categories):
            if row[c] not in cat.entities:
                raise ValueError(f"solution row {r} has {row[c]!r} outside {cat.name}")
            columns[c].add(row[c])
            if cat.ordered and row[c] != cat.entities[r]:
                raise ValueError(f"ordered category {cat.name} must sit in entity order")
    for cat, seen in zip(puzzle.categories, columns):
        if seen != set(cat.entities):
            raise ValueError(f"solution does not use every {cat.name} entity once")


def puzzle_to_dict(puzzle: Puzzle) -> dict:
    def atom(a: Atom | None):
        return None if a is None else {"category": a.category, "entity": a.entity}

    return {
        "id": puzzle.id, "title": puzzle.title, "source": puzzle.source,
        "memorization_risk": puzzle.memorization_risk, "question": puzzle.question,
        "notes": puzzle.notes, "meta": puzzle.meta_dict(),
        "categories": [{"name": c.name, "entities": list(c.entities), "ordered": c.ordered}
                       for c in puzzle.categories],
        "clues": [{"id": c.id, "kind": c.kind, "text": c.text, "left": atom(c.left),
                   "right": atom(c.right), "relation": c.relation, "fact": c.fact}
                  for c in puzzle.clues],
        "solution": puzzle.solution_dicts(),
        "asks": [{"id": a.id, "prompt": a.prompt, "category": a.category,
                  "with_category": a.with_category, "with_entity": a.with_entity}
                 for a in puzzle.asks],
    }


def puzzle_from_dict(data: dict) -> Puzzle:
    def atom(raw):
        return None if raw is None else Atom(raw["category"], raw["entity"])

    categories = tuple(Category(c["name"], tuple(c["entities"]), bool(c.get("ordered", False)))
                       for c in data["categories"])
    order = [c.name for c in categories]
    clues = tuple(Clue(c["id"], c["kind"], c["text"], atom(c.get("left")), atom(c.get("right")),
                       c.get("relation"), c.get("fact")) for c in data["clues"])
    solution = []
    for row in data["solution"]:
        solution.append(tuple(row[name] for name in order))
    asks = tuple(Ask(a["id"], a["prompt"], a["category"], a["with_category"], a["with_entity"])
                 for a in data.get("asks", []))
    meta = tuple(sorted((str(k), str(v)) for k, v in (data.get("meta") or {}).items()))
    puzzle = Puzzle(
        data["id"], data["title"], data["source"], data["memorization_risk"], categories, clues,
        tuple(solution), data["question"], asks, data.get("notes") or "", meta)
    validate_solution(puzzle)
    return puzzle


def dump_puzzle(puzzle: Puzzle) -> str:
    return json.dumps(puzzle_to_dict(puzzle), indent=2, ensure_ascii=False) + "\n"


def load_puzzle(text: str) -> Puzzle:
    return puzzle_from_dict(json.loads(text))
