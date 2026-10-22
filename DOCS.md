# Using the TMS ledger

TMS is a private, append-only evidence ledger for people and AI agents. You record **evidence** (the full text of a paper, page or post), **claims** (statements about the world), **links** (a verbatim quote from evidence that supports, rebuts or qualifies something) and **contradictions** (claims that cannot all hold). The server never decides what is true. It checks that records are well formed, that quotes really appear in the evidence they cite, and who signed what.

Every record is a Nostr-style event signed with its author's key. Nobody, including the operator, can alter a record without breaking its signature, and nothing is ever edited or deleted. To correct something, add a link that disputes it.

Every collection is private. Only its members can read, write or export it.

> Base URL: `{{BASE}}`. Current terms: version `{{TERMS_VERSION}}`, sha256 `{{TERMS_SHA256}}`. (Read in the repo, these are placeholders; the server's `/docs` and `/docs.md` fill them in.)

## Philosophy

TMS stands for truth maintenance system, but it doesn't maintain truth. It keeps a careful, signed record of what people and agents asserted, what documents they grounded it in, and where they think the assertions collide. What to believe is left to whoever reads that record.

### What this is

- **A ledger of assertions.** Evidence, claims, links and contradictions, each signed by the key that made it and timestamped by the server when it arrived.
- **A record of reasons.** Every link quotes its evidence verbatim and says why the quote bears on its target. Every contradiction names its claims and says why they can't all hold. A reader can always ask "says who, and on what grounds?" and get an answer from the record.
- **A shared workspace for people and agents.** Humans and bots use the same records, the same rules and the same signatures. A bot's contribution is attributed to the bot, and a person's to the person.
- **A history that only grows.** Corrections are new records that dispute old ones. Nothing is edited, retired or quietly replaced, so you can always see what was believed to be grounded at any point and what changed it.

### What this is not

- **Not a fact-checker or an oracle.** The server never decides whether a claim is true, whether evidence applies, or which side of a contradiction is right. It checks structure, signatures, membership, and that quotes really appear in the evidence they cite. That's all.
- **Not a confidence or scoring system.** There are no probabilities, weights, ratings or "confidence: high" labels, and nothing is aggregated into a score. Numbers inside a claim are just part of the claim's text. Search distances help you find things; they say nothing about truth.
- **Not a status tracker.** There is no "verified", "debunked", "contested", "open" or "resolved" field anywhere. Those are conclusions, and conclusions belong to readers. Two readers looking at the same records may reasonably reach different ones.
- **Not a knowledge graph that merges or infers.** Identical claim text is two claims. Two sources are not assumed independent. Nothing propagates: rebutting a claim doesn't touch the links that support it, and disputing a contradiction doesn't close it.
- **Not an editable wiki.** You can't fix a typo in a claim; you add a better claim and link the two. That is deliberate: the earlier wording, and who relied on it, stays visible.
- **Not an identity or credibility check.** A signature proves which key signed a record, not who holds the key or whether they are reliable. Whether a key is a human or an agent is whatever its profile says. How reliable a source is, is itself just a claim someone can make and ground.
- **Not a workflow engine.** There are no assignments, queues or task states. Agents and people decide what to work on outside the ledger; the ledger only keeps what they produce.
- **Not a public feed.** Every collection is private to its members. Nothing is published to Nostr relays, and there are no followers and no timeline.
- **Not a record of anyone's private reasoning.** The trail of links and contradictions shows what was asserted and on what grounds, not why someone went looking or what they thought along the way.

### The discipline

1. **No confidence scales.** Ground a claim or dispute it; don't rate it.
2. **Keep interpretation with readers.** Believed, contested, open and resolved are a reader's words, never the ledger's.
3. **Show the reasons.** A link needs a verbatim quote and a specific reason. A contradiction needs at least two distinct claims and an explanation of why they can't all hold.
4. **Preserve history.** Append; never edit or delete. Correct a record by disputing it with a new one.
5. **Keep provenance explicit.** Every record says which key signed it and when the server received it.

### Why it is built this way

- **Verbatim quotes.** A paraphrase can quietly drift from what a source says. A quote can be checked mechanically, and the server rejects any quote it can't find in the evidence text, forgiving only case, whitespace, curly quotes, dashes and ligatures. So the record can't claim a document says something it doesn't.
- **Contradictions are authored, not computed.** Claim text is opaque to the server, and "these can't all be true" is a judgement about meaning, scope and time. Someone has to make it and give a reason. A claim with both supporting and rebutting links is merely contested, and readers can see that with a query.
- **Contradictions don't name a loser.** A contradiction says the claims can't all hold, not which one is wrong, and any two of its claims may be compatible on their own. Later evidence either gives grounds to reject or qualify a member claim (the disagreement was addressed), or shows the contradiction was mistaken, for example because the claims are about different timeframes (the contradiction was corrected). Both are readings of the record, not states the server sets.
- **Signed events.** Every record is a Nostr-style event, so authorship doesn't depend on trusting the server. Anyone holding an export can verify every signature, and nobody, the operator included, can alter a record without breaking it.
- **Append-only.** If records could be edited, a link could end up pointing at words its author never saw. Because references are event IDs, which are hashes of exact content, a link commits to the exact text it was about.
- **Private collections.** People upload whole papers and articles. Keeping each collection to its members respects the uploads, and lets a group work on a question before it's ready to share.

### How the work flows

The ledger doesn't run a process, but this is the loop it is designed to support:

```text
gather evidence → extract claims and link them, with quotes → notice claims that can't all hold
  → record a contradiction → research the disagreement → add new evidence and links
  → a reader weighs it all and answers, citing the records
```

Anyone, human or agent, can play any part of it:

- **Intake:** finds and adds relevant evidence. Spotting a duplicate and adding nothing is a valid result.
- **Claims and links:** turns evidence into specific claims and links them with quotes and reasons.
- **Contradiction finding:** tells genuine incompatibility apart from differences in scope, time or meaning.
- **Review:** documents mistakes (misreadings, unsupported links) by disputing them with grounded links.
- **Follow-up research:** goes after a contradiction or an open question and brings back new evidence. It doesn't have to settle anything.
- **Briefing:** answers a question from the collection alone, cites the records, says what the collection doesn't cover, and leaves a checked thinking proof (`check_proof`).

Finding nothing is an honest outcome for every role. No one should manufacture a discovery to look productive.

## For people

### 1. Connect

You need a Nostr browser extension that supports NIP-07, such as [Alby](https://getalby.com), [nos2x](https://github.com/fiatjaf/nos2x) or Keys.band. Open [{{BASE}}/connect]({{BASE}}/connect), or click **Connect** on the home page.

1. The extension shares your public key.
2. The page looks up your existing Nostr profile on Damus and Primal. If it finds one, click **Use this profile here** to store it. If not, sign a short profile with a name, and say in "about" whether you are a human or an agent.
3. You sign a one-time login request. It sets a cookie that lasts 12 hours, so the extension won't prompt on every page.

You can use the service if an admin has approved your key, or if a collection's owner has added you as a member. Anyone else is turned away at login.

To ask for access, click **Request access** on the home page and paste your npub, with an optional note. You don't sign anything. An admin reviews the request; once it's approved, you can connect straight away.

### 2. Sign the terms

Before your first write, the home page shows the terms: one clause saying you have the right to upload what you upload. Click **I agree** to sign them. This signs a terms event with the exact hash of the text you agreed to.

### 3. Create a collection and add members

Approved keys can create collections. On the home page, type a slug (lowercase letters, digits, `-` and `_`) and click **Create collection**. You become its owner for good; ownership never transfers.

As owner, open **members** next to the collection (`/c/<slug>/members`) and paste one npub per line. Each save signs the complete member list, so anyone you leave out is removed. Members don't need operator approval, so this is how you let in collaborators and bots.

### 4. Submit evidence, claims and links

Open [{{BASE}}/submit]({{BASE}}/submit).

1. Pick the collection.
2. Paste a URL and click **Fetch** to pull in its text, or paste the text yourself. The text is what you are vouching for, so use the whole document, not a summary.
3. Add rows. Each row is a claim (new text, or the event id of an existing claim), a relation (`SUPPORTS`, `REBUTS` or `QUALIFIES`), a quote copied verbatim from the text, and a reason.
4. Click **Sign and publish**. Everything goes in as one batch: if any quote isn't found in the text, nothing is stored.

Quote matching ignores differences in case, whitespace, curly versus straight quotes, dash styles, soft hyphens and fi/fl ligatures. Nothing else is forgiven.

### 5. Export a collection

Any member can download every event in a collection as JSON Lines from the home page (**export**) or at `/c/<slug>/export.jsonl`. Each line is a complete signed event that verifies on its own with any Nostr library.

The [dashboard]({{BASE}}/dashboard) shows activity, records, contributors and sources for your collections. Admins also get **Ask the ledger**, a chat popup at the bottom right of every page: a read-only agent bound to one collection, which answers from the ledger, shows every tool call it makes, and exports the conversation as Markdown or JSON. Chats are not stored.

The [office]({{BASE}}/office), also the home page when you're logged out, replays the last hour of real work, by its shape only. Each board is a slice of one private collection: index cards are claims, papers are evidence, green string supports, red rebuts, amber qualifies, and a red zigzag marks a contradiction; a yellow card with no string is a hypothesis. It shows no text, names, collections or record ids, and its data, [`/office.json`]({{BASE}}/office.json), is anonymous and refreshed hourly.

## For bots and agents

### Keys

Each bot generates and holds its own key. The server never holds it. Any Nostr library works, as does this repo's CLI:

```bash
uv run tms-sign keygen
```

Give the bot's npub to a collection owner, who adds it on the members page. Before its first write, the bot signs the terms (kind 4706) and, ideally, a profile (kind 0) that says it is an agent.

### The MCP endpoint

```
{{BASE}}/mcp
```

The endpoint uses MCP's streamable HTTP transport and runs stateless, so no session or initialize step is needed. Anyone can list the tools. There is no bearer token: `publish` takes signed events, and every other tool takes a signed `request`.

Listing tools and prompts needs no signature. Each is a JSON-RPC POST to `/mcp` with the headers shown under [Signed requests](#signed-requests):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

This returns every tool's `name`, `description`, `inputSchema` and `outputSchema`, which MCP clients read automatically.

```json
{"jsonrpc": "2.0", "id": 2, "method": "prompts/list"}
```

```json
{"jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {"name": "claims_pass", "arguments": {"collection": "mcas"}}}
```

There are two prompts, each taking a `collection`. `claims_pass` turns evidence that no link cites yet into claims, links and contradictions. `briefing` answers questions from one collection with a checked thinking proof. `prompts/get` returns the instructions as `result.messages[0].content.text`.

### Events

Every event is a NIP-01 envelope:

```json
{"id": "<sha256 hex>", "pubkey": "<x-only hex>", "created_at": 1792454400, "kind": 4702,
 "tags": [], "content": "<JSON object as a string>", "sig": "<BIP-340 hex>"}
```

- **`id`** is the sha256 of the UTF-8 JSON `[0, pubkey, created_at, kind, tags, content]`, serialized with no whitespace, exactly as `JSON.stringify` does it.
- **`sig`** is a BIP-340 Schnorr signature over the id.
- **`tags`** is `[]` on every kind except profiles (kind 0), which may carry the tags other clients give them.
- **`content`** is a JSON object, serialized to a string. Unknown fields are rejected, except on profiles. Required strings must not be blank.

| Kind | Name | `content` fields (`?` = optional) |
|---|---|---|
| 0 | profile | `name`, `about`?, `picture`? |
| 4701 | evidence | `collection`, `text` (the full document), `url`?, `title`?, `source`? (publisher or site), `archive_url`? (where the text was actually read, such as a Wayback snapshot), `retrieved_via`? (how, such as `"Wayback"` or `"NewsAPI.ai"`) |
| 4702 | claim | `collection`, `text` |
| 4703 | link | `collection`, `from` (an evidence id), `to` (a claim, link, contradiction or evidence id), `relation` (`SUPPORTS`, `REBUTS` or `QUALIFIES`; `QUALIFIES` only targets claims), `quote` (verbatim from `from`'s text), `reason` |
| 4704 | contradiction | `collection`, `claims` (two or more distinct claim ids), `reason` |
| 4705 | members | `collection`, `members` (the full list of pubkeys; owner only) |
| 4706 | terms | `version` = `"{{TERMS_VERSION}}"`, `sha256` = `"{{TERMS_SHA256}}"` |
| 4707 | request | `tool`, `args`, `nonce`? (signed tool calls; never stored) |

References must stay inside one collection. They can point at events earlier in the same batch, because ids are known before signing. The first event that names a new collection creates it, if its signer is approved.

### Signed requests

Every tool except `publish` takes one argument, `request`: a kind 4707 event whose content is `{"tool": "<this tool's name>", "args": {<the tool's arguments>}, "nonce": "<random>"}`. The server takes the arguments from the signed content only. It accepts a request only if:

- the signature verifies;
- `tool` names the tool being called;
- `created_at` is within 60 seconds of the server's clock;
- the request hasn't been used before.

So sign a fresh request for every call, with a random `nonce`. `created_at` is in whole seconds, so without one, two identical calls in the same second get the same id and the second is rejected as a replay.

| Tool | `args` |
|---|---|
| `list_collections` | none |
| `get_event` | `id`, `offset`?, `max_chars`? (evidence text comes back in windows) |
| `search_claims` | `collection`, `text`, `method`? (`vector` or `keyword`), `limit`? |
| `list_claims` | `collection`, `sort`? (`unsupported`, `unchallenged`, `contested`, `links`, `recent`, `oldest`), `limit`?, `offset`? |
| `get_links` | `collection`, `to_id`?, `from_id`?, `relation`?, `limit`?, `offset`? |
| `list_evidence` | `collection`, `ungrounded_only`?, `source`?, `limit`?, `offset`? |
| `search_contradictions` | `collection`, `claim`?, `text`?, `limit`? |
| `check_proof` | `collection`, `proof` |
| `fetch_url` | `url` (returns text and title ready to sign as evidence; stores nothing; refuses captcha and near-empty pages) |

To read a whole collection, page with `offset`: call again with `offset` raised by `limit` until fewer than `limit` items come back. For claims, use `sort: "oldest"`, which doesn't reorder as new claims arrive.

Each call is a JSON-RPC POST to `/mcp` with the headers `Content-Type: application/json` and `Accept: application/json, text/event-stream`. The result is in `result.structuredContent`. Tools that can return a list or null wrap the value as `{"result": ...}`. A failed call has `result.isError: true`, and `result.content[0].text` says why.

#### Python

Uses `coincurve` and `httpx` (`pip install coincurve httpx`):

```python
import hashlib, json, os, secrets, time
import httpx
from coincurve import PrivateKey, PublicKeyXOnly

BASE = "{{BASE}}"
SK = PrivateKey(bytes.fromhex(os.environ["BOT_SECRET_HEX"]))
PUBKEY = PublicKeyXOnly.from_secret(SK.secret).format().hex()

def sign(kind, content, tags=()):
    content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)
    created_at = int(time.time())
    data = json.dumps([0, PUBKEY, created_at, kind, list(tags), content], separators=(",", ":"), ensure_ascii=False)
    eid = hashlib.sha256(data.encode()).hexdigest()
    sig = SK.sign_schnorr(bytes.fromhex(eid), os.urandom(32)).hex()
    return {"id": eid, "pubkey": PUBKEY, "created_at": created_at, "kind": kind,
            "tags": list(tags), "content": content, "sig": sig}

def call(tool, arguments):
    r = httpx.post(f"{BASE}/mcp", timeout=60,
                   headers={"Accept": "application/json, text/event-stream"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments}})
    result = r.json()["result"]
    if result.get("isError"):
        raise RuntimeError(result["content"][0]["text"])
    return result["structuredContent"]

def tool(name, **args):  # every tool except publish
    return call(name, {"request": sign(4707, {"tool": name, "args": args, "nonce": secrets.token_hex(8)})})

print(tool("list_collections"))
print(tool("search_claims", collection="mcas", text="DAO activity", method="keyword"))
```

#### JavaScript

Uses [`nostr-tools`](https://github.com/nbd-wtf/nostr-tools) (`npm install nostr-tools`) on Node 18 or later:

```js
import { finalizeEvent } from 'nostr-tools/pure'
import { hexToBytes } from '@noble/hashes/utils'

const BASE = '{{BASE}}'
const sk = hexToBytes(process.env.BOT_SECRET_HEX)
const sign = (kind, content) =>
  finalizeEvent({ kind, created_at: Math.floor(Date.now() / 1000), tags: [], content: JSON.stringify(content) }, sk)

async function call(tool, args) {
  const r = await fetch(`${BASE}/mcp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: tool, arguments: args } }),
  })
  const { result } = await r.json()
  if (result.isError) throw new Error(result.content[0].text)
  return result.structuredContent
}
const tool = (name, args = {}) => call(name, { request: sign(4707, { tool: name, args, nonce: Math.random().toString(36).slice(2) }) })

console.log(await tool('list_collections'))
```

### Publishing

`publish` takes `{"events": [...]}`: a batch of signed events, all or nothing. Events already stored are skipped, so retrying a batch is safe. It needs no request, because every event is its own proof.

First, once per key, sign the terms. Python, with the helpers above:

```python
call("publish", {"events": [
    sign(4706, {"version": "{{TERMS_VERSION}}", "sha256": "{{TERMS_SHA256}}"}),
    sign(0, {"name": "my-bot", "about": "agent: reads papers on histamine intolerance"}),
]})
```

Then, an example batch: one evidence document, a new claim, and a link between them:

```python
doc = sign(4701, {"collection": "mcas", "title": "HIT review", "url": "https://example.org/hit",
                  "source": "Example journal",
                  "text": "Histamine intolerance is thought to result from reduced diamine oxidase (DAO) activity."})
claim = sign(4702, {"collection": "mcas", "text": "Histamine intolerance results from reduced DAO activity."})
link = sign(4703, {"collection": "mcas", "from": doc["id"], "to": claim["id"], "relation": "SUPPORTS",
                   "quote": "thought to result from reduced diamine oxidase (DAO) activity",
                   "reason": "The review names reduced DAO activity as the proposed mechanism."})
print(call("publish", {"events": [doc, claim, link]}))
# {"accepted": [<3 ids>], "skipped": [], "embedded": 1, "collections": ["mcas"]}
```

To dispute a link or a contradiction, publish a link whose `to` is that event's id.

### What each tool returns

Records come back with `id`, `pubkey`, `author` (the signer's profile name, or null) and `received_at` (when the server stored them, ISO 8601). Lists are oldest first unless a sort says otherwise. Results that are a list, or that can be null, arrive as `{"result": ...}`.

| Tool | Result |
|---|---|
| `publish` | `{"accepted": [ids], "skipped": [ids already stored], "collections": [slugs], "embedded": n}`. `embedded` becomes `embedding_error` when embedding fails; the events are stored anyway, and their vectors catch up on a later publish. |
| `fetch_url` | `{"url", "title", "chars", "text"}` |
| `list_collections` | `{"result": [{"slug", "owner", "created_at", "members": [pubkeys], "evidence", "claims", "links", "contradictions"}]}` |
| `get_event` | `{"result": {"id", "pubkey", "author", "kind", "kind_name", "collection", "created_at", "received_at", "content": {...}}}`, or `{"result": null}` if the event doesn't exist or isn't in your collections. For evidence, `content.text` is the window from `offset` and the result adds `chars` (the full length) and `offset`. |
| `search_claims` | `{"method", "note", "items": [{"id", "pubkey", "author", "text", "received_at", "distance" (vector) or "rank" (keyword), "links": [link], "contradiction_ids": [ids]}]}`. Quotes inside `links` are cut to 300 characters here only. |
| `list_claims` | `{"result": [{"id", "pubkey", "author", "text", "received_at", "supports", "qualifies", "rebuts", "findings"}]}`, where `findings` counts the contradictions the claim belongs to. |
| `get_links` | `{"result": [link]}` |
| `list_evidence` | `{"result": [{"id", "pubkey", "author", "title", "url", "source", "archive_url", "retrieved_via", "received_at", "chars", "link_count"}]}`, without the text; read it with `get_event`. |
| `search_contradictions` | `{"result": [{"id", "pubkey", "author", "reason", "claim_ids", "received_at", "claims": [{"id", "pubkey", "author", "text"}], "links": [link]}]}` |
| `check_proof` | `{"ok", "problems": [strings], "root", "tree"}` (see below) |

A link is `{"id", "pubkey", "author", "from", "to", "relation", "quote", "reason", "received_at"}`. Distances, ranks and counts are retrieval aids, not confidence.

### Thinking proofs (`check_proof`)

A proof is an agent's argument resting on ledger events. It lives outside the ledger; `check_proof` validates it before the agent answers.

```json
{"question": "Is DAO deficiency the cause of histamine intolerance?",
 "steps": [
  {"id": "s1", "say": "One review proposes reduced DAO activity as the mechanism.", "from": ["<claim id>", "<link id>"]},
  {"id": "s2", "say": "A contradiction says this sits badly with serum data.", "from": ["<contradiction id>"]},
  {"id": "s3", "say": "Nothing in the collection covers children.", "from": [], "gap": true},
  {"id": "root", "say": "Proposed mechanism, not an established cause.", "from": ["s1", "s2", "s3"]}
 ]}
```

Each step has a unique `id`, a one-sentence `say`, and `from`: event ids from this collection, or ids of earlier steps. `gap: true` marks a step that no event supports. The rules:

1. Every `from` entry is an event in this collection or an earlier step. Premises come before the steps that use them.
2. Exactly one step, the answer, is not cited by any other step.
3. Every step has a ledger event somewhere in its ancestry, or is marked `gap`.

The result lists every broken rule in `problems`, and `ok` is true only when there are none. `root` is the answer step's id. `tree` is the proof printed as an indented tree with each event expanded (claim text, link quote, evidence title), so a person can read it next to the answer. An event from another collection is reported as not in this collection; the result never names other collections.

### Limits

| What | Limit |
|---|---|
| Events per `publish` batch | 1000 |
| `content` per event | 2,000,000 characters; split longer documents |
| Request age | within 60 seconds of the server's clock; each request works once |
| `limit` argument | at least 1, at most 200 (`list_evidence` 500, `get_links` 1000); page past it with `offset` |
| `get_event` window | `max_chars` defaults to 20,000; page with `offset` |
| `fetch_url` download | 50 MB before extraction, http(s) only, no internal hosts |
| Browser login | 12 hours |

### Common errors

| Message contains | Meaning and fix |
|---|---|
| `is not approved and is not a member of any collection` | Click **Request access** on the home page to ask an admin, or ask a collection owner to add the key. |
| `sign the current terms first` | Publish a kind 4706 terms event (version `{{TERMS_VERSION}}`, sha256 above) before anything else. |
| `not a member of collection` | The key isn't in that collection's member list. |
| `only approved pubkeys create collections` | The collection doesn't exist yet, and this key can't create it. Check the slug for typos. |
| `only the owner of ... changes its members` | Members events must be signed by the collection's owner. |
| `quote not found verbatim in evidence` | Copy the quote exactly from the evidence text. The whole batch was rolled back. |
| `from must be an evidence event`, `is not a claim in collection`, `does not exist` | A reference points at the wrong kind, at another collection, or at nothing. |
| `QUALIFIES may only target a claim` | Use `SUPPORTS` or `REBUTS` for links and contradictions. |
| `request was already used` | Every request is single-use. Sign a new one, with a random `nonce`: an identical call signed in the same second has the same id. |
| `returned a bot challenge or near-empty page` | `fetch_url` got a captcha or stub instead of the document. Get the text another way (an API, an archive copy), publish it as evidence, and record where in `archive_url` and `retrieved_via`. |
| `more than 60s from server time` | The request is stale, or the bot's clock is off. Sign a fresh one and check the clock. |
| `request was signed for tool 'x', not 'y'` | The `tool` inside the request must match the tool you call. |
| `pass the arguments inside its signed content` | With a `request`, put every argument in its `args`, not beside it. |
| `id does not match` | The id isn't the sha256 of the serialization. Usually `content` was re-serialized after signing; send the exact signed string. |
| `signature does not verify` | Signed with a different key, or the event was changed after signing. |
| `unknown fields`, `is missing`, `field '...' is invalid` | The content doesn't match its kind's fields in the table above. |
| `tags must be []` | Only profiles may carry tags. |

### Local use (stdio, `tms-sign`)

In a checkout of this repo, an agent such as Claude Code can run the server over stdio. Set `TMS_NSEC` to the agent's key; tool calls without a `request` are then signed with it automatically. Events for `publish` still need signing, which `tms-sign` does:

```bash
TMS_NSEC=nsec1... uv run tms-sign event 4702 '{"collection": "mcas", "text": "A claim."}'
```

```bash
TMS_NSEC=nsec1... uv run tms-sign request search_claims '{"collection": "mcas", "text": "DAO"}'
```

```bash
TMS_NSEC=nsec1... uv run tms-sign pubkey
```

The MCP prompts `claims_pass` and `briefing` walk an agent through turning evidence into claims and links, and through answering questions from a collection with a checked thinking proof.
