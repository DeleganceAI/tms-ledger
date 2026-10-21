"""MCP surface for the TMS v2 ledger, plus the web pages and dashboard over HTTP.

Run over stdio (Claude Code):    TMS_NSEC=nsec1... tms-server
Run over HTTP (everyone else):   TMS_SECRET=... tms-server --http --host 0.0.0.0 --port 8080

The endpoint is open. publish(events) takes signed events. Every other tool takes `request`, a
kind-4707 event signed fresh for the call, whose content is {"tool": <tool name>, "args": {...}}.
Over stdio, an omitted request is signed with TMS_NSEC from the tool's plain arguments.
"""
from __future__ import annotations

import argparse
import functools
import inspect
import os
import subprocess
import sys
import time
from contextvars import ContextVar

import httpx
import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import events as E
from . import ledger as L

LOCAL_SECRET = os.environ.get("TMS_NSEC") or None  # stdio only; main() clears it for HTTP
REQUEST_WINDOW = 60  # seconds either side of server time

INSTRUCTIONS = """\
Append-only evidence ledger of signed Nostr-shaped events. It stores evidence (documents),
claims, links (evidence bearing on a claim, link, contradiction or evidence, with a verbatim
quote) and contradictions, each signed by its author. It never decides what is true; readers do.
Every collection is private to its members. Work in one collection at a time.
Writes: publish(events) with events you signed (kinds 4701 evidence, 4702 claim, 4703 link,
4704 contradiction; 0 profile; 4706 terms, once, before your first write). IDs are known
before signing, so one batch can hold evidence, claims and the links between them.
Every other tool takes `request`: a kind-4707 event signed now, content {"tool": <this tool>,
"args": {<the tool's arguments>}}. Requests are single-use and expire after 60 seconds.
Discipline: search -> inspect -> publish -> read. Search for existing claims before adding one
and reuse IDs deliberately. A link's quote must appear in its evidence text; the server rejects
quotes it cannot find. Nothing is edited or deleted: dispute a link or contradiction by linking to it.
"""

_who: ContextVar[dict | None] = ContextVar("who", default=None)  # the verified caller, for mcp_calls


async def _log_calls(ctx, call_next):
    """Record every MCP request, reads included, in mcp_calls. Telemetry never fails a call."""
    if ctx.request_id is None:  # a notification, not a call
        return await call_next(ctx)
    started = time.monotonic()
    who: dict = {}
    _who.set(who)  # a dict, so the tool's thread can fill it in
    ok, error = True, None
    try:
        result = await call_next(ctx)
        if isinstance(result, dict) and result.get("isError"):  # SDK 2.x hands middleware plain dicts
            ok = False
            error = " ".join(c.get("text", "") for c in result.get("content") or [])[:500]
        return result
    except Exception as err:
        ok, error = False, str(err)[:500]
        raise
    finally:
        params = ctx.params or {}
        tool = params.get("name") if ctx.method == "tools/call" else None
        try:
            with L.connect() as conn:
                L.log_call(conn, ctx.method, tool, who.get("pubkey"), who.get("collection"), ok, error,
                           int((time.monotonic() - started) * 1000))
        except Exception as err:
            print(f"mcp_calls logging failed: {err}", file=sys.stderr)


mcp = MCPServer("tms", instructions=INSTRUCTIONS, middleware=[_log_calls])


def authenticate(conn, request, tool: str) -> tuple[str, dict]:
    """Check a signed request (EVENTS.md section 4) and return (pubkey, args)."""
    if not isinstance(request, dict) or request.get("kind") != E.REQUEST:
        raise E.Invalid("request must be a kind-4707 event")
    data = E.verify(request)
    if data["tool"] != tool:
        raise E.Invalid(f"request was signed for tool '{data['tool']}', not '{tool}'")
    if abs(time.time() - request["created_at"]) > REQUEST_WINDOW:
        raise E.Invalid(f"request created_at is more than {REQUEST_WINDOW}s from server time; sign a fresh one")
    with conn.transaction():
        conn.execute("DELETE FROM auth_seen WHERE seen_at < now() - interval '2 minutes'")
        if conn.execute("INSERT INTO auth_seen (id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id",
                        (request["id"],)).fetchone() is None:
            raise E.Invalid("request was already used; sign a fresh one for every call")
    L.require_allowed(conn, request["pubkey"])
    return request["pubkey"], data["args"]


def _errors(fn):
    """Turn failures into messages the agent can act on (the SDK hides unexpected exceptions'
    text). Postgres RAISE messages are the guidance."""
    try:
        return fn()
    except psycopg.Error as err:
        raise ToolError(err.diag.message_primary or str(err)) from err
    except (ValueError, RuntimeError, OSError, httpx.HTTPError, subprocess.SubprocessError) as err:
        raise ToolError(str(err)) from err


def signed(impl):
    """Register an MCP tool whose arguments arrive in a signed request. The decorated function
    supplies the schema and docstring; impl(conn, pubkey, **args) does the work."""
    def register(fn):
        defaults = {k: p.default for k, p in inspect.signature(fn).parameters.items() if k != "request"}

        @functools.wraps(fn)
        def tool(request: dict | None = None, **given):
            def run():
                with L.connect() as conn:
                    req = request
                    if req is None:
                        if not LOCAL_SECRET:
                            raise ValueError(f"request is required: a kind-4707 event with content "
                                             f'{{"tool": "{fn.__name__}", "args": {{...}}}}, signed now')
                        req = E.request(LOCAL_SECRET, fn.__name__, {k: v for k, v in given.items() if v != defaults[k]})
                    elif any(given.get(k, v) != v for k, v in defaults.items()):
                        raise ValueError("with a request, pass the arguments inside its signed content, not beside it")
                    pubkey, args = authenticate(conn, req, fn.__name__)
                    unknown = set(args) - set(defaults)
                    if unknown:
                        raise ValueError(f"unknown arguments for {fn.__name__}: {', '.join(sorted(unknown))}")
                    args = {**defaults, **args}
                    who = _who.get()
                    if who is not None:
                        who.update(pubkey=pubkey, collection=args.get("collection") or None)
                    return impl(conn, pubkey, **args)
            return _errors(run)
        return mcp.tool()(tool)
    return register


# ------------------------------------------------------------------- writes

@mcp.tool()
def publish(events: list[dict]) -> dict:
    """Append a batch of signed events, all or nothing. Each event is a NIP-01 envelope
    {id, pubkey, created_at, kind, tags: [], content, sig} whose content is a JSON object string
    (profiles may carry tags; they are stored as signed and ignored):
      4701 evidence      {collection, text, url?, title?, source?}  text = the full document
      4702 claim         {collection, text}
      4703 link          {collection, from: evidence id, to: claim|link|contradiction|evidence id,
                          relation: SUPPORTS|REBUTS|QUALIFIES (QUALIFIES only to claims), quote, reason}
      4704 contradiction {collection, claims: [>=2 distinct claim ids], reason}
      4705 members       {collection, members: [pubkeys]}   owner only; the full list
      4706 terms         {version, sha256}   sign once before your first write (see TERMS.md)
      0    profile       {name, about?, picture?}
    References stay inside one collection and may point at events earlier in the same batch. A
    link's quote must appear in its evidence's text. The first event naming a new collection
    creates it, if its signer is approved. Events already stored are skipped, so retries are safe."""
    def run():
        with L.connect() as conn:
            res = L.publish(conn, events)
        who = _who.get()
        if who is not None:
            who.update(pubkey=events[0]["pubkey"], collection=",".join(res["collections"]) or None)
        return res
    return _errors(run)


# -------------------------------------------------------------------- reads

def _fetch_url(conn, pubkey, url):
    text, title = L.fetch_text(url)
    return {"url": url, "title": title, "chars": len(text), "text": text}


@signed(_fetch_url)
def fetch_url(request: dict | None = None, url: str = "") -> dict:
    """Fetch a URL and return its plain text and title, ready to sign as evidence (PDF via
    pdftotext, HTML via a readability extractor, JATS XML by stripping tags). Nothing is stored.
    The evidence text is what link quotes are checked against, so publish the whole text."""


@signed(lambda conn, pubkey: L.list_collections(conn, pubkey))
def list_collections(request: dict | None = None) -> list[dict]:
    """Collections you are a member of, with owner, members and counts."""


@signed(L.get_event)
def get_event(request: dict | None = None, id: str = "", offset: int = 0, max_chars: int = 20000) -> dict | None:
    """Exact read of one event by ID, content parsed. Evidence text comes back as a window
    (offset, max_chars) with `chars`, the total; page through long documents."""


@signed(L.search_claims)
def search_claims(request: dict | None = None, collection: str = "", text: str = "", method: str = "vector",
                  limit: int = 10) -> dict:
    """Retrieve claims in a collection by meaning (method='vector') or words (method='keyword').
    Each result inlines the links targeting it (relation, quote, grounding evidence) and the ids of
    contradictions it belongs to. Inlined quotes are cut to 300 chars here only. Ordering is a
    retrieval aid, not a judgement."""


@signed(L.list_claims)
def list_claims(request: dict | None = None, collection: str = "", sort: str = "unsupported",
                limit: int = 50) -> list[dict]:
    """Claims in a collection with their link counts (supports, qualifies, rebuts) and how many
    contradictions they belong to. sort: 'unsupported' (fewest links first), 'unchallenged'
    (supported, never rebutted or qualified), 'contested', 'links' (most), 'recent'. A worklist for
    follow-up research; counts are retrieval aids, not judgements."""


@signed(L.get_links)
def get_links(request: dict | None = None, collection: str = "", to_id: str = "", from_id: str = "",
              relation: str = "", limit: int = 100) -> list[dict]:
    """Links in a collection, filtered by target (to_id), grounding evidence (from_id) and/or relation."""


@signed(L.list_evidence)
def list_evidence(request: dict | None = None, collection: str = "", ungrounded_only: bool = False,
                  source: str = "", limit: int = 50) -> list[dict]:
    """Evidence documents in a collection, oldest first, without their text. ungrounded_only=true
    returns documents no link cites yet, the worklist for a claims pass. source filters by substring."""


@signed(L.search_contradictions)
def search_contradictions(request: dict | None = None, collection: str = "", claim: str = "", text: str = "",
                          limit: int = 20) -> list[dict]:
    """Contradictions in a collection, optionally those naming a claim id or matching words in the
    reason, each with its member claims and the links that target it. Whether one is open or
    resolved is the reader's conclusion."""


@signed(L.check_proof)
def check_proof(request: dict | None = None, collection: str = "", proof: dict | None = None) -> dict:
    """Validate a thinking proof before answering. proof = {"question": str, "steps": [{"id", "say",
    "from": [event ids or earlier step ids], "gap": bool?}]}. Rules: every 'from' resolves to an
    event in this collection or an earlier step; exactly one root; every step has a ledger event
    in its ancestry or is marked gap. Returns problems and an indented tree with leaves expanded."""


# ------------------------------------------------------------------ prompts

BRIEFING = """\
You are answering questions from the '{collection}' collection of the TMS ledger, and only from it.
Every tool except publish takes a fresh signed request (kind 4707); sign one per call.

For each question:
1. Retrieve. Call search_claims (vector, then keyword if thin) with the question and with
   rephrasings. Follow contradiction_ids with search_contradictions. Read quotes; open
   get_event on evidence when a quote needs context.
2. Build a thinking proof: {{"question": ..., "steps": [...]}}. Each step has an id, a one
   sentence "say", and "from": the event ids (claims, links, contradictions, evidence) or
   earlier step ids it rests on. Premises come before conclusions; the last step is the
   answer. Anything you want to say that no event supports goes in a step marked "gap": true.
3. Call check_proof. Fix every problem it lists, then call it again until ok.
4. Write the answer. Each paragraph corresponds to a step and cites its ids inline. Report
   rebuttals, qualifications and contradictions as what the events say, and state that
   open-or-resolved is your reading. Say plainly what the collection does not cover.
5. Reply with the answer in chat followed by the check_proof tree; save only {{question, steps}}
   to proofs/<YYYYMMDD-HHMM>-<slug>.json.

Never answer from general knowledge without marking it as a gap step. If the collection has
nothing relevant, say so; that is a complete and honest answer.
"""

CLAIMS_PASS = """\
You are extracting claims from evidence in the '{collection}' collection of the TMS ledger.
You sign everything with your own key (tms-sign, or any Nostr library). Before your first write,
publish a profile (kind 0, say in "about" that you are an agent) and the terms (kind 4706).
Every tool except publish takes a fresh signed request (kind 4707); sign one per call.

Worklist: list_evidence(ungrounded_only=true). For each evidence event:
1. Read it in full with get_event (page with offset/max_chars).
2. For each statement about the world worth keeping, call search_claims with it. Reuse an
   existing claim id when it says the same thing with the same scope; otherwise sign a new
   claim (kind 4702). Aim for the statements a careful reader would cite, usually five to
   fifteen per paper. Keep hedges, population, dose, timeframe and criteria inside the text.
3. Sign a link (kind 4703) from this evidence to the claim: SUPPORTS, REBUTS or QUALIFIES, with a
   verbatim quote copied exactly from the evidence text and a reason saying what it shows.
4. When a retrieved claim and a claim from this document cannot both hold, sign a contradiction
   (kind 4704) naming both ids, with the reason. If they differ only in scope, population or
   timeframe, sign a QUALIFIES link instead.
5. publish the document's new claims, links and contradictions as one batch. If a quote is
   rejected, the whole batch is: re-read the passage, copy it again, re-sign, retry. Never paraphrase.
Finding nothing new in a document is a valid outcome. Do not summarise; record.
"""


def _col(collection: str) -> str:
    collection = collection or os.environ.get("TMS_COLLECTION", "")
    if not collection:
        raise ToolError("collection is required (or set TMS_COLLECTION)")
    return collection


@mcp.prompt()
def briefing(collection: str = "") -> str:
    """Answer questions only from the ledger, with a checked thinking proof."""
    return BRIEFING.format(collection=_col(collection))


@mcp.prompt()
def claims_pass(collection: str = "") -> str:
    """Turn ungrounded evidence into claims, quoted links and contradictions."""
    return CLAIMS_PASS.format(collection=_col(collection))


# --------------------------------------------------------------------- main

def http_app():
    """MCP at /mcp plus the web pages, in one Starlette app."""
    from mcp.server.transport_security import TransportSecuritySettings

    from . import ui, web
    app = mcp.streamable_http_app(
        stateless_http=True, json_response=True,
        # The Host header is the deployment's own hostname; requests are signed, so no rebinding risk.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app.router.routes.extend(web.routes + ui.routes)
    return app


def main() -> None:
    global LOCAL_SECRET
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--http", action="store_true", help="serve MCP and the web pages over HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    a = p.parse_args()
    if not a.http:
        mcp.run("stdio")
        return
    if not os.environ.get("TMS_SECRET"):
        sys.exit("set TMS_SECRET to a long random secret (it signs login cookies) before serving over HTTP")
    import uvicorn
    LOCAL_SECRET = None   # over HTTP every call brings its own signature
    L.ALLOW_LOCAL = False  # remote callers fetch http(s) only; no local files, no internal hosts
    uvicorn.run(http_app(), host=a.host, port=a.port, log_level="info", proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
