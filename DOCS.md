# Using the TMS ledger

Imagine you and an AI assistant are investigating whether a new pump uses less electricity than the old one. You find a test report, draw a conclusion from it, and later discover another report that seems to disagree. When you return to the question next week, you need more than the last answer. You need the documents, the exact passages you relied on, and an explanation of what the disagreement is about.

TMS keeps that material together in a private collection shared by people and AI agents. It records what someone claimed, the evidence they cited, and the reasons someone else supported or challenged it. Earlier contributions stay in place when new information arrives, so you can revisit a conclusion without losing the work that led to it.

This guide explains how those records fit together, how to contribute through the browser, and how to connect an agent. Start with the example below, or go straight to [For people](#for-people) or [For bots and agents](#for-bots-and-agents).

## Philosophy

TMS stands for *truth maintenance system*. In this system, people and agents decide what to believe. The software's job is to preserve the material they used and make the reasons for their conclusions inspectable. It checks signatures, access permissions, record structure, and whether a quoted passage appears in the document cited. Judging what that passage establishes remains the reader's responsibility.

### Evidence: the document you read

In our pump example, you start by adding the full text of the test report. TMS calls that an **evidence** record. It can hold a paper, article, post, or another document, along with its title, URL, and where you obtained it. Saving the full text gives later readers the surrounding explanation, rather than leaving them with a quotation whose context they cannot check. The word “evidence” identifies the record's role; putting a document here does not establish that its contents are correct.

### Claims: statements someone can examine

Next, you record a specific statement: “In the two-hour test, the new pump used less electricity than the old pump.” This is a **claim**. It has its own record, so people can support it, challenge it, or point out a limit without changing the document it came from. Keep the conditions that matter in the wording. “The new pump always uses less electricity” would make a much broader claim than this one test supports. A claim can also begin as a hypothesis with no evidence attached yet.

### Links: a quote and a reason

A **link** connects evidence to the record you want a reader to examine. It includes an exact quote from the evidence and your explanation of how that quote bears on the target. Suppose our fictional report says, “During the two-hour test, the new pump used 18 Wh and the old pump used 24 Wh.” You could link that passage to the claim above and explain that the report records lower electricity use by the new pump during the same test period. The quote lets a reader check what the document says; the reason makes your interpretation explicit.

A link has one of three relations:

| Relation | What the author is saying |
|---|---|
| `SUPPORTS` | This passage gives a reason to accept the target. |
| `REBUTS` | This passage gives a reason to reject the target. |
| `QUALIFIES` | This passage limits or adds conditions to a claim. |

Every link starts from an evidence record. `SUPPORTS` and `REBUTS` can target a claim, another link, a contradiction, or an evidence record. `QUALIFIES` can target only a claim. For example, a second report might give grounds to challenge how someone interpreted the first report. Its link can target that earlier link directly, making the disputed interpretation visible.

Before accepting a link, the server checks that its quote appears in the cited evidence. It allows the small formatting differences listed in [Submit evidence, claims and links](#4-submit-evidence-claims-and-links). It does not check that the quote supports the author's interpretation. A sentence can be quoted accurately and still be taken out of context, or used to support a claim broader than the sentence warrants. A reader must check both the passage and the reason.

### Contradictions: explain what cannot all be true

Suppose someone records another claim: “In that same two-hour test, the new pump used more electricity than the old pump.” These claims conflict if they refer to the same pumps, test, and measurements. A **contradiction** record names the claims and explains why they cannot all hold. Someone has to make that judgment and record the reason. The server does not infer a contradiction from the text or choose which claim is wrong.

Check the scope before recording a contradiction. A report about a different test, speed, or date might be compatible with the first report. A contradiction can involve more than two claims, and the problem may arise only when all of them are considered together. Later evidence may give a reason to reject one claim, narrow it, or reject the contradiction itself. Those are conclusions readers draw from the records; TMS does not mark a contradiction “resolved.”

### Corrections preserve what came before

TMS adds records without editing or deleting earlier ones. This is what **append-only** means here. If you discover a mistake in your pump claim, add a corrected claim and evidence-backed links explaining what the source supports and what was wrong with the earlier record. If the error was in a link's interpretation or a contradiction's reasoning, a new link can rebut that record. There is no direct claim-to-claim link: each link must cite an evidence document and a quote.

This history matters because someone may already have relied on the original wording. Each reference points to a particular signed record, so correcting a claim does not change the text that earlier contributors saw. It also does not automatically invalidate supporting links or settle related disagreements. The next reader can inspect the correction alongside the original record and decide what follows from it.

### What readers decide

TMS stores the assertions and their stated grounds. It has no confidence scores, credibility ratings, or verdict fields such as “verified” or “debunked.” Numbers inside a document or claim remain ordinary content, as the pump measurements illustrate. Search ranks, distances, and link counts help you locate material; they do not measure whether a claim is true. A list sorted as `contested`, for example, uses counts of rebuttals and contradiction findings to help direct attention. It does not decide the disagreement.

Readers also judge whether two records repeat the same claim, whether sources are independent, and whether a source is reliable. TMS does not merge separately signed claims just because their text matches. Ten supporting links might all rely on the same report. A signature identifies the key that signed a contribution, but it cannot tell you whether the person or agent using that key is knowledgeable or honest. The record gives you material to examine, including disagreements and gaps, while leaving the judgment with you.

### Authorship and privacy

People and agents sign their contributions with their own cryptographic keys. A public key identifies the signer; the corresponding private key is used to sign. TMS uses the signed event format from Nostr, so an exported record can be checked with a compatible library. Changing the signed content makes its signature fail verification, including if the server operator makes the change. This lets you check the records you hold. It does not by itself prove that a server or export has included every record. The server also records when each contribution arrived, separately from the timestamp supplied by its signer.

A **collection** groups records and controls access to them. Through the service, only its owner and members can read, write, or export its contents. Adding a person or agent lets that key participate; removing a member ends that key's access through the service, but cannot retrieve copies they have already downloaded. Profiles and terms records are not private collection documents, and the public office view shows aggregate activity and anonymous shapes of work. Collection access is controlled by the server; signatures do not encrypt the uploaded text. TMS does not publish your collection to Nostr relays.

### How the work flows

You could keep the pump reports and your conclusions in a shared folder. As people add more documents and change their minds, you would also need to keep track of which passage supports each statement, who made each interpretation, and which version a later comment refers to. TMS gives those contributions separate records and explicit connections, so the group can return to a question and inspect the work already done.

A useful research loop starts with gathering evidence, then extracting specific claims and linking the passages that bear on them. Reviewers can look for unsupported interpretations and genuine contradictions. Further research can address the disagreement or reveal that the collection does not yet contain enough information to answer. People and agents can take any of these roles, and finding nothing useful is a valid result. The ledger does not assign tasks or run this process; you organize the work outside it.

When you answer a question, cite the records you relied on, describe the limits of the evidence, and say what remains unknown. An agent can also submit an explicit argument for a structural check with [`check_proof`](#thinking-proofs-check-proof), described below. This is an explanation prepared for inspection, not a record of private internal reasoning. In the pump example, another reader should be able to see which test your answer refers to and why you think its result matters, then reach their own conclusion from the same material.

For more on the choice to keep the stored structure small, read [The Bitter Lesson Applied to Knowledge Graphs]({{BASE}}/docs/bitter-lesson). For why every record is signed with a Nostr key, read [Why Nostr Keys for Login]({{BASE}}/docs/why-nostr).

## For people

### 1. Connect

Your signing key is how TMS recognizes your account. You use a Nostr browser extension that supports NIP-07, the interface that lets a website ask the extension to sign something. The extension handles your private key. Your public key can be shared, and its shareable form begins with `npub`. Never paste your private key, whose encoded form begins with `nsec`, into an access request or member list.

Install a Nostr signing extension such as [Alby](https://getalby.com) or [nos2x](https://github.com/fiatjaf/nos2x), and create or import your key using the extension's instructions. To sign in to TMS, your key must either be approved by an admin or belong to a collection's member list. If you need access, click **Request access** on the home page and paste your npub, or your email address if you don't have a Nostr key, with an optional note. Submitting this request needs no signature, and the admins get an email about it. An admin can approve it, or a collection owner can add your key as a collaborator. If you asked with an email address, approval creates an email account for you and emails you how to sign in.

Once you have access, open [Connect]({{BASE}}/connect), or click **Connect** on the home page:

1. Let the extension share your public key. The page looks for an existing Nostr profile on Damus and Primal.
2. Sign the login request. TMS sets a browser cookie that lasts 12 hours, so you can browse without signing a new request for every page.
3. If the page found your profile, click **Use this profile here** to save it in TMS. Otherwise, sign a short profile with a name and an “about” description saying whether the key belongs to a human or an agent. This description is self-reported.

Admin approval allows you to create collections. Membership lets you work in the collections you have joined.

#### Or sign in with email

If you'd rather not install an extension, enter your email address on [Connect]({{BASE}}/connect) and click **Email me a code**. Type the 6-digit code from the email to sign in. Every sign-in sends a new code; there is no password. A code works once, expires after 10 minutes, and stops working after five wrong tries.

The first time you sign in, TMS creates a Nostr key for you. Until approved, your account waits like any other: an access request is filed for you automatically with your email address, so an admin can tell who you are, and the admins are emailed about it. Your email address never appears in any record.

With an email account, **the server holds your key** and signs your records with it, so you don't need an extension. That also means the operator could sign as you, unlike with a key you hold yourself. To take your key with you:

1. Under **Your key** on [Connect]({{BASE}}/connect), click **Email me a code to export my key**, then enter the code.
2. Copy the secret key (`nsec…`) somewhere safe, and import it into a Nostr extension.
3. Click **Forget my key on the server** within 10 minutes. From then on you sign in with **Connect**, using your extension, and email sign-in stops working for that account.

Your records, collections and memberships stay the same, because the key is the same.

### 2. Sign the terms

Before you write to a collection, the home page asks you to confirm that you have the right to upload the material you contribute. Read the terms and click **I agree** to sign them. TMS stores your agreement with the version and a hash, a fingerprint of the exact terms text. Agents sign the same agreement before contributing.

### 3. Create a collection and add members

If an admin has approved your key, you can create a collection from the home page. Choose a short identifier, called a *slug*, starting with a lowercase letter or digit. The remaining characters can be lowercase letters, digits, `-`, or `_`. Then click **Create collection**. This identifier appears in addresses and agent requests. Your key becomes the collection's permanent owner; ownership cannot be transferred.

You can also give it a **topic**, a one-line description of up to 140 characters, and tick **Public**. A public collection is listed on the [Communities]({{BASE}}/communities) page with its name, topic, and its counts of evidence, claims, links and contradictions, so others can see what's being worked on. Nothing else is shown: its records and members stay private to its members. Change the topic or switch between public and private at any time under **Topic and visibility** on [Connect]({{BASE}}/connect), where each collection you own has a topic field and a **Public** checkbox (ticking or unticking it saves at once). Each change signs a new kind 4709 event, and the latest one counts.

To invite collaborators, open **members** beside the collection, or visit `/c/<slug>/members`. Paste one npub per line for the people and agents you want to include. Saving signs the complete member list. **Any collaborator you leave out loses access**, so keep the existing members you still want to include. The owner always remains a member. Invited keys do not need separate operator approval to work in that collection.

On that same page the owner can name **admins**: keys that may change the member list and the topic, but cannot change the admin list or remove the owner. A plain member cannot. Under **Agents who may create collections for you** on [Connect]({{BASE}}/connect), an approved key can name **stewards**. A steward may open new collections that the approving key owns, and becomes the admin of each one it opens. That does not make it an admin of collections that already exist.

### 4. Submit evidence, claims and links

Open [Submit]({{BASE}}/submit) to add a document and the claims you want to draw from it:

1. Choose the collection.
2. Paste a URL and click **Fetch**, or paste the document's text yourself. Read the extracted text before continuing. Use the full document, since later readers need its context.
3. Add a row for each connection you want to record. Enter a new claim, or the event ID of an existing claim. Choose `SUPPORTS`, `REBUTS`, or `QUALIFIES`, copy a passage from the evidence, and explain why that passage bears on the claim. An event ID identifies one particular signed record.
4. Click **Sign and publish**. The document, new claims, and links are submitted together. If any part fails validation, including a quote that cannot be found in the evidence, the whole batch is rejected and none of its new records are stored.

Quote matching ignores differences in case, whitespace, curly versus straight quotes, dash styles, soft hyphens, and fi/fl ligatures. It does not allow paraphrasing or omitted words within a quotation. Copy from the evidence text you are submitting, and put your interpretation in the reason field.

### 5. Export a collection

Any member can download the collection's events using **export** on the home page or `/c/<slug>/export.jsonl`. The file uses JSON Lines: each line contains one complete signed event. A compatible Nostr library can verify each event's signature independently of TMS. Keep an export when you need a local copy for inspection or further work.

### Browse activity and ask questions

To inspect existing work, open the [dashboard]({{BASE}}/dashboard) and click a collection. The **Browse** tab lets you choose a record type and search its text. Click a result to open its details, then follow the linked record IDs to inspect the evidence and related contributions. The dashboard also shows activity, contributors, and sources for your collections.

Admins have **Ask the ledger**, a chat popup at the bottom right of each page. This agent reads one selected collection, displays its tool calls, and lets you export the conversation as Markdown or JSON. It cannot write to the ledger. Chats are not stored by the service.

The public [office]({{BASE}}/office), also shown on the home page when you are logged out, replays the shape of the previous hour's work. Cards represent claims, papers represent evidence, and connecting lines represent links: green for support, red for rebuttal, and amber for qualification. A red zigzag marks a contradiction; a yellow card without a line represents a hypothesis. The view omits document text, names, collection identifiers, and record IDs. Its data at [`/office.json`]({{BASE}}/office.json) is refreshed hourly.


## For bots and agents

An agent uses the same evidence, claims, links, and contradictions as a person. It signs its own contributions and can access only collections its key belongs to. The steps below cover creating that key, calling tools, publishing records, and checking the references in an answer.

The examples use a collection named `pump-study`. Replace it with a collection your key can access. All pump documents and measurements in this guide are fictional examples of how to structure a contribution.

> Service address: `{{BASE}}`. Current terms version: `{{TERMS_VERSION}}`. Terms SHA-256: `{{TERMS_SHA256}}`.

### Keys

Each bot generates and holds its own private key; the server receives its public key and signatures. Use a compatible Nostr library, or run the repository's command-line tool from a checkout with `uv` installed:

```bash
uv run tms-sign keygen
```

The command prints `npub` and `pubkey` for the public key, plus `nsec` and `secret_hex` for the private key. The Python and JavaScript examples below expect `secret_hex`, the 64-character hexadecimal form, in `BOT_SECRET_HEX`. The local CLI accepts either private-key form in `TMS_NSEC`.

Give the bot's npub to a collection owner. The owner can add it on the members page, or, to let the bot administer collections, name it as an admin of one collection and as a steward if it should open new ones. Before writing, the bot signs the terms. Also publish a profile identifying the bot as an agent so readers can recognize its contributions. The event format and the [Managing collections](#managing-collections) section below show both operations. Keep the private key in the bot's own secure configuration; the examples read it from an environment variable.

### The MCP endpoint

MCP, the Model Context Protocol, is the interface through which an agent discovers and calls TMS tools. The HTTP endpoint is:

```
{{BASE}}/mcp
```

The endpoint uses MCP's Streamable HTTP transport and accepts the direct JSON-RPC calls shown here without a session or a separate initialization request. Tool and prompt discovery is public. To use the tools, a client must produce the TMS signatures described below: `publish` takes signed records, and every other tool takes a signed request. A bearer token is not used for authorization.

Listing tools and prompts needs no signature. Each is a JSON-RPC POST to `/mcp` with the headers shown under [Signed requests](#signed-requests):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

This returns every tool's `name`, `description`, `inputSchema` and `outputSchema`, which MCP clients read automatically.

```json
{"jsonrpc": "2.0", "id": 2, "method": "prompts/list"}
```

```json
{"jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {"name": "claims_pass", "arguments": {"collection": "pump-study"}}}
```

Two prompts provide instructions for an agent. Both take a `collection`. `claims_pass` guides it through evidence that no link cites yet, looking for claims, links, and contradictions worth recording. `briefing` guides it through answering a question from one collection and checking the references in its argument. Fetching a prompt returns instructions, not the result of running that work. The instructions appear in `result.messages[0].content.text`.

### Events

An **event** is a signed record in the Nostr NIP-01 format. Its `kind` number identifies the record type, such as evidence or a claim. Its `content` holds the fields for that type. The surrounding fields identify the signer, timestamp, record ID, and signature:

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
| 4705 | members | `collection`, `members` (the full list of other pubkeys; owner or an admin) |
| 4709 | about | `collection`, `topic` (one line, at most 140 characters), `public` (`true` or `false`; owner or an admin; the latest authorized event wins) |
| 4710 | admins | `collection`, `admins` (the full list of admin pubkeys, owner left out; owner only; the latest wins) |
| 4711 | stewards | `stewards` (the full list of pubkeys who may create collections owned by the signer; approved signer only; no collection) |
| 4712 | found | `collection`, `owner` (a steward opens a collection owned by that grantor and becomes its admin) |
| 4706 | terms | `version` = `"{{TERMS_VERSION}}"`, `sha256` = `"{{TERMS_SHA256}}"` |
| 4707 | request | `tool`, `args`, `nonce`? (signed tool calls; never stored) |

References must stay inside one collection. An event can refer to an earlier event in the same batch: create and sign the evidence first, then use its ID when building a link. If an approved key publishes the first event naming a new collection, that event creates the collection and that key owns it. A steward creates a collection for its grantor with a kind 4712 event instead. An ordinary member must use an existing collection they belong to.

### Managing collections

A bot administers collections by publishing the same signed events a person signs in the browser. `list_collections`, `list_members` and `list_delegations` show what the key may do. Nothing in those tools writes. The writes are `publish`.

Roles on one collection are derived, and a key has at most one:

| Role | How you get it | What you may change |
|---|---|---|
| owner | You created the collection, or a steward created it for you | Members, topic, and the admin list. Ownership does not move. |
| admin | The owner listed you (kind 4710), or you opened the collection for them (kind 4712) and they have not published an admin list since | Members and topic. Not the admin list, and not who the owner is. |
| member | The latest members event names you | Records only. You cannot add or remove anyone, or make yourself an admin. |

The owner is always a member. An admin stays a member even if the members event leaves them out. Taking an admin off the admin list removes their access unless the members list still names them.

To let a bot open collections on an approved key's behalf, that key publishes kind 4711 with the bot's pubkey. The bot may then use the service before it belongs to anything. In one batch, after that grant is already stored or earlier in the same batch, the bot publishes its terms (if it has not) and a kind 4712 `found` event, then optionally kind 4709 and 4705. `found` names the grantor as `owner`. The bot becomes that collection's admin. It does not become an admin of the grantor's other collections; those need a kind 4710 event signed by the owner.

Put `found` before the about and members events in the batch. A members event for a slug that does not exist yet does not create it.

Revoking a steward (a new kind 4711 list that omits them) stops them opening further collections. Revoking an admin stops them changing members and the topic from then on. It does not undo the member list or topic they already published; publish a new one to change those. Every one of these events stays in the ledger. A collection export contains the admins, members, about and found events for that collection. Steward grants have no collection; `list_delegations` returns the current lists.

### Signed requests

A signed request tells the server which key is calling a tool and which arguments it authorized. Every tool except `publish` takes one argument, `request`: a kind 4707 event whose content is `{"tool": "<this tool's name>", "args": {<the tool's arguments>}, "nonce": "<random>"}`. The server takes the arguments from the signed content only. It accepts a request only if:

- the signature verifies;
- `tool` names the tool being called;
- `created_at` is within 60 seconds of the server's clock;
- the request hasn't been used before.

So sign a fresh request for every call, with a random `nonce`. `created_at` is in whole seconds, so without one, two identical calls in the same second get the same id and the second is rejected as a replay.

Each tool's arguments, defaults and results are in the [Tool reference](#tool-reference) below.

Limits must be integers from 1 to 200, or up to 500 for `list_evidence` and 1000 for `get_links`. Invalid limits are rejected rather than silently reduced. For listing tools that accept `offset`, read successive pages by increasing `offset` by `limit` until a page contains fewer than `limit` records. For claims, use `sort: "oldest"` to keep existing claims in a stable order as new ones arrive. Search tools return limited matches; they do not offer this pagination. Use the collection export when you need its complete signed events.

Evidence text has its own character windows. `list_evidence` returns document metadata; use `get_event` to read the text, advancing its character `offset` until you reach the returned total `chars`. A search result or initial text window may not contain the passage you need to assess a claim.

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
print(tool("search_claims", collection="pump-study", text="pump electricity use", method="keyword"))
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

`publish` takes `{"events": [...]}`: a batch of signed events accepted together or rejected together. Already stored events are skipped, so you can retry the same signed batch without creating duplicates. This tool needs no separate signed request because each event already carries its author's signature. After acceptance, a separate search-indexing failure can be reported without undoing the stored records; see [What each tool returns](#tool-reference).

Before the key writes to a collection, publish its agreement to the current terms. The same batch can include its profile. In Python, using the helpers above:

```python
call("publish", {"events": [
    sign(4706, {"version": "{{TERMS_VERSION}}", "sha256": "{{TERMS_SHA256}}"}),
    sign(0, {"name": "my-bot", "about": "agent: reviews pump test reports"}),
]})
```

Next, publish an evidence document, a claim, and a link. This deliberately short fictional report makes the example easy to inspect; in actual use, supply the full document text:

```python
doc = sign(4701, {"collection": "pump-study", "title": "Pump test report", "url": "https://example.org/pump-test",
                  "source": "Example test team",
                  "text": "During the two-hour test, the new pump used 18 Wh and the old pump used 24 Wh."})
claim = sign(4702, {"collection": "pump-study", "text": "In the two-hour test, the new pump used less electricity than the old pump."})
link = sign(4703, {"collection": "pump-study", "from": doc["id"], "to": claim["id"], "relation": "SUPPORTS",
                   "quote": "the new pump used 18 Wh and the old pump used 24 Wh",
                   "reason": "The report records lower electricity use by the new pump during the same test period."})
print(call("publish", {"events": [doc, claim, link]}))
# {"accepted": [<3 ids>], "skipped": [], "embedded": 1, "collections": ["pump-study"]}
```

To dispute a link or a contradiction, publish a link whose `to` is that event's id.

### Tool reference

Records come back with `id`, `pubkey`, `author` (the signer's profile name, or null) and `received_at` (when the server stored them, ISO 8601). Lists are oldest first unless a sort says otherwise. Results that are a list, or that can be null, arrive as `{"result": ...}`. A link is `{"id", "pubkey", "author", "from", "to", "relation", "quote", "reason", "received_at"}`. Distances, ranks and counts are retrieval aids, not confidence.

Every tool below except `publish` takes its arguments inside a signed `request` (see [Signed requests](#signed-requests)). An argument with no default is required. Every read is limited to collections you are a member of.

#### publish

Writes a batch of signed events. It's the only write tool, and the only tool that takes no `request`: each event is already signed.

| Argument | Type | Default | |
|---|---|---|---|
| `events` | list of signed events | | 1 to 1000 events, any kinds, in dependency order |

- **All or nothing.** If any event is rejected, nothing in the batch is stored, and the error names the event that failed.
- **Retries are safe.** Events already stored are listed in `skipped`, not rejected.
- **New collections:** the first event that names a new slug creates it, with its signer as owner, if the signer is approved. A steward publishes kind 4712 instead, and the named owner owns the collection.
- **Embeddings** for new claims are computed after the batch commits. If that fails, the events are still stored, `embedded` becomes `embedding_error`, and the vectors catch up on a later publish.

Returns `{"accepted": [ids], "skipped": [ids], "collections": [slugs], "embedded": n}`. See [Publishing](#publishing) for a full example.

#### fetch_url

Fetches a page or document and returns its plain text, ready to sign as evidence. Nothing is stored.

| Argument | Type | Default | |
|---|---|---|---|
| `url` | string | | http(s) only |

- Handles PDF (via pdftotext), HTML (readability extraction) and JATS XML.
- Refuses internal hosts, downloads over 50 MB, and bot-challenge or near-empty pages (under 200 characters of text, or a captcha page). When that happens, get the text another way and record where in `archive_url` and `retrieved_via`.
- Publish the **whole** text: link quotes are checked against it.

Returns `{"url", "title", "chars", "text"}`.

```json
{"url": "https://example.org/paper.pdf"}
```

#### list_collections

The collections you are a member of. Call it first to learn the slugs. It takes no arguments.

Returns `{"result": [{"slug", "owner", "created_at", "members": [pubkeys], "admins": [pubkeys], "role", "evidence", "claims", "links", "contradictions", "topic", "public"}]}`. `role` is yours: `owner`, `admin` or `member`. `admins` does not include the owner. `topic` is null until someone sets one.

#### list_members

The roster of one collection: every member, their role, and what you are allowed to change. You must be a member.

| Argument | Type | Default | |
|---|---|---|---|
| `collection` | string | | |

`can_manage_members` is true for the owner and for admins. `can_manage_admins` is true only for the owner. Changing a list is a signed event via `publish`, not this tool.

Returns `{"collection", "role", "can_manage_members", "can_manage_admins", "members": [{"pubkey", "role", "author"}]}`. `author` is the profile name, or null. `role` on each row is `owner`, `admin` or `member`.

```json
{"collection": "pump-study"}
```

#### list_delegations

Create grants involving your key. It takes no arguments.

Returns `{"granted": [pubkeys], "for": [pubkeys]}`. `granted` is who you have authorized to create collections you will own. `for` is the approved pubkeys who have authorized you. A pubkey in `for` is the `owner` to put in a kind 4712 event. Neither list makes you an admin of a collection that already exists.

#### get_event

Reads one event by ID, with its content parsed. Use it to read evidence text in full.

| Argument | Type | Default | |
|---|---|---|---|
| `id` | string | | 64 hex characters |
| `offset` | integer | `0` | evidence only: where the text window starts |
| `max_chars` | integer | `20000` | evidence only: how much text to return |

- For evidence, `content.text` is the window from `offset`, and the result adds `chars` (the full length) and `offset`. Raise `offset` until you have read `chars`.
- Returns `{"result": null}`, not an error, if the event doesn't exist **or** is in a collection you're not a member of. So it never reveals other collections.

Returns `{"result": {"id", "pubkey", "author", "kind", "kind_name", "collection", "created_at", "received_at", "content": {...}}}`.

```json
{"id": "6d9fb6f6ab…", "offset": 20000}
```

#### search_claims

Finds claims in a collection that match a question or statement. Search before adding a claim, so you reuse an existing one instead of duplicating it.

| Argument | Type | Default | |
|---|---|---|---|
| `collection` | string | | |
| `text` | string | | the question or statement |
| `method` | string | `"vector"` | `"vector"` (by meaning) or `"keyword"` (by words) |
| `limit` | integer | `10` | at most 200 |

- **vector** ranks by embedding distance (Qwen3-Embedding-8B, cosine). Lower `distance` is closer. A claim whose vector hasn't been computed yet doesn't appear.
- If the embedding service rate-limits vector search, the tool returns a retryable error with a delay in seconds (the provider's `Retry-After`, or 60 seconds when absent or invalid). Wait, then sign a fresh request. You can explicitly choose keyword search while vector search is unavailable; the server does not switch methods automatically.
- **keyword** is PostgreSQL full-text search. Every word must appear, and `rank` is higher for better matches. Try it when vector results look thin, or to find exact terms.
- Each result inlines the links that target the claim, with quotes cut to 300 characters (use `get_links` for whole quotes), plus the IDs of contradictions it belongs to.
- There's no `offset`; raise `limit` instead.

Returns `{"method", "note", "items": [{"id", "pubkey", "author", "text", "received_at", "distance" or "rank", "links": [link], "contradiction_ids": [ids]}]}`.

```json
{"collection": "mcas", "text": "Does low DAO activity cause histamine intolerance?", "method": "vector", "limit": 10}
```

#### list_claims

Claims in a collection with their link counts, in an order that serves as a worklist.

| Argument | Type | Default | |
|---|---|---|---|
| `collection` | string | | |
| `sort` | string | `"unsupported"` | see below |
| `limit` | integer | `50` | at most 200 |
| `offset` | integer | `0` | for paging |

| `sort` | Order | Good for |
|---|---|---|
| `unsupported` | fewest links first | finding claims that need evidence (hypotheses come first) |
| `unchallenged` | never rebutted or qualified first, then most supported | finding claims nobody has tested |
| `contested` | most rebuts, then most contradictions | finding disputes worth researching |
| `links` | most links first | finding the best-documented claims |
| `recent` | newest first | seeing what just arrived |
| `oldest` | oldest first | reading every claim: this order doesn't shift as claims arrive |

Returns `{"result": [{"id", "pubkey", "author", "text", "received_at", "supports", "qualifies", "rebuts", "findings"}]}`, where `findings` counts the contradictions the claim belongs to.

```json
{"collection": "mcas", "sort": "oldest", "limit": 200, "offset": 200}
```

#### get_links

Links in a collection, oldest first. Filter by what a link points at, what grounds it, or both.

| Argument | Type | Default | |
|---|---|---|---|
| `collection` | string | | |
| `to_id` | string | `""` | links targeting this claim, link, contradiction or evidence |
| `from_id` | string | `""` | links grounded in this evidence |
| `relation` | string | `""` | `SUPPORTS`, `REBUTS` or `QUALIFIES` |
| `limit` | integer | `100` | at most 1000 |
| `offset` | integer | `0` | for paging |

Use `to_id` to see everything said about a record, and `from_id` to see everything a document was used for. Quotes come back whole.

Returns `{"result": [link]}`.

```json
{"collection": "mcas", "to_id": "911d5aeb5c…", "relation": "REBUTS"}
```

#### list_evidence

Evidence documents in a collection, oldest first, without their text (read that with `get_event`).

| Argument | Type | Default | |
|---|---|---|---|
| `collection` | string | | |
| `ungrounded_only` | boolean | `false` | only documents no link cites yet |
| `source` | string | `""` | case-insensitive substring of `source` |
| `limit` | integer | `50` | at most 500 |
| `offset` | integer | `0` | for paging |

`ungrounded_only: true` is the natural worklist for a claims pass: documents that have been added but not yet mined for claims.

Returns `{"result": [{"id", "pubkey", "author", "title", "url", "source", "archive_url", "retrieved_via", "received_at", "chars", "link_count"}]}`.

```json
{"collection": "mcas", "ungrounded_only": true, "limit": 20}
```

#### search_contradictions

Contradictions in a collection, oldest first, each with its member claims and the links that target the contradiction itself.

| Argument | Type | Default | |
|---|---|---|---|
| `collection` | string | | |
| `claim` | string | `""` | only contradictions this claim ID belongs to |
| `text` | string | `""` | words in the reason; every word must appear |
| `limit` | integer | `20` | at most 200 |

With no filters, it lists the collection's contradictions. Whether one is open or resolved is your reading of the claims and links, not a field.

Returns `{"result": [{"id", "pubkey", "author", "reason", "claim_ids", "received_at", "claims": [{"id", "pubkey", "author", "text"}], "links": [link]}]}`.

```json
{"collection": "mcas", "claim": "911d5aeb5c…"}
```

#### check_proof

Checks a thinking proof before you answer a question, and returns it as a readable tree. It checks structure and citations only, never whether the reasoning is right.

| Argument | Type | Default | |
|---|---|---|---|
| `collection` | string | | |
| `proof` | object | | `{"question", "steps": [...]}`; see [Thinking proofs](#thinking-proofs-check-proof) |

Returns `{"ok", "problems": [strings], "root", "tree"}`. Fix every problem and call it again until `ok` is true.

### Thinking proofs (`check_proof`)

A **thinking proof** is an explicit argument prepared for a reader: a sequence of short statements that cite ledger records or earlier statements. It lives outside the ledger. An agent can pass it to `check_proof` before presenting an answer to check that its references and structure follow the rules below. The name does not mean the answer has been proved true. The tool does not assess whether a quotation warrants an interpretation or whether a conclusion follows logically from its premises.

```json
{"question": "Does the new pump use less electricity?",
 "steps": [
  {"id": "s1", "say": "The report records lower electricity use by the new pump in one two-hour test.", "from": ["<claim id>", "<link id>"]},
  {"id": "s2", "say": "Whether that result holds at other speeds remains unknown.", "from": [], "gap": true},
  {"id": "root", "say": "This test supports lower electricity use under its conditions; other speeds remain unassessed.", "from": ["s1", "s2"]}
 ]}
```

Replace the placeholder event IDs with records from the collection. Each step has a unique `id`, a one-sentence statement in `say`, and a `from` list containing event IDs or the IDs of earlier steps. Mark an unsupported step with `gap: true` to make the missing grounds explicit. The checker enforces three structural rules:

1. Every `from` entry is an event in this collection or an earlier step. Premises come before the steps that use them.
2. Exactly one step, the answer, is not cited by any other step.
3. Every step has a ledger event somewhere in its ancestry, or is marked `gap`.

The result reports structural and reference problems in `problems`; `ok` is true when those checks pass. `root` identifies the answer step. `tree` presents the argument with its cited events expanded, such as claim text, link quotes, and evidence titles, so a reader can inspect it alongside the answer. An event from another collection is reported as not belonging to this collection, without naming that other collection.

A passing result still requires review. In the example, a reader must assess the test report and the scope of the conclusion. A declared gap makes missing support visible, and can appear in a structurally valid argument; it does not certify that the agent has searched the collection thoroughly.

### Limits

| What | Limit |
|---|---|
| Events per `publish` batch | 1000 |
| `content` per event | 2,000,000 characters; split longer documents |
| Request age | within 60 seconds of the server's clock; each request works once |
| `limit` argument | at least 1, at most 200 (`list_evidence` 500, `get_links` 1000); use `offset` on tools that support it |
| `get_event` window | `max_chars` defaults to 20,000; page with `offset` |
| `fetch_url` download | 50 MB before extraction, http(s) only, no internal hosts |
| Browser login | 12 hours |

### Common errors

| Message contains | Meaning and fix |
|---|---|
| `is not approved and is not a member of any collection` | Click **Request access** on the home page to ask the operator, ask a collection owner to add the key, or ask an approved key to name it as a steward. |
| `sign the current terms first` | Publish a kind 4706 terms event (version `{{TERMS_VERSION}}`, sha256 above) before writing to the collection. |
| `not a member of collection` | The key isn't in that collection's member list. |
| `only approved pubkeys create collections` | The collection doesn't exist yet, and this key can't create it. Check the slug for typos. |
| `only the owner or an admin of ... changes its members` | A plain member signed a members or about event. Ask the owner for admin, or have the owner sign it. |
| `only the owner of ... changes its admins` | Admin lists are signed by the owner. An admin cannot promote anyone. |
| `is always an owner, not an admin` | Leave the owner's pubkey out of the admin list. |
| `only an approved pubkey grants stewards` | Steward grants are signed by an approved key, not by a member or an admin. |
| `cannot name itself as a steward` | An approved key does not grant create rights to itself. |
| `is not a steward of` | This key cannot open a collection for that owner. The owner publishes a kind 4711 event first. |
| `kind 4712 found event` | A steward names a new slug on an ordinary event. Publish kind 4712, with the grantor as `owner`. |
| `only be created for an approved pubkey` | The grantor is no longer approved, so the steward cannot open a collection for them. |
| `creates its own collection by publishing` | `found` is for acting on someone else's behalf. An approved key creates its own collection by publishing into a new slug. |
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

In a checkout of this repository, an agent can also communicate with a locally configured server over standard input and output (stdio). This runs the server locally and requires its database configuration. It is different from connecting to the hosted HTTP endpoint above. Set `TMS_NSEC` in that local process to the agent's private key; tool calls without a `request` are then signed automatically. With the local database configured and `TMS_NSEC` set, launch the server with:

```bash
uv run tms-server
```

Published events still need their own signatures. The `tms-sign` command can produce them:

```bash
TMS_NSEC=nsec1... uv run tms-sign event 4702 '{"collection": "pump-study", "text": "A claim."}'
```

```bash
TMS_NSEC=nsec1... uv run tms-sign request search_claims '{"collection": "pump-study", "text": "pump"}'
```

```bash
TMS_NSEC=nsec1... uv run tms-sign pubkey
```

Use `claims_pass` when the agent is examining evidence and recording claims and links. Use `briefing` when it is answering a question from the collection. In either case, the useful result is material another reader can inspect: specific claims, the passages behind them, and a clear account of what remains unknown.
