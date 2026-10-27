"""Unique-solution search for a Murdle-style grid.

Rows are positions. An ordered category is fixed to those positions (house 1 is the
leftmost row). With no ordered category, category 0 is fixed the same way so two
row-rotations of one matching are not counted as two solutions.

Search is forward checking on bit masks plus minimum-remaining-values backtracking.
It stops at ``limit`` solutions. A puzzle is uniquely solvable when one call with
``limit=2`` returns exactly one solution and ``complete`` is true.
"""
from __future__ import annotations

from dataclasses import dataclass

from evals.murdle.model import RELATIONS, Atom, Clue, Puzzle, validate_structure


@dataclass
class SolveResult:
    solutions: list[tuple[tuple[str, ...], ...]]
    complete: bool
    nodes: int


class _Fail(Exception):
    """The current assignment contradicts a clue or an all-different constraint."""


class _Enough(Exception):
    """Already found ``limit`` solutions."""


class _Budget(Exception):
    """Node budget exhausted."""


def _full(n: int) -> int:
    return (1 << n) - 1


def _shift_up(mask: int, n: int) -> int:
    return (mask << 1) & _full(n)


def _neighbors(mask: int, n: int) -> int:
    return _shift_up(mask, n) | (mask >> 1)


def _filter_left_of(mask_left: int, mask_right: int, n: int) -> tuple[int, int]:
    """Keep positions that still have a partner strictly to the right, and the reverse."""
    full = _full(n)
    new_left = new_right = 0
    for p in range(n):
        bit = 1 << p
        if mask_left & bit and (mask_right & (full ^ ((1 << (p + 1)) - 1))):
            new_left |= bit
        if mask_right & bit and (mask_left & ((1 << p) - 1)):
            new_right |= bit
    return new_left, new_right


def _index(puzzle: Puzzle) -> dict[tuple[str, str], tuple[int, int]]:
    return {(cat.name, ent): (c, e) for c, cat in enumerate(puzzle.categories) for e, ent in enumerate(cat.entities)}


def _active(puzzle: Puzzle, use_red_herrings: bool) -> list[Clue]:
    active = []
    for clue in puzzle.clues:
        kind = clue.effective_kind(use_red_herrings=use_red_herrings)
        if kind is None:
            continue
        if kind == clue.kind:
            active.append(clue)
            continue
        active.append(Clue(clue.id, kind, clue.text, clue.left, clue.right, clue.relation))
    return active


def _propagate(dom: list[list[int]], n: int, k: int, clues: list[tuple]) -> None:
    """Shrink domains until a fixpoint. Raises ``_Fail`` on a contradiction."""
    changed = True
    while changed:
        changed = False
        for c in range(k):
            for e in range(n):
                bits = dom[c][e]
                if bits == 0:
                    raise _Fail()
                if bits & (bits - 1) == 0:
                    for other in range(n):
                        if other != e and dom[c][other] & bits:
                            dom[c][other] &= ~bits
                            changed = True
                            if dom[c][other] == 0:
                                raise _Fail()
            for p in range(n):
                bit = 1 << p
                owner = None
                count = 0
                for e in range(n):
                    if dom[c][e] & bit:
                        count += 1
                        owner = e
                        if count > 1:
                            break
                if count == 0:
                    raise _Fail()
                if count == 1 and dom[c][owner] != bit:
                    dom[c][owner] = bit
                    changed = True
        for kind, a, b, relation in clues:
            la, ra = dom[a[0]][a[1]], dom[b[0]][b[1]]
            if kind == "direct":
                both = la & ra
                if both == 0:
                    raise _Fail()
                if both != la:
                    dom[a[0]][a[1]] = both
                    changed = True
                if both != ra:
                    dom[b[0]][b[1]] = both
                    changed = True
            elif kind == "negative":
                if la & (la - 1) == 0 and ra & la:
                    dom[b[0]][b[1]] = ra & ~la
                    changed = True
                    if dom[b[0]][b[1]] == 0:
                        raise _Fail()
                if ra & (ra - 1) == 0 and la & ra:
                    dom[a[0]][a[1]] = la & ~ra
                    changed = True
                    if dom[a[0]][a[1]] == 0:
                        raise _Fail()
            elif relation == "immediately_left_of":
                new_l, new_r = la & (ra >> 1), ra & _shift_up(la, n)
            elif relation == "immediately_right_of":
                new_l, new_r = la & _shift_up(ra, n), ra & (la >> 1)
            elif relation == "next_to":
                new_l, new_r = la & _neighbors(ra, n), ra & _neighbors(la, n)
            elif relation == "left_of":
                new_l, new_r = _filter_left_of(la, ra, n)
            elif relation == "right_of":
                new_r, new_l = _filter_left_of(ra, la, n)
            else:
                raise ValueError(f"unknown relation {relation}")
            if kind == "relational":
                if new_l == 0 or new_r == 0:
                    raise _Fail()
                if new_l != la:
                    dom[a[0]][a[1]] = new_l
                    changed = True
                if new_r != ra:
                    dom[b[0]][b[1]] = new_r
                    changed = True


def _read(dom: list[list[int]], puzzle: Puzzle) -> tuple[tuple[str, ...], ...]:
    n = len(puzzle.categories[0].entities)
    rows = []
    for p in range(n):
        bit = 1 << p
        row = []
        for c, cat in enumerate(puzzle.categories):
            found = [cat.entities[e] for e in range(n) if dom[c][e] == bit]
            if len(found) != 1:
                raise RuntimeError("domain fixpoint was not a complete assignment")
            row.append(found[0])
        rows.append(tuple(row))
    return tuple(rows)


def solve(puzzle: Puzzle, *, limit: int = 2, use_red_herrings: bool = False,
          max_nodes: int = 200_000) -> SolveResult:
    """Search for up to ``limit`` solutions.

    ``complete`` is false only when ``max_nodes`` was hit before the search finished
    and fewer than ``limit`` solutions had been found. Hitting the limit on purpose
    still counts as complete: the caller asked for at most that many.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    validate_structure(puzzle)
    n = len(puzzle.categories[0].entities)
    k = len(puzzle.categories)
    index = _index(puzzle)
    compiled = []
    for clue in _active(puzzle, use_red_herrings):
        assert clue.left is not None and clue.right is not None
        compiled.append((
            clue.kind, index[(clue.left.category, clue.left.entity)],
            index[(clue.right.category, clue.right.entity)], clue.relation))
        if clue.kind == "relational" and clue.relation not in RELATIONS:
            raise ValueError(f"clue {clue.id} has unknown relation {clue.relation}")
    anchor = next((c for c, cat in enumerate(puzzle.categories) if cat.ordered), 0)
    dom = [[_full(n) for _ in range(n)] for _ in range(k)]
    for e in range(n):
        dom[anchor][e] = 1 << e
    solutions: list[tuple[tuple[str, ...], ...]] = []
    nodes = 0

    def clone(src: list[list[int]]) -> list[list[int]]:
        return [row[:] for row in src]

    def search(state: list[list[int]]) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            raise _Budget()
        pick = None
        best = n + 1
        for c in range(k):
            for e in range(n):
                size = state[c][e].bit_count()
                if 1 < size < best:
                    best = size
                    pick = (c, e)
        if pick is None:
            solutions.append(_read(state, puzzle))
            if len(solutions) >= limit:
                raise _Enough()
            return
        c, e = pick
        bits = state[c][e]
        p = 0
        while bits:
            if bits & 1:
                child = clone(state)
                child[c][e] = 1 << p
                try:
                    _propagate(child, n, k, compiled)
                    search(child)
                except _Fail:
                    pass
            bits >>= 1
            p += 1

    try:
        _propagate(dom, n, k, compiled)
        search(dom)
    except _Fail:
        return SolveResult([], True, nodes)
    except _Enough:
        return SolveResult(solutions, True, nodes)
    except _Budget:
        return SolveResult(solutions, False, nodes)
    return SolveResult(solutions, True, nodes)


def positions(puzzle: Puzzle) -> dict[tuple[str, str], int]:
    """Row index of every entity in the stored solution."""
    found: dict[tuple[str, str], int] = {}
    for r, row in enumerate(puzzle.solution):
        for c, cat in enumerate(puzzle.categories):
            found[(cat.name, row[c])] = r
    return found


def clue_holds(puzzle: Puzzle, clue: Clue) -> bool:
    """Whether a clue's grid fact is true of the stored solution. Flavor text counts as true."""
    kind = clue.fact if clue.kind == "red_herring" else clue.kind
    if kind == "flavor":
        return True
    if not puzzle.solution:
        raise ValueError("clue_holds needs a stored solution")
    pos = positions(puzzle)
    assert clue.left is not None and clue.right is not None
    lp = pos[(clue.left.category, clue.left.entity)]
    rp = pos[(clue.right.category, clue.right.entity)]
    if kind == "direct":
        return lp == rp
    if kind == "negative":
        return lp != rp
    return {
        "immediately_left_of": lp + 1 == rp,
        "immediately_right_of": lp == rp + 1,
        "next_to": abs(lp - rp) == 1,
        "left_of": lp < rp,
        "right_of": lp > rp,
    }[clue.relation or ""]


def atom_at(puzzle: Puzzle, category: str, row: int) -> str:
    index = next(i for i, cat in enumerate(puzzle.categories) if cat.name == category)
    return puzzle.solution[row][index]


def partner(puzzle: Puzzle, atom: Atom, other_category: str) -> Atom:
    """The entity of ``other_category`` that shares the solution row with ``atom``."""
    pos = positions(puzzle)[(atom.category, atom.entity)]
    return Atom(other_category, atom_at(puzzle, other_category, pos))
