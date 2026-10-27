"""Command line for the Murdle eval.

    uv run python -m evals.murdle list
    uv run python -m evals.murdle run --puzzle terrace --agent reference
    uv run python -m evals.murdle generate --dimensions 4 --entities 5 --clues 18 --seed 1
    uv run python -m evals.murdle scale --entities 3,4,5 --dimensions 3 --agent reference
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.murdle.agents import build_agent
from evals.murdle.classic import catalog
from evals.murdle.generate import generate
from evals.murdle.harness import run_eval, scale_eval
from evals.murdle.model import dump_puzzle, load_puzzle
from evals.murdle.solver import solve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.murdle", description="Murdle-style evals for agents using tms.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list the hand-written puzzles")

    solve_p = sub.add_parser("solve", help="show the unique grid for a puzzle")
    solve_p.add_argument("--puzzle", choices=tuple(catalog()))
    solve_p.add_argument("--file", type=Path)

    gen = sub.add_parser("generate", help="write one uniquely solvable puzzle as JSON")
    _gen_args(gen)
    gen.add_argument("--out", type=Path)

    run_p = sub.add_parser("run", help="score an agent with tms and without it")
    run_p.add_argument("--puzzle", action="append", default=[], choices=tuple(catalog()))
    run_p.add_argument("--all", action="store_true")
    run_p.add_argument("--file", type=Path)
    run_p.add_argument("--generate", action="store_true", help="also run a freshly generated puzzle")
    _gen_args(run_p)
    _agent_args(run_p)
    run_p.add_argument("--json", action="store_true")
    run_p.add_argument("--out", type=Path)
    run_p.add_argument("--strict", action="store_true", help="exit 1 unless every mode is solved with no error")

    scale = sub.add_parser("scale", help="score an agent as the grid grows")
    scale.add_argument("--entities", default="3,4,5", help="comma list of grid sizes")
    scale.add_argument("--seeds", default="0", help="comma list of seeds")
    _gen_args(scale, entities=False, seed=False)
    _agent_args(scale)
    scale.add_argument("--json", action="store_true")
    scale.add_argument("--strict", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "list":
        return _list()
    if args.cmd == "solve":
        return _solve(args)
    if args.cmd == "generate":
        return _generate(args)
    if args.cmd == "run":
        return _run(args)
    if args.cmd == "scale":
        return _scale(args)
    parser.error(f"unknown command {args.cmd}")
    return 2


def _gen_args(parser: argparse.ArgumentParser, *, entities: bool = True, seed: bool = True) -> None:
    parser.add_argument("--dimensions", type=int, default=3)
    if entities:
        parser.add_argument("--entities", type=int, default=4)
    parser.add_argument("--clues", type=int, default=None)
    parser.add_argument("--clue-types", default="direct,negative,relational,red_herring")
    parser.add_argument("--red-herrings", type=int, default=None)
    if seed:
        parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-nodes", type=int, default=50_000)


def _agent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", default="reference", choices=("reference", "mock", "openai"))
    parser.add_argument("--modes", default="tms,baseline")
    parser.add_argument("--max-steps", type=int, default=24)


def _types(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _ints(text: str) -> list[int]:
    try:
        return [int(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise ValueError(f"expected a comma list of integers, got {text!r}") from None


def _modes(text: str) -> tuple[str, ...]:
    modes = tuple(part.strip() for part in text.split(",") if part.strip())
    if not modes or any(mode not in ("tms", "baseline") for mode in modes):
        raise ValueError("modes is a comma list of tms and baseline")
    return modes


def _make_generated(args):
    return generate(
        dimensions=args.dimensions, entities=args.entities, clues=args.clues,
        clue_types=_types(args.clue_types), red_herrings=args.red_herrings,
        seed=args.seed, max_nodes=args.max_nodes)


def _list() -> int:
    print(f"{'id':10} {'risk':6} {'grid':8} {'clues':6} title")
    for puzzle in catalog().values():
        grid = f"{len(puzzle.categories)}x{len(puzzle.categories[0].entities)}"
        print(f"{puzzle.id:10} {puzzle.memorization_risk:6} {grid:8} {len(puzzle.clues):<6} {puzzle.title}")
    return 0


def _solve(args) -> int:
    puzzle = _one(args)
    if puzzle is None:
        return 2
    found = solve(puzzle, limit=2)
    names = [cat.name for cat in puzzle.categories]
    print("\t".join(names))
    for row in (found.solutions[0] if found.solutions else puzzle.solution):
        print("\t".join(row))
    print(f"solutions={len(found.solutions)} complete={found.complete} nodes={found.nodes}", file=sys.stderr)
    return 0 if found.complete and len(found.solutions) == 1 else 1


def _one(args):
    if args.file:
        return load_puzzle(args.file.read_text())
    if args.puzzle:
        return catalog()[args.puzzle]
    print("pass --puzzle or --file", file=sys.stderr)
    return None


def _generate(args) -> int:
    try:
        puzzle = _make_generated(args)
    except (ValueError, RuntimeError) as err:
        print(str(err), file=sys.stderr)
        return 1
    text = dump_puzzle(puzzle)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(args.out)
    else:
        sys.stdout.write(text)
    print(f"{puzzle.id}: {len(puzzle.clues)} clues. {puzzle.notes}", file=sys.stderr)
    return 0


def _agent(args):
    agent = build_agent(args.agent, max_steps=args.max_steps)
    if args.agent == "openai":
        agent.require_credentials()
    return agent


def _run(args) -> int:
    try:
        agent = _agent(args)
        modes = _modes(args.modes)
    except (RuntimeError, ValueError) as err:
        print(str(err), file=sys.stderr)
        return 2
    puzzles = []
    if args.all:
        puzzles.extend(catalog().values())
    for name in args.puzzle:
        puzzles.append(catalog()[name])
    if args.file:
        puzzles.append(load_puzzle(args.file.read_text()))
    if args.generate:
        try:
            puzzles.append(_make_generated(args))
        except (ValueError, RuntimeError) as err:
            print(str(err), file=sys.stderr)
            return 1
    seen = set()
    chosen = []
    for puzzle in puzzles:
        if puzzle.id in seen:
            continue
        seen.add(puzzle.id)
        chosen.append(puzzle)
    if not chosen:
        print("name a --puzzle, or pass --all, --file, or --generate", file=sys.stderr)
        return 2
    reports = [run_eval(puzzle, agent, modes=modes, max_steps=args.max_steps) for puzzle in chosen]
    payload = reports[0] if len(reports) == 1 else reports
    _emit(payload, args)
    if args.strict and any(_bad(report) for report in reports):
        return 1
    return 0


def _scale(args) -> int:
    try:
        agent = _agent(args)
        modes = _modes(args.modes)
        entities = _ints(args.entities)
        seeds = _ints(args.seeds)
    except (RuntimeError, ValueError) as err:
        print(str(err), file=sys.stderr)
        return 2
    if not entities or not seeds:
        print("scale needs at least one size and one seed", file=sys.stderr)
        return 2
    try:
        rows = scale_eval(
            entities, args.dimensions, seeds, agent, clue_types=_types(args.clue_types),
            clues=args.clues, red_herrings=args.red_herrings, modes=modes,
            max_steps=args.max_steps, max_nodes=args.max_nodes)
    except (ValueError, RuntimeError) as err:
        print(str(err), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(f"{'entities':8} {'seed':5} {'clues':6} {'mode':9} {'accuracy':8} {'exact':5} "
              f"{'steps':6} {'tokens':7} {'seconds':8} {'links':6} {'contradictions'}")
        for row in rows:
            if row.get("error") and "mode" not in row:
                print(f"{row['entities']:<8} {row['seed']:<5} error: {row['error']}")
                continue
            print(f"{row['entities']:<8} {row['seed']:<5} {row['clues']:<6} {row['mode']:<9} "
                  f"{row['accuracy']:<8.2f} {str(row['exact_match']):<5} {row['steps']:<6} "
                  f"{row['tokens']:<7} {row['seconds']:<8.3f} {row['links']:<6} {row['contradictions_valid']}")
    if args.strict and any(row.get("error") or row.get("solved") is False for row in rows):
        return 1
    return 0


def _emit(payload, args) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    if args.json:
        sys.stdout.write(text)
        return
    reports = payload if isinstance(payload, list) else [payload]
    for report in reports:
        _print_report(report)


def _print_report(report: dict) -> None:
    print(f"{report['puzzle_id']}  {report['agent']}  risk={report['memorization_risk']}  "
          f"{report['dimensions']}x{report['entities']}  clues={report['clues']}")
    if report.get("notes"):
        print(f"  {report['notes']}")
    for mode, metrics in report["modes"].items():
        trail = "n/a" if metrics["trail_score"] is None else f"{metrics['trail_score']:.2f}"
        print(f"  {mode:8} accuracy={metrics['accuracy']:.2f} exact={metrics['exact_match']} "
              f"answers={metrics['answer_accuracy']:.2f} claims={metrics['claims']} links={metrics['links']} "
              f"contradictions={metrics['contradictions_valid']} steps={metrics['steps']} "
              f"tokens={metrics['tokens']} trail={trail}")
        if metrics["error"]:
            print(f"    error: {metrics['error']}")


def _bad(report: dict) -> bool:
    return any(metrics["error"] or not metrics["solved"] for metrics in report["modes"].values())
