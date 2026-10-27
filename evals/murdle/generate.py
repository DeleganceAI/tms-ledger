"""Generate Murdle-style grids that the solver can prove have one solution.

The construction is deterministic for a seed. It draws a completed grid, emits only
clues that are true of that grid, and keeps a subset the solver still finds unique.
Red herrings are true clues (or, in the hand-written puzzles, flavor text) that the
uniqueness proof does not use. A red herring is never a false statement: every clue
in the collection is safe to believe.

When ``relational`` is one of the clue types, one dimension is an ordered ``house``
axis. "Immediately left of" refers to that axis. ``entities`` above 80 is rejected:
past that, proving uniqueness by search stops being a check and becomes the experiment.
"""
from __future__ import annotations

import random
from dataclasses import replace

from evals.murdle.model import Ask, Atom, Category, Clue, Puzzle, describe, validate_solution
from evals.murdle.solver import solve

MAX_ENTITIES = 80
MAX_DIMENSIONS = 12
INFORMATIVE = ("direct", "negative", "relational")

# Original names for generated puzzles. Not a cast from any published Murdle.
POOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("suspect", ("Avery", "Blair", "Casey", "Drew", "Ellis", "Frankie", "Greer", "Harper",
                 "Indigo", "Jules", "Kerry", "Logan", "Morgan", "Noel", "Parker", "Quinn",
                 "Reese", "Shiloh", "Taylor", "Uma", "Val", "Winter", "Yael", "Arden",
                 "Blake", "Cameron", "Darcy", "Emery", "Finley", "Gray", "Hayden", "Ira",
                 "Jude", "Kit", "Lane", "Marlow", "Oakley", "Perry", "Rio", "Sage")),
    ("weapon", ("candlestick", "revolver", "rope", "wrench", "poison", "trophy", "letter-opener",
                "marble", "violin", "statue", "dagger", "poker", "axe", "hammer", "scarf",
                "bottle", "brick", "telescope", "compass", "lantern", "goblet", "flute",
                "shield", "crown", "mirror", "quill", "glove", "mask", "bell", "chain")),
    ("location", ("library", "kitchen", "garden", "study", "hall", "conservatory", "ballroom",
                  "cellar", "attic", "gallery", "courtyard", "studio", "vault", "terrace",
                  "lobby", "chapel", "office", "pantry", "observatory", "nursery", "parlor",
                  "stable", "dock", "tower", "crypt", "arcade", "cloister", "workshop")),
    ("motive", ("revenge", "jealousy", "debt", "blackmail", "inheritance", "silence", "accident",
                "escape", "fame", "fear", "loyalty", "pride", "hunger", "secrecy", "duty",
                "spite", "greed", "grief", "rivalry", "mercy")),
    ("vehicle", ("carriage", "bicycle", "ferry", "tram", "wagon", "sled", "skiff", "coach",
                 "cart", "raft", "sleigh", "canoe")),
    ("color", ("red", "green", "blue", "yellow", "ivory", "purple", "orange", "black", "white",
               "grey", "scarlet", "copper", "navy", "olive", "amber")),
    ("drink", ("tea", "coffee", "milk", "juice", "water", "cocoa", "cider", "wine", "ale",
               "broth")),
    ("occupation", ("chef", "painter", "doctor", "violinist", "banker", "gardener", "sailor",
                    "judge", "poet", "baker", "locksmith", "printer", "weaver", "clerk")),
)


def generate(dimensions: int = 3, entities: int = 4, clues: int | None = None,
             clue_types: tuple[str, ...] = ("direct", "negative", "relational", "red_herring"),
             red_herrings: int | None = None, seed: int = 0, max_nodes: int = 50_000) -> Puzzle:
    """Return one puzzle. ``clues`` is a target, not a promise: uniqueness wins ties.

    ``clues=None`` carves down toward a small unique set. The puzzle's ``notes`` and
    ``meta`` record the requested counts and the counts actually kept.
    """
    types = _check_args(dimensions, entities, clues, clue_types, red_herrings)
    red_count = _red_count(clues, entities, types, red_herrings)
    informative_target = None if clues is None else max(0, clues - red_count)
    rng = random.Random(seed)
    categories = _categories(dimensions, entities, "relational" in types)
    assignment = _assignment(rng, len(categories), entities)
    solution = tuple(tuple(categories[c].entities[assignment[c][p]] for c in range(len(categories)))
                     for p in range(entities))
    pos = {(categories[c].name, solution[r][c]): r for r in range(entities) for c in range(len(categories))}

    def holds(clue: Clue) -> bool:
        return _holds(pos, clue)

    pin = [c for c in _pinning(categories, assignment, types) if holds(c)]
    if len(pin) != (len(categories) - 1) * entities and "direct" in types:
        raise RuntimeError("direct pinning set is the wrong size")
    pool = [c for c in _pool(categories, assignment, types) if holds(c)]
    rng.shuffle(pool)
    pin_keys = {_key(c) for c in pin}
    one_type = sum(t in types for t in INFORMATIVE) == 1
    if informative_target is None:
        extra_budget = min(len(pool), max(12, entities))
    elif one_type and informative_target >= len(pin):
        extra_budget = min(len(pool), informative_target - len(pin))
    else:
        extra_budget = min(len(pool), max(0, informative_target - len(pin)) + min(20, max(8, entities)))
    extras = []
    seen = set(pin_keys)
    for clue in pool:
        if len(extras) >= extra_budget:
            break
        k = _key(clue)
        if k in seen:
            continue
        seen.add(k)
        extras.append(clue)
    working = pin + extras
    if not _unique(categories, working, solution, max_nodes):
        raise RuntimeError("pinning clues did not produce a unique grid; this is a generator bug")
    kept = _carve(categories, working, solution, informative_target, rng, max_nodes)
    have = {_key(c) for c in kept}
    if informative_target is not None:
        for clue in pool:
            if len(kept) >= informative_target:
                break
            k = _key(clue)
            if k in have or not holds(clue):
                continue
            kept.append(clue)
            have.add(k)
    herrings = []
    for clue in pool:
        if len(herrings) >= red_count:
            break
        k = _key(clue)
        if k in have or not holds(clue):
            continue
        herrings.append(_as_herring(clue))
        have.add(k)
    if len(herrings) < red_count:
        for clue in _pool(categories, assignment, ("negative",)):
            if len(herrings) >= red_count:
                break
            if not holds(clue) or _key(clue) in have:
                continue
            herrings.append(_as_herring(clue))
            have.add(_key(clue))
    shown = list(kept) + herrings
    rng.shuffle(shown)
    shown_clues = tuple(replace(c, id=f"c{i:03d}") for i, c in enumerate(shown, start=1))
    notes = _notes(clues, red_count, len(kept), len(herrings))
    anchor, other = categories[0], categories[1]
    ask_id = f"{anchor.name}-{solution[0][0]}"
    asks = (Ask(ask_id, f"Which {other.name} is together with {anchor.name} {solution[0][0]}?",
                other.name, anchor.name, solution[0][0]),)
    puzzle = Puzzle(
        id=_puzzle_id(dimensions, entities, clues, seed, types),
        title=f"Generated grid ({dimensions} by {entities}, seed {seed})",
        source="generated", memorization_risk="low", categories=tuple(categories),
        clues=shown_clues, solution=solution,
        question="State the full matching. " + asks[0].prompt,
        asks=asks, notes=notes, meta=())
    final = solve(puzzle, limit=2, max_nodes=max(max_nodes, 200_000))
    if not final.complete or len(final.solutions) != 1:
        raise RuntimeError(
            "could not prove the generated puzzle has one solution; raise max_nodes or include direct clues")
    if final.solutions[0] != solution:
        raise RuntimeError("solver grid does not match the grid the clues were drawn from")
    for clue in puzzle.clues:
        if not holds(clue):
            raise RuntimeError(f"clue {clue.id} is not true of the generated solution")
    meta = (
        ("seed", str(seed)), ("dimensions", str(dimensions)), ("entities", str(entities)),
        ("requested_clues", "" if clues is None else str(clues)),
        ("informative_clues", str(len(kept))), ("red_herrings", str(len(herrings))),
        ("clue_types", ",".join(types)), ("nodes", str(final.nodes)),
        ("max_nodes", str(max_nodes)),
    )
    puzzle = replace(puzzle, meta=meta)
    validate_solution(puzzle)
    return puzzle


def _check_args(dimensions, entities, clues, clue_types, red_herrings) -> tuple[str, ...]:
    if not isinstance(dimensions, int) or dimensions < 2 or dimensions > MAX_DIMENSIONS:
        raise ValueError(f"dimensions must be an integer from 2 to {MAX_DIMENSIONS}")
    if not isinstance(entities, int) or entities < 2 or entities > MAX_ENTITIES:
        raise ValueError(f"entities must be an integer from 2 to {MAX_ENTITIES}")
    if clues is not None and (not isinstance(clues, int) or clues < 0):
        raise ValueError("clues must be a non-negative integer or None")
    if red_herrings is not None and (not isinstance(red_herrings, int) or red_herrings < 0):
        raise ValueError("red_herrings must be a non-negative integer or None")
    if not clue_types:
        raise ValueError("clue_types must name at least one informative type")
    unknown = [t for t in clue_types if t not in INFORMATIVE and t != "red_herring"]
    if unknown:
        raise ValueError(f"unknown clue types: {', '.join(unknown)}")
    types = tuple(dict.fromkeys(clue_types))
    if not any(t in types for t in INFORMATIVE):
        raise ValueError("clue_types needs direct, negative, or relational so a unique grid exists")
    if "direct" not in types and "relational" not in types:
        pin_size = (dimensions - 1) * entities * (entities - 1)
        if pin_size > 20_000:
            raise ValueError("negative-only puzzles of this size are too large to verify; include direct or relational")
    return types


def _red_count(clues, entities, types, red_herrings) -> int:
    if red_herrings is not None:
        return red_herrings
    if "red_herring" not in types:
        return 0
    natural = max(1, entities // 3)
    if clues is None:
        return natural
    if clues < 3:
        return 0
    return min(natural, max(1, clues // 5))


def _entities(label: str, pool: tuple[str, ...], n: int) -> tuple[str, ...]:
    picked = list(pool[:n])
    while len(picked) < n:
        picked.append(f"{label}-{len(picked) + 1}")
    if len(set(picked)) != len(picked):
        raise RuntimeError(f"duplicate names in the {label} pool")
    return tuple(picked)


def _categories(dimensions: int, entities: int, ordered: bool) -> list[Category]:
    categories = []
    if ordered:
        categories.append(Category("house", tuple(str(i) for i in range(1, entities + 1)), ordered=True))
    for name, pool in POOLS:
        if len(categories) == dimensions:
            break
        categories.append(Category(name, _entities(name, pool, entities)))
    while len(categories) < dimensions:
        label = f"group{len(categories)}"
        categories.append(Category(label, tuple(f"{label}-{i}" for i in range(1, entities + 1))))
    return categories


def _assignment(rng: random.Random, k: int, n: int) -> list[list[int]]:
    columns = []
    for c in range(k):
        perm = list(range(n))
        if c != 0:
            rng.shuffle(perm)
        columns.append(perm)
    return columns


def _at(categories, assignment, c: int, p: int) -> Atom:
    return Atom(categories[c].name, categories[c].entities[assignment[c][p]])


def _key(clue: Clue) -> tuple:
    left = (clue.left.category, clue.left.entity) if clue.left else None
    right = (clue.right.category, clue.right.entity) if clue.right else None
    kind = clue.fact if clue.kind == "red_herring" and clue.fact else clue.kind
    return (kind, left, right, clue.relation)


def _make(kind: str, left: Atom, right: Atom, relation: str | None = None) -> Clue:
    if relation == "next_to" and (left.category, left.entity) > (right.category, right.entity):
        left, right = right, left
    return Clue("", kind, describe(kind, left, right, relation), left, right, relation)


def _pinning(categories, assignment, types: tuple[str, ...]) -> list[Clue]:
    n, k = len(categories[0].entities), len(categories)
    clues = []
    if "direct" in types:
        for c in range(1, k):
            for p in range(n):
                clues.append(_make("direct", _at(categories, assignment, 0, p), _at(categories, assignment, c, p)))
        return clues
    if "relational" in types:
        for c in range(1, k):
            for p in range(n):
                if p + 1 < n:
                    clues.append(_make("relational", _at(categories, assignment, c, p),
                                       _at(categories, assignment, 0, p + 1), "immediately_left_of"))
                else:
                    clues.append(_make("relational", _at(categories, assignment, c, p),
                                       _at(categories, assignment, 0, p - 1), "immediately_right_of"))
        return clues
    for c in range(1, k):
        for p in range(n):
            for other in range(n):
                if other == p:
                    continue
                clues.append(_make("negative", _at(categories, assignment, 0, p),
                                   _at(categories, assignment, c, other)))
    return clues


def _pool(categories, assignment, types: tuple[str, ...]) -> list[Clue]:
    n, k = len(categories[0].entities), len(categories)
    ordered = categories[0].ordered
    clues: list[Clue] = []
    pairs = [(a, b) for a in range(k) for b in range(a + 1, k)]
    if "direct" in types:
        for a, b in pairs:
            for p in range(n):
                clues.append(_make("direct", _at(categories, assignment, a, p), _at(categories, assignment, b, p)))
    if "negative" in types:
        # Cap the negative cloud. The pinning set, when it is negative-only, is built separately.
        budget = 4_000
        for a, b in pairs:
            for p in range(n):
                for other in range(n):
                    if other == p:
                        continue
                    clues.append(_make("negative", _at(categories, assignment, a, p),
                                       _at(categories, assignment, b, other)))
                    if len(clues) >= budget and "direct" not in types and "relational" not in types:
                        return clues
                    if len(clues) >= budget:
                        break
                else:
                    continue
                break
            else:
                continue
            break
    if "relational" in types and ordered:
        for a in range(k):
            for b in range(k):
                if a == 0 and b == 0:
                    continue
                for p in range(n - 1):
                    clues.append(_make("relational", _at(categories, assignment, a, p),
                                       _at(categories, assignment, b, p + 1), "immediately_left_of"))
                    clues.append(_make("relational", _at(categories, assignment, a, p),
                                       _at(categories, assignment, b, p + 1), "next_to"))
                for p in range(n):
                    for q in range(p + 2, n):
                        clues.append(_make("relational", _at(categories, assignment, a, p),
                                           _at(categories, assignment, b, q), "left_of"))
                        if len(clues) >= 4_000:
                            return clues
    return clues


def _holds(pos: dict[tuple[str, str], int], clue: Clue) -> bool:
    kind = clue.fact if clue.kind == "red_herring" else clue.kind
    if kind == "flavor":
        return True
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


def _as_herring(clue: Clue) -> Clue:
    return Clue("", "red_herring", clue.text, clue.left, clue.right, clue.relation, fact=clue.kind)


def _numbered(clues: list[Clue]) -> tuple[Clue, ...]:
    return tuple(replace(c, id=f"t{i:04d}") for i, c in enumerate(clues))


def _unique(categories, clues, solution, max_nodes: int) -> bool:
    if not clues:
        return False
    trial = Puzzle(
        id="trial", title="trial", source="generated", memorization_risk="low",
        categories=tuple(categories), clues=_numbered(clues), solution=tuple(solution),
        question="trial", asks=())
    found = solve(trial, limit=2, max_nodes=max_nodes)
    return found.complete and len(found.solutions) == 1


def _carve(categories, working, solution, target: int | None, rng: random.Random, max_nodes: int) -> list[Clue]:
    directs = [c for c in working if c.kind == "direct"]
    others = [c for c in working if c.kind != "direct"]
    rng.shuffle(directs)
    rng.shuffle(others)
    kept = list(working)
    for clue in directs + others:
        if target is not None and len(kept) <= target:
            break
        trial = [c for c in kept if c is not clue]
        if len(trial) == len(kept):
            continue
        if _unique(categories, trial, solution, max_nodes):
            kept = trial
    return kept


def _notes(requested: int | None, red_requested: int, informative: int, herrings: int) -> str:
    info = _plural(informative, "informative clue")
    herr = _plural(herrings, "red herring")
    if requested is None:
        return f"Carved toward a small unique set: {info} and {herr}."
    body = f"Requested {requested} clues with {_plural(red_requested, 'red herring')}. Kept {info} and {herr}."
    if informative + herrings != requested or herrings != red_requested:
        body += " Uniqueness, not the requested count, decided the size."
    return body


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _puzzle_id(dimensions, entities, clues, seed, types) -> str:
    count = "min" if clues is None else str(clues)
    tag = "".join({"direct": "d", "negative": "n", "relational": "r", "red_herring": "h"}[t] for t in types)
    return f"gen-d{dimensions}-e{entities}-c{count}-s{seed}-{tag}"
