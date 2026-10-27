"""Hand-checked puzzles.

Zebra restates the widely circulated five-house riddle in new sentences. It is not a
transcription of the 1962 magazine wording, and it is not a Murdle. Terrace and gallery
are original. Published Murdle book text is not stored here: those puzzles are copyrighted,
and a model may have memorized them anyway. ``memorization_risk`` records that difference.
"""
from __future__ import annotations

from functools import lru_cache

from evals.murdle.model import Ask, Atom, Category, Clue, Puzzle, validate_solution


def _direct(cid: str, text: str, c1: str, e1: str, c2: str, e2: str) -> Clue:
    return Clue(cid, "direct", text, Atom(c1, e1), Atom(c2, e2))


def _negative(cid: str, text: str, c1: str, e1: str, c2: str, e2: str) -> Clue:
    return Clue(cid, "negative", text, Atom(c1, e1), Atom(c2, e2))


def _rel(cid: str, text: str, c1: str, e1: str, relation: str, c2: str, e2: str) -> Clue:
    return Clue(cid, "relational", text, Atom(c1, e1), Atom(c2, e2), relation)


def _flavor(cid: str, text: str) -> Clue:
    return Clue(cid, "red_herring", text, fact="flavor")


def _aside(cid: str, text: str, kind: str, c1: str, e1: str, c2: str, e2: str, relation: str | None = None) -> Clue:
    return Clue(cid, "red_herring", text, Atom(c1, e1), Atom(c2, e2), relation, fact=kind)


def zebra() -> Puzzle:
    """The five-house riddle: who drinks water, and who owns the zebra."""
    categories = (
        Category("house", ("1", "2", "3", "4", "5"), ordered=True),
        Category("color", ("yellow", "blue", "red", "ivory", "green")),
        Category("nationality", ("Norwegian", "Ukrainian", "Englishman", "Spaniard", "Japanese")),
        Category("drink", ("water", "tea", "milk", "orange juice", "coffee")),
        Category("smoke", ("Kools", "Chesterfields", "Old Gold", "Lucky Strike", "Parliaments")),
        Category("pet", ("fox", "horse", "snails", "dog", "zebra")),
    )
    # Rows follow the house axis. This is the standard solution of the folk riddle.
    solution = (
        ("1", "yellow", "Norwegian", "water", "Kools", "fox"),
        ("2", "blue", "Ukrainian", "tea", "Chesterfields", "horse"),
        ("3", "red", "Englishman", "milk", "Old Gold", "snails"),
        ("4", "ivory", "Spaniard", "orange juice", "Lucky Strike", "dog"),
        ("5", "green", "Japanese", "coffee", "Parliaments", "zebra"),
    )
    clues = (
        _flavor("z01", "There are five houses in a row, numbered 1 through 5 from left to right."),
        _direct("z02", "The Englishman lives in the red house.", "nationality", "Englishman", "color", "red"),
        _direct("z03", "The Spaniard owns the dog.", "nationality", "Spaniard", "pet", "dog"),
        _direct("z04", "Coffee is drunk in the green house.", "drink", "coffee", "color", "green"),
        _direct("z05", "The Ukrainian drinks tea.", "nationality", "Ukrainian", "drink", "tea"),
        _rel("z06", "The green house is immediately to the right of the ivory house.",
             "color", "ivory", "immediately_left_of", "color", "green"),
        _direct("z07", "The Old Gold smoker owns snails.", "smoke", "Old Gold", "pet", "snails"),
        _direct("z08", "Kools are smoked in the yellow house.", "smoke", "Kools", "color", "yellow"),
        _direct("z09", "Milk is drunk in house 3, the middle house.", "drink", "milk", "house", "3"),
        _direct("z10", "The Norwegian lives in house 1.", "nationality", "Norwegian", "house", "1"),
        _rel("z11", "The Chesterfields smoker lives next to the house with the fox.",
             "smoke", "Chesterfields", "next_to", "pet", "fox"),
        _rel("z12", "Kools are smoked in the house next to the house with the horse.",
             "smoke", "Kools", "next_to", "pet", "horse"),
        _direct("z13", "The Lucky Strike smoker drinks orange juice.", "smoke", "Lucky Strike", "drink", "orange juice"),
        _direct("z14", "The Japanese smokes Parliaments.", "nationality", "Japanese", "smoke", "Parliaments"),
        _rel("z15", "The Norwegian lives next to the blue house.",
             "nationality", "Norwegian", "next_to", "color", "blue"),
    )
    asks = (
        Ask("water", "Who drinks water?", "nationality", "drink", "water"),
        Ask("zebra", "Who owns the zebra?", "nationality", "pet", "zebra"),
    )
    puzzle = Puzzle(
        id="zebra", title="Zebra (five houses)", source="classic", memorization_risk="high",
        categories=categories, clues=clues, solution=solution,
        question="Who drinks water, and who owns the zebra?", asks=asks,
        notes="Constraints match the folk five-house riddle. The sentences are original to this eval.")
    validate_solution(puzzle)
    return puzzle


def terrace() -> Puzzle:
    """Three people, three drinks, three seats. Small enough to score by hand."""
    categories = (
        Category("seat", ("1", "2", "3"), ordered=True),
        Category("person", ("Ada", "Bo", "Cy")),
        Category("drink", ("tea", "coffee", "juice")),
    )
    solution = (
        ("1", "Ada", "tea"),
        ("2", "Bo", "coffee"),
        ("3", "Cy", "juice"),
    )
    clues = (
        _direct("t01", "Ada sits in seat 1.", "person", "Ada", "seat", "1"),
        _direct("t02", "Juice is at seat 3.", "drink", "juice", "seat", "3"),
        _negative("t03", "Bo does not sit in seat 3.", "person", "Bo", "seat", "3"),
        _direct("t04", "Bo drinks coffee.", "person", "Bo", "drink", "coffee"),
        _flavor("t05", "The terrace faces the river, and someone mentioned the view."),
        _aside("t06", "Ada does not drink juice.", "negative", "person", "Ada", "drink", "juice"),
    )
    asks = (Ask("tea", "Who drinks tea?", "person", "drink", "tea"),)
    puzzle = Puzzle(
        id="terrace", title="Tea on the terrace", source="original", memorization_risk="low",
        categories=categories, clues=clues, solution=solution,
        question="Who drinks tea?", asks=asks,
        notes="Original three-by-three. The river sentence is flavor; Ada not drinking juice is a true aside.")
    validate_solution(puzzle)
    return puzzle


def gallery() -> Puzzle:
    """Four guests, four rooms, four objects, four times. Original, Murdle-shaped."""
    categories = (
        Category("time", ("8", "9", "10", "11"), ordered=True),
        Category("suspect", ("Inez", "Jules", "Nico", "Omar")),
        Category("room", ("gallery", "vault", "studio", "courtyard")),
        Category("item", ("marble", "lens", "frame", "key")),
    )
    solution = (
        ("8", "Inez", "gallery", "marble"),
        ("9", "Jules", "vault", "lens"),
        ("10", "Nico", "studio", "frame"),
        ("11", "Omar", "courtyard", "key"),
    )
    clues = (
        _direct("g01", "Inez was there at time 8.", "suspect", "Inez", "time", "8"),
        _direct("g02", "The marble was used at time 8.", "item", "marble", "time", "8"),
        _direct("g03", "Inez was in the gallery.", "suspect", "Inez", "room", "gallery"),
        _rel("g04", "Inez was immediately before Jules.",
             "suspect", "Inez", "immediately_left_of", "suspect", "Jules"),
        _direct("g05", "Jules used the lens.", "suspect", "Jules", "item", "lens"),
        _direct("g06", "The lens was used in the vault.", "item", "lens", "room", "vault"),
        _rel("g07", "Jules was immediately before Nico.",
             "suspect", "Jules", "immediately_left_of", "suspect", "Nico"),
        _direct("g08", "Nico used the frame.", "suspect", "Nico", "item", "frame"),
        _rel("g09", "The studio is immediately left of the courtyard.",
             "room", "studio", "immediately_left_of", "room", "courtyard"),
        _direct("g10", "Omar was there at time 11.", "suspect", "Omar", "time", "11"),
        _direct("g11", "Omar used the key.", "suspect", "Omar", "item", "key"),
        _direct("g12", "Omar was in the courtyard.", "suspect", "Omar", "room", "courtyard"),
        _negative("g13", "Nico was not in the vault.", "suspect", "Nico", "room", "vault"),
        _flavor("g14", "A guest claimed the studio door sticks, which says nothing about who was where."),
        _aside("g15", "Jules was not in the courtyard.", "negative", "suspect", "Jules", "room", "courtyard"),
    )
    asks = (
        Ask("lens", "Who used the lens?", "suspect", "item", "lens"),
        Ask("frame", "Which room was the frame used in?", "room", "item", "frame"),
    )
    puzzle = Puzzle(
        id="gallery", title="The gallery opening", source="original", memorization_risk="low",
        categories=categories, clues=clues, solution=solution,
        question="Who used the lens, and where was the frame used?", asks=asks,
        notes="Original. The sticking door is flavor; Jules not being in the courtyard is a true aside.")
    validate_solution(puzzle)
    return puzzle


@lru_cache(maxsize=1)
def catalog() -> dict[str, Puzzle]:
    puzzles = (zebra(), terrace(), gallery())
    return {p.id: p for p in puzzles}
