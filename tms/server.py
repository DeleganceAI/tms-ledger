"""MCP surface for the TMS v2 ledger. Storage and retrieval only; contributors reason.

Run over stdio (Claude Code):    tms-server
Run over HTTP (remote agents):   TMS_TOKEN=... tms-server --http --port 8765
"""
from __future__ import annotations

import argparse
import hmac
import os
import subprocess
import sys
import time

import httpx
import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import ledger as L

INSTRUCTIONS = """\
Append-only evidence ledger. It stores sources, observations (documents), claims,
evidence (an observation's bearing on a target, with a verbatim quote) and
contradiction findings, each with an author and timestamp. It never decides what
is true; readers do. Work in one collection at a time.
Discipline: search -> inspect -> append -> read. Search for existing claims before
adding one and reuse IDs deliberately. Every evidence record must quote its
grounding observation verbatim; the server rejects quotes it cannot find.
Nothing is ever edited or deleted: correct by appending.
"""

async def _log_calls(ctx, call_next):
    """Record every MCP request, reads included, in mcp_calls. Telemetry never fails a call."""
    if ctx.request_id is None:  # a notification, not a call
        return await call_next(ctx)
    started = time.monotonic()
    ok, error = True, None
    try:
        result = await call_next(ctx)
        if getattr(result, "is_error", False):
            ok = False
            error = " ".join(getattr(c, "text", "") for c in (result.content or []))[:500]
        return result
    except Exception as err:
        ok, error = False, str(err)[:500]
        raise
    finally:
        params = ctx.params or {}
        tool = params.get("name") if ctx.method == "tools/call" else None
        args = (params.get("arguments") or {}) if tool else {}
        collection = args.get("collection") or (os.environ.get("TMS_COLLECTION") if tool else None) or None
        try:
            with L.connect() as conn:
                L.log_call(conn, ctx.method, tool, args.get("author_id"), collection, ok, error,
                           int((time.monotonic() - started) * 1000))
        except Exception as err:
            print(f"mcp_calls logging failed: {err}", file=sys.stderr)


mcp = MCPServer("tms", instructions=INSTRUCTIONS, middleware=[_log_calls])


def _run(fn, *args, **kwargs):
    """Open a connection, call a ledger function, and turn failures into messages the agent can act on
    (the SDK hides the text of unexpected exceptions). Postgres RAISE messages are the guidance."""
    try:
        with L.connect() as conn:
            return fn(conn, *args, **kwargs)
    except psycopg.Error as err:
        raise ToolError(err.diag.message_primary or str(err)) from err
    except (ValueError, RuntimeError, OSError, httpx.HTTPError, subprocess.SubprocessError) as err:
        raise ToolError(str(err)) from err


def _col(collection: str) -> str:
    collection = collection or os.environ.get("TMS_COLLECTION", "")
    if not collection:
        raise ToolError("collection is required (or set TMS_COLLECTION)")
    return collection


# ----------------------------------------------------------------- appends

@mcp.tool()
def add_author(id: str, name: str, kind: str) -> dict:
    """Register an operational identity (not a login). kind is 'human' or 'agent'.
    Use a short slug id such as 'dustin' or 'grok-scout-1'. Register once, reuse the id. Calling it
    again with the same id, name and kind returns the existing record; a different name or kind for
    an existing id is an error."""
    return _run(L.add_author, id, name, kind)


@mcp.tool()
def add_collection(id: str, name: str, author_id: str) -> dict:
    """Create a collection (a topic or project that scopes observations, claims and contradictions).
    id is a lowercase slug such as 'mcas'."""
    return _run(L.add_collection, id, name, author_id)


@mcp.tool()
def list_collections() -> list[dict]:
    """List collections with their observation and claim counts."""
    return _run(L.list_collections)


@mcp.tool()
def add_source(name: str, author_id: str, uri: str = "") -> dict:
    """Register where material comes from: a journal, a website, an X account, a person.
    Sources are global across collections. Search first with search_sources and reuse the id."""
    return _run(L.add_source, name, author_id, uri or None)


@mcp.tool()
def search_sources(text: str, limit: int = 20) -> list[dict]:
    """Find candidate sources by name or URI substring. A match is a candidate, not an identity."""
    return _run(L.search_sources, text, limit)


@mcp.tool()
def add_observation(source_id: str, author_id: str, uri: str, content: str = "", title: str = "",
                    collection: str = "") -> dict:
    """Preserve a document, paper, blog post or social post in a collection.
    Pass the full text as content, or leave content empty and the server fetches uri
    (PDF via pdftotext, HTML via a readability extractor). The stored text is what
    evidence quotes are checked against, so pass the whole thing, not a summary.
    title is optional: left empty, the server derives one (the document's <title> or JATS
    <article-title>, else the first non-empty line). Returns the record without content; read
    it back with get_record."""
    return _run(L.add_observation, _col(collection), source_id, author_id, uri, content or None, title or None)


@mcp.tool()
def add_claim(text: str, author_id: str, collection: str = "") -> dict:
    """Record one opaque statement about the world. Keep hedges, population, dose, timeframe and
    diagnostic criteria inside the text ("In adults meeting consensus-2 MCAS criteria, ...").
    Call search_claims first and reuse an existing id if the statement is already recorded.
    The claim is embedded for vector search on write."""
    return _run(L.add_claim, _col(collection), text, author_id)


@mcp.tool()
def add_evidence(from_observation_id: str, target_kind: str, target_id: str, relation: str,
                 quote: str, reason: str, author_id: str) -> dict:
    """Record how an observation bears on a target. relation: SUPPORTS, REBUTS, or QUALIFIES
    (QUALIFIES only targets claims). target_kind: claim, contradiction, evidence, source, observation.
    quote must be a verbatim passage (<=1500 chars) from the grounding observation; the write is
    rejected if it cannot be found there. reason says specifically what the passage shows."""
    return _run(L.add_evidence, from_observation_id, target_kind, target_id, relation, quote, reason, author_id)


@mcp.tool()
def add_contradiction(claim_ids: list[str], reason: str, author_id: str, collection: str = "") -> dict:
    """Record an authored finding that two or more distinct claims cannot all hold, with the reason.
    Membership is frozen on write; a different set needs a new finding. Differences of scope,
    population or timeframe are not contradictions: put that in a QUALIFIES evidence instead.
    Two criteria sets or definitions for the same diagnosis that would classify the same patient
    differently ARE a contradiction, not a scope difference."""
    return _run(L.add_contradiction, _col(collection), claim_ids, reason, author_id)


# ------------------------------------------------------------------- reads

@mcp.tool()
def get_record(kind: str, id: str, offset: int = 0, max_chars: int = 20000) -> dict | None:
    """Exact read. kind: author, collection, source, observation, claim, contradiction, evidence.
    Observations return title, a content window (offset, max_chars) and `chars` (the total); page
    through long documents. A null content with content_unavailable=true means the text was not stored."""
    return _run(L.get_record, kind, id, offset, max_chars)


@mcp.tool()
def search_claims(text: str, method: str = "vector", limit: int = 10, collection: str = "") -> dict:
    """Retrieve claims in a collection by meaning (method='vector') or words (method='keyword').
    Each result inlines its evidence (relation, quote, grounding observation) and the ids of any
    contradiction findings it belongs to. Inlined quotes are cut to 300 chars with an ellipsis here
    only; get_evidence and get_record return them whole. Ordering is a retrieval aid, not a judgement."""
    return _run(L.search_claims, _col(collection), text, method, limit)


@mcp.tool()
def get_evidence(target_kind: str = "", target_id: str = "", from_observation_id: str = "",
                 relation: str = "", limit: int = 100) -> list[dict]:
    """Evidence records filtered by target (kind + id), grounding observation and/or relation."""
    return _run(L.get_evidence, target_kind or None, target_id or None, from_observation_id or None,
                              relation or None, limit)


@mcp.tool()
def list_observations(ungrounded_only: bool = False, limit: int = 50, collection: str = "") -> list[dict]:
    """List observations in a collection, oldest first. ungrounded_only=true returns documents that no
    evidence cites yet, which is the natural worklist for a claims pass."""
    return _run(L.list_observations, _col(collection), ungrounded_only, limit)


@mcp.tool()
def search_contradictions(claim_id: str = "", text: str = "", limit: int = 20, collection: str = "") -> list[dict]:
    """Contradiction findings in a collection, optionally those naming a claim or matching words in the
    reason. Each includes member claims and any evidence targeting the finding itself. Whether a
    finding is open or resolved is the reader's conclusion."""
    return _run(L.search_contradictions, _col(collection), claim_id or None, text or None, limit)


@mcp.tool()
def check_proof(proof: dict, collection: str = "") -> dict:
    """Validate a thinking proof before answering. proof = {"question": str, "steps": [{"id", "say",
    "from": [ledger ids or earlier step ids], "gap": bool?}]}. Rules: every 'from' resolves to a
    record in this collection or an earlier step; exactly one root; every step has a ledger record
    in its ancestry or is marked gap. Returns problems and an indented tree with leaves expanded."""
    return _run(L.check_proof, _col(collection), proof)


# ----------------------------------------------------------------- prompts

BRIEFING = """\
You are answering questions from the '{collection}' collection of the TMS ledger, and only from it.

For each question:
1. Retrieve. Call search_claims (vector, then keyword if thin) with the question and with
   rephrasings. Follow contradiction_ids with search_contradictions. Read quotes; open
   get_record on observations when a quote needs context.
2. Build a thinking proof: {{"question": ..., "steps": [...]}}. Each step has an id, a one
   sentence "say", and "from": the ledger ids (claims, evidence, contradictions, observations)
   or earlier step ids it rests on. Premises come before conclusions; the last step is the
   answer. Anything you want to say that no record supports goes in a step marked "gap": true.
3. Call check_proof. Fix every problem it lists, then call it again until ok.
4. Write the answer. Each paragraph corresponds to a step and cites its ids inline. Report
   rebuttals, qualifications and contradiction findings as what the records say, and state
   that open-or-resolved is your reading. Say plainly what the collection does not cover.
5. Reply with the answer in chat followed by the check_proof tree; save only {question, steps}
   to proofs/<YYYYMMDD-HHMM>-<slug>.json.

Never answer from general knowledge without marking it as a gap step. If the collection has
nothing relevant, say so; that is a complete and honest answer.
"""

CLAIMS_PASS = """\
You are extracting claims from documents in the '{collection}' collection of the TMS ledger.
Register yourself once with add_author (kind 'agent') and reuse that author_id.

Worklist: list_observations(ungrounded_only=true). For each observation:
1. Read it in full with get_record (page with offset/max_chars).
2. For each statement about the world worth keeping, call search_claims with it. Reuse an
   existing claim id when it says the same thing with the same scope; otherwise add_claim.
   Aim for the statements a careful reader would cite, usually five to fifteen per paper.
   Keep hedges, population, dose, timeframe and diagnostic criteria inside the claim text.
3. add_evidence from this observation to the claim: SUPPORTS, REBUTS or QUALIFIES, with a
   verbatim quote copied exactly from the document and a reason saying what the passage shows.
   If the server rejects the quote, re-read the passage and copy it again; never paraphrase.
4. When a retrieved claim and a claim from this document cannot both hold, call
   add_contradiction with both ids and the reason. If they differ only in scope, population
   or timeframe, record a QUALIFIES evidence instead.
Finding nothing new in a document is a valid outcome. Do not summarise; record.
"""


@mcp.prompt()
def briefing(collection: str = "") -> str:
    """Answer questions only from the ledger, with a checked thinking proof."""
    return BRIEFING.format(collection=_col(collection))


@mcp.prompt()
def claims_pass(collection: str = "") -> str:
    """Turn ungrounded observations into claims, quoted evidence and contradiction findings."""
    return CLAIMS_PASS.format(collection=_col(collection))


# ------------------------------------------------------------------- main

def _bearer(app, token: str):
    """ASGI wrapper: everything except lifespan events needs `Authorization: Bearer <token>`."""
    expected = token.encode()

    async def wrapped(scope, receive, send):
        if scope["type"] != "lifespan":
            header = dict(scope.get("headers") or []).get(b"authorization", b"")
            scheme, _, presented = header.partition(b" ")
            if scheme.lower() != b"bearer" or not hmac.compare_digest(presented.strip(), expected):
                if scope["type"] == "http":
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
                    await send({"type": "http.response.body", "body": b"unauthorized"})
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await app(scope, receive, send)

    return wrapped


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    if not a.http:
        mcp.run("stdio")
        return
    token = os.environ.get("TMS_TOKEN")
    if not token:
        sys.exit("set TMS_TOKEN to a long random secret before serving over HTTP")
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings
    L.ALLOW_LOCAL = False  # remote callers fetch http(s) only; no local files, no internal hosts
    # Host header will be the tunnel hostname; the bearer token is the gate.
    app = mcp.streamable_http_app(
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    uvicorn.run(_bearer(app, token), host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
