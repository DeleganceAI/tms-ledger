"""Chat with a collection, at /c/<slug>/chat: a read-only agent over that collection, on DeepInfra.

Any member can open the page; only approved accounts (TMS_APPROVED, admins, limits lifted in
/admin) can chat, since every turn costs model calls. Nothing is stored. The browser sends the
whole conversation each turn and gets server-sent events back: each tool call, its result, the
records that result pulled up (for the panel beside the chat), the answer, then the updated
conversation to send next time. Tools are the MCP read tools, run as the member and pinned to
the chat's collection.
"""
from __future__ import annotations

import functools
import inspect
import json
import os
import sys
import time
from pathlib import Path

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route

from . import events as E
from . import ledger as L
from .web import cookie_pubkey, db, with_header

CHAT_URL = os.environ.get("CHAT_URL", "https://api.deepinfra.com/v1/openai").rstrip("/")
CHAT_API_KEY = os.environ.get("CHAT_API_KEY") or L.EMBED_API_KEY  # one DeepInfra key for both
CHAT_MODEL = os.environ.get("CHAT_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash")
PRICE_IN = float(os.environ.get("CHAT_PRICE_IN_PER_MTOK", "0.20"))    # USD per million tokens
PRICE_OUT = float(os.environ.get("CHAT_PRICE_OUT_PER_MTOK", "0.60"))
MAX_STEPS = 12          # model calls per turn
MAX_RESULT = 12_000     # chars of one tool result sent back to the model
MAX_HISTORY = 400_000   # chars of conversation the browser may send

# Read tools only: no publish, no fetch_url, no list_collections (the chat has one collection).
TOOLS = ["search_claims", "list_claims", "get_links", "list_evidence", "search_contradictions",
         "get_event", "check_proof"]
TYPES = {"str": "string", "int": "integer", "bool": "boolean"}

SYSTEM = """\
You answer a member's questions from the '{collection}' collection of the Paranoy ledger, and only
from it. The ledger stores evidence (documents), claims, links (evidence that SUPPORTS, REBUTS or
QUALIFIES a target, with a verbatim quote) and contradictions between claims. It never decides
what is true; you report what the records say and mark your own reading as yours.

1. Retrieve: search_claims (vector, then keyword if thin) with the question and rephrasings.
   Follow contradiction_ids with search_contradictions; open get_event on evidence when a quote
   needs context. list_claims and list_evidence give worklists.
2. For a substantive answer, build a thinking proof and call check_proof until it is ok. Steps
   cite event ids; anything no event supports is a step marked "gap": true.
3. Answer concisely. Cite the full 64-character event ids inline. Say plainly what the
   collection does not cover; that is a complete and honest answer.
You can only read. Never answer from general knowledge without saying so.
"""


@functools.cache
def tool_specs() -> list[dict]:
    """OpenAI-style tool definitions from the MCP tools' own signatures and docstrings."""
    from . import server as S
    specs = []
    for name in TOOLS:
        fn = inspect.unwrap(getattr(S, name))
        props = {}
        for p, param in inspect.signature(fn).parameters.items():
            if p in ("request", "collection"):
                continue
            ann = str(param.annotation)
            props[p] = {"type": next((v for k, v in TYPES.items() if ann.startswith(k)), "object")}
        required = [p for p in ("text", "id", "proof") if p in props]
        specs.append({"type": "function", "function": {
            "name": name, "description": inspect.getdoc(fn) or name,
            "parameters": {"type": "object", "properties": props, "required": required}}})
    return specs


def run_tool(pubkey: str, collection: str, name: str, args: dict):
    """One read, as the member, inside the chat's collection."""
    if name not in TOOLS:
        return {"error": f"unknown tool {name}"}
    allowed = tool_specs()[TOOLS.index(name)]["function"]["parameters"]["properties"]
    args = {k: v for k, v in args.items() if k in allowed}
    try:
        with L.connect() as conn:
            fn = getattr(L, name)
            if name == "get_event":
                out = fn(conn, pubkey, **args)
                return out if out and out["collection"] == collection else None  # pinned to this collection
            return fn(conn, pubkey, collection, **args)
    except Exception as err:  # the model reads the message and tries again
        return {"error": str(err)[:500]}


def complete(messages: list[dict], pubkey: str, collection: str) -> dict:
    """One model call. Its tokens go to embed_calls with the chat model's name."""
    r = httpx.post(f"{CHAT_URL}/chat/completions", timeout=180,
                   headers={"Authorization": f"Bearer {CHAT_API_KEY}"} if CHAT_API_KEY else {},
                   json={"model": CHAT_MODEL, "messages": messages, "tools": tool_specs(), "tool_choice": "auto"})
    if r.status_code >= 400:
        raise RuntimeError(f"{CHAT_MODEL}: HTTP {r.status_code} {r.text[:300]}")
    body = r.json()
    usage = body.get("usage") or {}
    tin, tout = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    try:  # ponytail: embed_calls now holds chat calls too; rename it llm_calls if it ever matters
        with L.connect() as conn:
            conn.execute("""INSERT INTO embed_calls (pubkey, collection, model, tokens, cost_usd)
                            VALUES (%s, %s, %s, %s, %s)""",
                         (pubkey, collection, CHAT_MODEL, tin + tout, (tin * PRICE_IN + tout * PRICE_OUT) / 1e6))
    except Exception as err:  # telemetry never fails a chat
        print(f"embed_calls logging failed: {err}", file=sys.stderr)
    return body["choices"][0]["message"]


def history(raw) -> list[dict]:
    """The conversation as the browser sent it: user, assistant and tool messages only."""
    if not isinstance(raw, list) or len(json.dumps(raw)) > MAX_HISTORY:
        raise ValueError(f"messages must be a list under {MAX_HISTORY:,} characters")
    keep = ("role", "content", "tool_calls", "tool_call_id", "reasoning_content")
    out = []
    for m in raw:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant", "tool"):
            raise ValueError("each message needs role user, assistant or tool")
        out.append({k: m[k] for k in keep if k in m})
    if not out or out[-1]["role"] != "user":
        raise ValueError("the last message must be the user's question")
    return out


def records(out) -> list[dict]:
    """The records a tool result mentions, each once, as the chat's side panel shows them."""
    found: dict[str, dict] = {}

    def add(d: dict) -> None:
        c = d.get("content") if isinstance(d.get("content"), dict) else d  # get_event nests the record
        kind = d.get("kind_name") or ("link" if "relation" in c else "contradiction" if "claim_ids" in c or "claims" in c and "reason" in c
                                      else "evidence" if {"title", "url", "source", "chars"} & c.keys() else "claim" if "text" in c else None)
        if kind and d["id"] not in found:
            found[d["id"]] = {"id": d["id"], "kind": kind, "author": d.get("author"),
                              **{k: str(c[k])[:400] for k in ("title", "url", "source", "text", "relation", "quote", "reason") if c.get(k)}}

    def walk(x) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("id"), str) and E.HEX64.match(x["id"]):
                add(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(out)
    return list(found.values())


def turn(pubkey: str, collection: str, messages: list[dict]):
    """The agent loop: call the model, run the tools it asks for, until it answers."""
    msgs = [{"role": "system", "content": SYSTEM.format(collection=collection)}, *messages]
    for _ in range(MAX_STEPS):
        reply = complete(msgs, pubkey, collection)
        msgs.append({k: reply[k] for k in ("role", "content", "tool_calls", "reasoning_content") if reply.get(k)}
                    | {"role": "assistant", "content": reply.get("content") or ""})
        calls = reply.get("tool_calls") or []
        if not calls:
            yield {"type": "answer", "content": reply.get("content") or ""}
            break
        for c in calls:
            name = c["function"]["name"]
            raw = c["function"].get("arguments") or "{}"
            try:
                args = raw if isinstance(raw, dict) else json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool_call", "id": c["id"], "name": name, "args": args}
            started = time.monotonic()
            out = run_tool(pubkey, collection, name, args)
            text = json.dumps(out, default=str, ensure_ascii=False)
            if len(text) > MAX_RESULT:
                text = text[:MAX_RESULT] + f"… [cut at {MAX_RESULT} chars; narrow the query]"
            yield {"type": "tool_result", "id": c["id"], "name": name, "result": text,
                   "ms": int((time.monotonic() - started) * 1000)}
            if found := records(out):
                yield {"type": "records", "records": found}
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": text})
    else:
        yield {"type": "answer", "content": f"(Stopped after {MAX_STEPS} model calls without an answer.)"}
    yield {"type": "messages", "messages": msgs[1:]}


PAGE_FILE = Path(__file__).with_name("chat.html")


def _member(conn, pk: str, slug: str) -> bool:
    return conn.execute("SELECT 1 FROM members WHERE collection = %s AND pubkey = %s", (slug, pk)).fetchone() is not None


def page(request: Request):
    """The chat page. Members see it; for anyone not approved the chat is greyed out."""
    pk, slug = cookie_pubkey(request), request.path_params["slug"]
    if pk is None:
        return RedirectResponse(f"/connect?next=/c/{slug}/chat", status_code=302)
    with L.connect() as conn:
        if not _member(conn, pk, slug):
            return PlainTextResponse(f"You are not a member of '{slug}'.", status_code=403)
    html = PAGE_FILE.read_text(encoding="utf-8").replace("{{MODEL}}", CHAT_MODEL).replace("{{CONTACT}}", L.CONTACT)
    return HTMLResponse(with_header(request, html), headers={"Cache-Control": "private, no-store"})


async def chat(request: Request):
    pk, slug = cookie_pubkey(request), request.path_params["slug"]
    if pk is None:
        return JSONResponse({"error": "log in first"}, status_code=401)
    if not await db(L.is_approved, pk):
        return JSONResponse({"error": f"The chat is for approved accounts. Email {L.CONTACT} for access to the chat."}, status_code=403)
    try:
        body = await request.json()
        messages = history(body.get("messages") if isinstance(body, dict) else None)
        await db(L.require_member, pk, slug)
    except ValueError as err:
        return JSONResponse({"error": str(err)}, status_code=403 if isinstance(err, L.Denied) else 400)

    def stream():  # sync: Starlette iterates it in its threadpool
        try:
            for ev in turn(pk, slug, messages):
                yield f"data: {json.dumps(ev, default=str, ensure_ascii=False)}\n\n"
        except Exception as err:
            yield f"data: {json.dumps({'type': 'error', 'error': str(err)[:500]})}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


routes = [Route("/c/{slug}/chat", page), Route("/api/c/{slug}/chat", chat, methods=["POST"])]
