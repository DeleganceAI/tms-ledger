"""What an agent is allowed to see. The answer key stays in the harness."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evals.murdle.model import Ask, Category, Clue, Puzzle


@dataclass
class Task:
    mode: str
    puzzle_id: str
    title: str
    question: str
    categories: tuple[Category, ...]
    asks: tuple[Ask, ...]
    prompt: str
    session: Any = None
    formal_clues: tuple[Clue, ...] | None = None
    max_steps: int = 24


def render_prompt(puzzle: Puzzle, mode: str) -> str:
    """User message for one run. Baseline includes clue sentences; tms mode does not."""
    lines = [
        f"Puzzle: {puzzle.title}",
        f"Question: {puzzle.question}",
        "",
        "Categories. Each row uses exactly one entity from each category, and each entity is used once.",
    ]
    for cat in puzzle.categories:
        axis = " This category is ordered left to right and is the row axis." if cat.ordered else ""
        lines.append(f"- {cat.name}:{axis} {', '.join(cat.entities)}")
    if puzzle.asks:
        lines.append("")
        lines.append("Answer these too, using the entity strings exactly. Keys are the ids in front.")
        for ask in puzzle.asks:
            lines.append(f"- {ask.id}: {ask.prompt}")
    lines.append("")
    if mode == "baseline":
        lines.append("Clues. Every clue is true.")
        for i, clue in enumerate(puzzle.clues, start=1):
            lines.append(f"{i}. {clue.text}")
        lines.append("")
        lines.append("There is no ledger in this run. Reason from the clues above and submit the grid.")
    elif mode == "tms":
        lines.append(
            f"The {len(puzzle.clues)} clues are evidence records in this collection. "
            "They are not copied into this message. Read every document with the ledger tools, "
            "record claims and verbatim links as you decide, record a contradiction when two "
            "claims cannot both be true, then submit the grid.")
    else:
        raise ValueError("mode must be tms or baseline")
    lines.append("")
    lines.append("The solution is a list of rows. Each row maps every category name to one entity.")
    lines.append("answers is an object whose keys are the question ids above.")
    lines.append("When you record a claim, its text is exactly one line with tab-separated fields:")
    lines.append("PAIR<TAB>category<TAB>entity<TAB>category<TAB>entity")
    lines.append("NOT<TAB>category<TAB>entity<TAB>category<TAB>entity")
    lines.append("REL<TAB>category<TAB>entity<TAB>relation<TAB>category<TAB>entity")
    lines.append("Relations: immediately_left_of, immediately_right_of, next_to, left_of, right_of.")
    lines.append("A link's quote is copied from the evidence text, not paraphrased. The reason is your own sentence.")
    return "\n".join(lines)


def prompt_contains_clue(prompt: str, text: str) -> bool:
    for line in prompt.splitlines():
        if line == text:
            return True
        if ". " in line:
            head, tail = line.split(". ", 1)
            if head.isdigit() and tail == text:
                return True
    return False
