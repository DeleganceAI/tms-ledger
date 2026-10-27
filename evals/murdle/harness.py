"""Run one puzzle, or a size sweep, in tms mode and in the no-ledger baseline."""
from __future__ import annotations

import re
import time

from tms import events as E

from evals.murdle.generate import generate
from evals.murdle.model import Puzzle
from evals.murdle.score import score_run
from evals.murdle.session import EvalCollection
from evals.murdle.task import Task, render_prompt


def collection_slug(puzzle_id: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]", "-", puzzle_id.lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    slug = f"murdle-{cleaned}" if cleaned else "murdle-puzzle"
    if E.SLUG.match(slug) is None:
        return "murdle-puzzle"
    return slug[:80]


def make_task(puzzle: Puzzle, mode: str, *, formal: bool, session=None, max_steps: int = 24) -> Task:
    return Task(
        mode=mode, puzzle_id=puzzle.id, title=puzzle.title, question=puzzle.question,
        categories=puzzle.categories, asks=puzzle.asks, prompt=render_prompt(puzzle, mode),
        session=session, formal_clues=puzzle.clues if formal else None, max_steps=max_steps)


def run_eval(puzzle: Puzzle, agent, modes: tuple[str, ...] = ("tms", "baseline"), max_steps: int = 24) -> dict:
    """Score ``agent`` on ``puzzle``. tms mode loads every clue as evidence first."""
    formal = bool(getattr(agent, "sees_formal", False))
    modes_out = {}
    for mode in modes:
        if mode not in ("tms", "baseline"):
            raise ValueError("modes must be tms, baseline, or both")
        session = None
        if mode == "tms":
            session = EvalCollection(collection_slug(puzzle.id))
            session.load_puzzle(puzzle)
        task = make_task(puzzle, mode, formal=formal, session=session, max_steps=max_steps)
        started = time.perf_counter()
        try:
            result = agent.run(task)
        except Exception as err:
            from evals.murdle.agents import AgentResult
            result = AgentResult(error=f"{err.__class__.__name__}: {err}"[:500])
        modes_out[mode] = score_run(puzzle, result, session, time.perf_counter() - started)
    return {
        "puzzle_id": puzzle.id,
        "title": puzzle.title,
        "source": puzzle.source,
        "memorization_risk": puzzle.memorization_risk,
        "dimensions": len(puzzle.categories),
        "entities": len(puzzle.categories[0].entities),
        "clues": len(puzzle.clues),
        "notes": puzzle.notes,
        "agent": getattr(agent, "name", type(agent).__name__),
        "agent_sees_formal_clues": formal,
        "modes": modes_out,
        "comparison": _comparison(modes_out),
    }


def _comparison(modes: dict) -> dict:
    if "tms" not in modes or "baseline" not in modes:
        return {}
    return {
        "accuracy_tms": modes["tms"]["accuracy"],
        "accuracy_baseline": modes["baseline"]["accuracy"],
        "accuracy_delta": modes["tms"]["accuracy"] - modes["baseline"]["accuracy"],
        "tms_links": modes["tms"]["links"],
        "baseline_links": modes["baseline"]["links"],
        "tms_contradictions_valid": modes["tms"]["contradictions_valid"],
        "tms_trail_score": modes["tms"]["trail_score"],
    }


def scale_eval(entity_sizes: list[int], dimensions: int, seeds: list[int], agent, *,
               clue_types: tuple[str, ...] = ("direct", "negative", "relational", "red_herring"),
               clues: int | None = None, red_herrings: int | None = None,
               modes: tuple[str, ...] = ("tms", "baseline"), max_steps: int = 24,
               max_nodes: int = 50_000) -> list[dict]:
    """Generate a grid at each size and score the agent. One bad size does not stop the sweep."""
    rows = []
    for entities in entity_sizes:
        for seed in seeds:
            started = time.perf_counter()
            try:
                puzzle = generate(dimensions=dimensions, entities=entities, clues=clues, clue_types=clue_types,
                                  red_herrings=red_herrings, seed=seed, max_nodes=max_nodes)
            except (ValueError, RuntimeError) as err:
                rows.append({"entities": entities, "dimensions": dimensions, "seed": seed, "error": str(err)})
                continue
            generate_seconds = round(time.perf_counter() - started, 6)
            report = run_eval(puzzle, agent, modes=modes, max_steps=max_steps)
            for mode, metrics in report["modes"].items():
                rows.append({
                    "puzzle_id": puzzle.id, "entities": entities, "dimensions": dimensions, "seed": seed,
                    "clues": len(puzzle.clues),
                    "informative_clues": puzzle.meta_dict().get("informative_clues", ""),
                    "generate_seconds": generate_seconds, "mode": mode,
                    "accuracy": metrics["accuracy"], "exact_match": metrics["exact_match"],
                    "solved": metrics["solved"], "steps": metrics["steps"], "tokens": metrics["tokens"],
                    "seconds": metrics["seconds"], "links": metrics["links"],
                    "contradictions_valid": metrics["contradictions_valid"],
                    "trail_score": metrics["trail_score"], "error": metrics["error"],
                })
    return rows
