"""Agents. ``reference`` and ``mock`` need no credentials. ``openai`` calls a chat API.

``reference`` is an oracle: it solves from the formal clues the generator already
has, then, in tms mode, writes the trail into the collection. It does not receive
the answer key. It is the offline stand-in so the harness, the quote rule, and the
scorer run without a model. It is not a subject.

``mock`` solves the same way and writes nothing, including in tms mode.

``openai`` sees only the prompt and the tools. In tms mode the prompt does not
contain the clues. Set TMS_EVAL_API_KEY (or OPENAI_API_KEY or CHAT_API_KEY) and
TMS_EVAL_MODEL (or CHAT_MODEL). TMS_EVAL_BASE_URL, OPENAI_BASE_URL, or CHAT_URL is
the prefix in front of ``/chat/completions``; the default is ``https://api.openai.com/v1``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace

import httpx

from evals.murdle.claims import claim_line, encode_pair
from evals.murdle.model import Puzzle
from evals.murdle.solver import partner, solve
from evals.murdle.task import Task, prompt_contains_clue

_KEY_VARS = ("TMS_EVAL_API_KEY", "OPENAI_API_KEY", "CHAT_API_KEY")
_MODEL_VARS = ("TMS_EVAL_MODEL", "CHAT_MODEL")
_URL_VARS = ("TMS_EVAL_BASE_URL", "OPENAI_BASE_URL", "CHAT_URL")


@dataclass
class AgentResult:
    solution: list | None = None
    answers: dict | None = None
    steps: int = 0
    tokens: int = 0
    proof_ok: bool | None = None
    error: str | None = None
    raw: str = ""
    extras: dict = field(default_factory=dict)


def _project(task: Task, rows: tuple[tuple[str, ...], ...]) -> tuple[list[dict], dict]:
    names = [cat.name for cat in task.categories]
    dicts = [{names[i]: row[i] for i in range(len(names))} for row in rows]
    answers = {}
    for ask in task.asks:
        for row in dicts:
            if row.get(ask.with_category) == ask.with_entity:
                answers[ask.id] = row[ask.category]
                break
    return dicts, answers


def _formal_puzzle(task: Task) -> Puzzle:
    return Puzzle(
        id=task.puzzle_id, title=task.title, source="original", memorization_risk="low",
        categories=task.categories, clues=tuple(task.formal_clues or ()), solution=(),
        question=task.question, asks=task.asks)


def solve_formal(task: Task) -> tuple[tuple[tuple[str, ...], ...] | None, str | None]:
    """Unique grid from formal clues, or an error string. Does not read ``solution``."""
    if not task.formal_clues:
        return None, "this agent was not given formal clues"
    found = solve(_formal_puzzle(task), limit=2)
    if not found.complete or len(found.solutions) != 1:
        return None, "solver did not prove a unique grid"
    return found.solutions[0], None


class MockAgent:
    """Solves from formal clues and does not touch the ledger."""

    name = "mock"
    sees_formal = True

    def run(self, task: Task) -> AgentResult:
        rows, err = solve_formal(task)
        if err or rows is None:
            return AgentResult(error=err or "no solution")
        solution, answers = _project(task, rows)
        return AgentResult(solution=solution, answers=answers, steps=0, tokens=0)


class ScriptedAgent:
    """Returns a canned grid. Tests use it to check the scorer."""

    name = "scripted"
    sees_formal = False

    def __init__(self, solution: list | None = None, answers: dict | None = None, error: str | None = None):
        self.solution = solution or []
        self.answers = answers or {}
        self.error = error

    def run(self, task: Task) -> AgentResult:
        return AgentResult(solution=self.solution, answers=self.answers, error=self.error, steps=0, tokens=0)


class ReferenceAgent:
    """Oracle solver that records a trail when the run has a collection."""

    name = "reference"
    sees_formal = True

    def run(self, task: Task) -> AgentResult:
        rows, err = solve_formal(task)
        if err or rows is None:
            return AgentResult(error=err or "no solution")
        solution, answers = _project(task, rows)
        if task.mode == "baseline":
            missing = [c.id for c in task.formal_clues or () if not prompt_contains_clue(task.prompt, c.text)]
            if missing:
                return AgentResult(error="clues missing from the baseline prompt: " + ", ".join(missing[:5]))
            return AgentResult(solution=solution, answers=answers, steps=1, tokens=0)
        if task.session is None:
            return AgentResult(error="tms mode requires a collection")
        evidence = _read_evidence(task.session)
        missing = [c.id for c in task.formal_clues or () if c.text not in evidence]
        if missing:
            return AgentResult(error="clues missing from the collection: " + ", ".join(missing[:5]),
                               steps=task.session.tool_calls)
        proof_ok = _write_trail(task, rows, evidence, answers)
        return AgentResult(solution=solution, answers=answers, steps=task.session.tool_calls, tokens=0,
                           proof_ok=proof_ok)


def _read_evidence(session) -> dict[str, str]:
    found: dict[str, str] = {}
    offset = 0
    while True:
        page = session.list_evidence(limit=500, offset=offset)
        for row in page:
            event = session.get_event(row["id"])
            found[event["content"]["text"]] = event["id"]
        if len(page) < 500:
            return found
        offset += 500


def _write_trail(task: Task, rows, evidence: dict[str, str], answers: dict) -> bool:
    session = task.session
    made: dict[str, str] = {}
    first_ev = first_claim = None

    def claim(text: str) -> str:
        if text not in made:
            made[text] = session.add_claim(text)["id"]
        return made[text]

    for clue in task.formal_clues or ():
        line = claim_line(clue)
        if line is None:
            continue
        ev_id = evidence[clue.text]
        cid = claim(line)
        session.add_link(ev_id, cid, "SUPPORTS", clue.text, "The clue states this.")
        if first_ev is None:
            first_ev, first_claim = ev_id, cid
    _contradict_one_negative(task, rows, evidence, claim)
    if first_ev is None or first_claim is None:
        return False
    said = " ".join(f"{ask.prompt} {answers[ask.id]}." for ask in task.asks if ask.id in answers)
    proof = {"question": task.question, "steps": [
        {"id": "s1", "say": "The clues are stored as evidence.", "from": [first_ev]},
        {"id": "s2", "say": "The claims drawn from those clues fix one grid.", "from": [first_claim]},
        {"id": "root", "say": said or "The submitted grid is the unique matching.", "from": ["s1", "s2"]},
    ]}
    checked = session.check_proof(proof)
    return bool(checked["ok"])


def _contradict_one_negative(task: Task, rows, evidence: dict[str, str], claim) -> None:
    negative = next((c for c in task.formal_clues or ()
                     if (c.fact or c.kind) == "negative" and c.kind != "red_herring"), None)
    if negative is None or negative.left is None or negative.right is None:
        return
    solved = replace(_formal_puzzle(task), solution=rows)
    true_right = partner(solved, negative.left, negative.right.category)
    if true_right == negative.right:
        return
    false_id = claim(encode_pair(negative.left, negative.right))
    true_id = claim(encode_pair(negative.left, true_right))
    session = task.session
    session.add_link(evidence[negative.text], false_id, "REBUTS", negative.text, "The clue denies this pairing.")
    session.add_contradiction(
        [false_id, true_id],
        f"{negative.left.category} {negative.left.entity} cannot be paired with both "
        f"{negative.right.entity} and {true_right.entity} in {negative.right.category}.")


class OpenAIAgent:
    """Tool-calling chat model. Talks to the network only inside ``run``."""

    name = "openai"
    sees_formal = False

    def __init__(self, max_steps: int = 24):
        self.max_steps = max_steps

    def require_credentials(self) -> tuple[str, str, str]:
        key = next((os.environ[name] for name in _KEY_VARS if os.environ.get(name)), "")
        model = next((os.environ[name] for name in _MODEL_VARS if os.environ.get(name)), "")
        base = next((os.environ[name] for name in _URL_VARS if os.environ.get(name)), "https://api.openai.com/v1")
        if not key or not model:
            raise RuntimeError(
                "openai agent needs a key (TMS_EVAL_API_KEY, OPENAI_API_KEY, or CHAT_API_KEY) "
                "and a model (TMS_EVAL_MODEL or CHAT_MODEL). No key is read from disk.")
        return key, base.rstrip("/"), model

    def run(self, task: Task) -> AgentResult:
        try:
            key, base, model = self.require_credentials()
        except RuntimeError as err:
            return AgentResult(error=str(err))
        tools = _tool_specs(task.mode)
        system = _SYSTEM_TMS if task.mode == "tms" else _SYSTEM_BASELINE
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task.prompt},
        ]
        budget = task.max_steps or self.max_steps
        tokens = 0
        steps = 0
        submitted = None
        raw = ""
        try:
            for _ in range(max(1, budget)):
                steps += 1
                message, used = _complete(base, key, model, messages, tools)
                tokens += used
                messages.append(_assistant(message))
                raw = message.get("content") or raw
                calls = message.get("tool_calls") or []
                if not calls:
                    submitted = submitted or _extract_submission(message.get("content") or "")
                    break
                stop = False
                for call in calls:
                    name = call.get("function", {}).get("name", "")
                    args = _args(call)
                    if name == "submit_answer":
                        submitted = args
                        payload = {"ok": True}
                        stop = True
                    else:
                        payload = _dispatch(task.session, name, args)
                    messages.append({
                        "role": "tool", "tool_call_id": call.get("id", ""),
                        "content": _clip(payload),
                    })
                if stop:
                    break
        except (httpx.HTTPError, RuntimeError) as err:
            return AgentResult(error=f"model request failed: {err.__class__.__name__}: {str(err)[:200]}",
                               steps=steps, tokens=tokens)
        if not submitted:
            return AgentResult(error="model did not submit an answer", steps=steps, tokens=tokens, raw=raw[:500])
        return AgentResult(
            solution=submitted.get("solution") if isinstance(submitted, dict) else [],
            answers=submitted.get("answers") if isinstance(submitted, dict) else {},
            steps=steps, tokens=tokens, raw=raw[:500])


def build_agent(name: str, *, max_steps: int = 24):
    if name == "reference":
        return ReferenceAgent()
    if name == "mock":
        return MockAgent()
    if name == "openai":
        return OpenAIAgent(max_steps=max_steps)
    raise ValueError(f"unknown agent {name!r}; choose reference, mock, or openai")


_SYSTEM_TMS = """\
You solve a logic-grid puzzle from a TMS collection and from nothing else.
The collection holds evidence (the clues), claims, links, and contradictions.
A link cites one evidence id, copies a quote that appears in that evidence, and says why.
SUPPORTS, REBUTS, and QUALIFIES are the only relations. QUALIFIES targets a claim.
A contradiction names two or more claims that cannot all be true, and says why.
Search and list tools do not decide truth. Write the claims yourself.
Claim text uses the tab format in the user message, with no extra words.
Read every clue before you answer. Then call submit_answer once.
"""

_SYSTEM_BASELINE = """\
You solve a logic-grid puzzle from the clues in the user message. There is no ledger.
Call submit_answer once with the full grid and the asked answers.
Use the entity strings exactly as listed.
"""


def _tool_specs(mode: str) -> list[dict]:
    submit = {"type": "function", "function": {
        "name": "submit_answer",
        "description": "Submit the finished grid and the answers to the asked questions.",
        "parameters": {"type": "object", "properties": {
            "solution": {"type": "array", "items": {"type": "object"},
                         "description": "One object per row, category name to entity."},
            "answers": {"type": "object", "description": "Map of question id to entity."},
        }, "required": ["solution", "answers"]},
    }}
    if mode != "tms":
        return [submit]
    specs = []
    for name, description, properties, required in _TMS_TOOLS:
        specs.append({"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        }})
    specs.append(submit)
    return specs


_S = {"type": "string"}
_I = {"type": "integer"}
_B = {"type": "boolean"}
_TMS_TOOLS = (
    ("list_evidence", "Evidence documents, oldest first, without their text. Page with offset.",
     {"ungrounded_only": _B, "source": _S, "limit": _I, "offset": _I}, []),
    ("get_event", "One event by id. Evidence text is a window of max_chars at offset.",
     {"id": _S, "offset": _I, "max_chars": _I}, ["id"]),
    ("search_claims", "Find claims by keyword overlap. vector falls back to keywords in this eval.",
     {"text": _S, "method": _S, "limit": _I}, ["text"]),
    ("list_claims", "Claims with support, qualify, rebut, and contradiction counts.",
     {"sort": _S, "limit": _I, "offset": _I}, []),
    ("get_links", "Links filtered by to_id, from_id, or relation (SUPPORTS, REBUTS, QUALIFIES).",
     {"to_id": _S, "from_id": _S, "relation": _S, "limit": _I, "offset": _I}, []),
    ("search_contradictions", "Contradictions, optionally those naming a claim id or words in the reason.",
     {"claim": _S, "text": _S, "limit": _I}, []),
    ("publish_claim", "Store a claim. Text is one PAIR, NOT, or REL line, tab-separated.",
     {"text": _S}, ["text"]),
    ("publish_link", "Store a link. quote must appear verbatim in evidence from_id.",
     {"from_id": _S, "to_id": _S, "relation": _S, "quote": _S, "reason": _S},
     ["from_id", "to_id", "relation", "quote", "reason"]),
    ("publish_contradiction", "Store a contradiction naming claim ids that cannot all be true.",
     {"claim_ids": {"type": "array", "items": _S}, "reason": _S}, ["claim_ids", "reason"]),
    ("check_proof", "Check a thinking proof. steps have id, say, from, and optional gap.",
     {"proof": {"type": "object"}}, ["proof"]),
)


def _dispatch(session, name: str, args: dict) -> dict:
    if session is None:
        return {"error": "no ledger in the baseline; the clues are in the prompt"}
    fn = {
        "list_evidence": session.list_evidence, "get_event": session.get_event,
        "search_claims": session.search_claims, "list_claims": session.list_claims,
        "get_links": session.get_links, "search_contradictions": session.search_contradictions,
        "check_proof": session.check_proof, "publish_claim": session.add_claim,
        "publish_link": session.add_link, "publish_contradiction": session.add_contradiction,
    }.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    import inspect
    allowed = {p for p, spec in inspect.signature(fn).parameters.items() if spec.kind != inspect.Parameter.KEYWORD_ONLY}
    # count is keyword-only; drop anything else the model invented, including collection.
    cleaned = {k: v for k, v in args.items() if k in allowed and k != "count"}
    try:
        result = fn(**cleaned)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as err:
        return {"error": str(err)[:500]}


def _complete(base: str, key: str, model: str, messages: list[dict], tools: list[dict]) -> tuple[dict, int]:
    response = httpx.post(
        f"{base}/chat/completions", timeout=180,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "tools": tools, "tool_choice": "auto"})
    if response.status_code >= 400:
        raise RuntimeError(f"model HTTP {response.status_code}: {response.text[:300]}")
    body = response.json()
    usage = body.get("usage") or {}
    tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
    return body["choices"][0]["message"], tokens


def _assistant(message: dict) -> dict:
    out = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        out["tool_calls"] = message["tool_calls"]
    if message.get("reasoning_content"):
        out["reasoning_content"] = message["reasoning_content"]
    return out


def _args(call: dict) -> dict:
    raw = call.get("function", {}).get("arguments") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_submission(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("solution" in data or "answers" in data):
            return data
    return None


def _clip(payload) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > 12_000:
        return text[:12_000] + "...(truncated)"
    return text
