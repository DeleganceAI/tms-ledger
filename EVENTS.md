# TMS v2 — Signed Events (draft for review)

Every record in the ledger is a signed event, posted by the human or bot whose key signed it. Nostr is used for keys, browser login and signing, and profiles. Relays are touched only to fetch a user's existing profile. The data is not meant to be readable by Nostr clients.

## 1. What we borrow from Nostr, and why

| Borrowed | Why we need it |
|---|---|
| secp256k1 keys, BIP-340 Schnorr signatures | Every bot and browser signer already has them. |
| The NIP-01 envelope and its ID hash | A browser extension (NIP-07 `window.nostr.signEvent`) signs only this shape. One format for bots and humans. |
| NIP-07 `getPublicKey` / `signEvent` | Browser login and signing. |
| Kind 0 profiles, fetched from relays | Users already have a profile; we show it instead of asking them to re-enter it. |

Not borrowed: tags (`e`, `p`, `t`), NIP-09 deletion, replaceable/addressable kind semantics, publishing to relays, or any other NIP.

## 2. Envelope

```json
{
  "id": "<sha256 hex of the serialization below>",
  "pubkey": "<32-byte x-only hex>",
  "created_at": 1792454400,
  "kind": 4702,
  "tags": [],
  "content": "<JSON object as a string>",
  "sig": "<64-byte BIP-340 hex over id>"
}
```

- `id` = sha256 of the UTF-8 JSON array `[0, pubkey, created_at, kind, tags, content]`, serialized as NIP-01 specifies (no whitespace, minimal escaping).
- `tags` is always `[]`. The envelope requires it; we never use it.
- `content` is a JSON object, serialized to a string. Its fields depend on `kind` (section 4). The server stores this exact string, because the signature covers those bytes.
- `created_at` is the time the signer claims. The server separately records `received_at`, and only `received_at` orders the ledger.
- The `id` is the record's ID everywhere. References between records are IDs, so a record commits to the exact bytes of everything it points at.

## 3. Collections and access

Every collection is **private**. Only its members can read, write or download it.

- A collection is a free slug (`^[a-z0-9][a-z0-9_-]*$`). The first accepted event that names a new slug creates it. That event's signer becomes the collection's **owner** and its only member. A collection has exactly one owner, its admin, and ownership never transfers.
- The owner changes membership with a `members` event (section 4). The latest one, by `received_at`, is the member list. The owner is always a member.
- Every record belongs to exactly one collection, and every reference must stay inside that collection. That way, reading one collection can never reveal records from another.
- Any member can download a full export of the collection (every event, as JSONL). Each line verifies on its own.
- Before their first write, each user signs the current terms (section 4): they have the right to upload everything they upload.

## 4. Kinds

Kind numbers stay within 0–65535, because common Nostr libraries reject larger values. They are placeholders: check them against the NIPs kind list before freezing.

| Kind | Name | Fields in `content` | Stored |
|---|---|---|---|
| 0 | profile | `name`, `about`?, `picture`? | yes |
| 4701 | evidence | `collection`, `text`, `url`?, `title`?, `source`? | yes |
| 4702 | claim | `collection`, `text` | yes |
| 4703 | link | `collection`, `from`, `to`, `relation`, `quote`, `reason` | yes |
| 4704 | contradiction | `collection`, `claims`, `reason` | yes |
| 4705 | members | `collection`, `members` | yes |
| 4706 | terms | `version`, `sha256` | yes |
| 4707 | login | `challenge`, `origin` | no |
| 4708 | snapshot | `date`, `cid`, `sha256`, `count`, `last_received_at` | yes |

Fields marked `?` are optional. All other fields are required, and unknown fields are rejected (kind 0 excepted, since profiles come from other clients).

### profile (0)
A standard Nostr profile. At login the page fetches the user's latest kind 0 from `wss://relay.damus.io` and `wss://relay.primal.net` and posts it to the server, which verifies and stores it like any other event. Users without one can sign a new one on the site. Readers show the latest by `received_at`; every version is kept. Whether a key is a human or an agent is self-declared in `about`, not verified.

### evidence (4701)
A document as the signer saw it: a paper, a page, a post, or an excerpt. `text` is the full text the signer is vouching for, so the signature proves "this key submitted exactly this text". `source` is a free-text publisher or site name (`"Journal of Allergy"`, `"x.com/@someone"`), replacing the old `sources` table. Statements about how reliable a source is are ordinary claims.

### claim (4702)
An opaque statement. Any event time belongs in `text`.

### link (4703)
Evidence bearing on a target.
- `from`: the ID of an evidence event (the grounding document).
- `to`: the ID of any claim, link, contradiction or evidence event. The server looks up what it points at, so no target type is needed.
- `relation`: `SUPPORTS`, `REBUTS` or `QUALIFIES`. `QUALIFIES` is allowed only when `to` is a claim.
- `quote`: a verbatim excerpt of any length that must appear in `from`'s `text`, using the existing normalisation (case, whitespace, curly quotes, dashes, ligatures).
- `reason`: why this quote bears on the target.

Linking to a link or to a contradiction is how you dispute it. That replaces deletion.

### contradiction (4704)
An authored assertion that two or more claims cannot all hold together. Any two of them may be compatible on their own. `claims` lists at least two distinct claim IDs, and the membership is fixed when the event is created; a different set of claims needs a new contradiction. It can't be derived from links: a claim with both SUPPORTS and REBUTS links is merely contested, and readers can compute that with a query.

### members (4705)
Signed by the collection's owner. `members` is the complete list of pubkeys allowed to read and write. Any other signer is rejected.

### terms (4706)
A user's acceptance of the terms in [TERMS.md](TERMS.md). `version` names the document, and `sha256` is the hash of its exact text, so the signature commits to what was accepted. The server rejects writes from a key that hasn't signed the current version.

### login (4707)
Proves control of a key for reading. The server issues a random `challenge`; the browser or bot signs it along with the server's `origin`, and gets back a session token (a cookie in the browser, a bearer token for bots). The server checks that the challenge is unused and less than 5 minutes old. Login events are not stored in the ledger.

### snapshot (4708)
Signed by the server's own key after each daily backup upload to Filecoin. The backup is the whole ledger, encrypted with a server-held key. It's for disaster recovery; members get their own copies from the export. `cid` and `sha256` identify the encrypted file, `count` is the number of events in it, and `last_received_at` marks where it ends. This gives a signed, dated history of what the ledger held.
## 5. Server acceptance rules

The server accepts an event only if:

1. Recomputing the `id` matches, and `sig` verifies for `pubkey`.
2. `kind` is a stored kind from section 4, and `content` parses to an object with exactly that kind's fields. Required strings are non-blank.
3. The signer has signed the current `terms`, and is a member of the event's collection (or is creating it).
4. Every referenced ID exists, either in the ledger or earlier in the same batch, has the kind the field requires, and belongs to the same collection.
5. Link quotes appear in the `from` evidence text.
6. `snapshot` events are signed by the server's key, and no other kind is.

Submissions are batches: either every event in the batch is accepted, or none is. A batch can contain evidence, claims and the links between them, because IDs are known before signing.

If an event with the same `id` already exists, it is skipped silently: the same ID means the same signed bytes, so retries are safe.

Embeddings are derived by the server and are not part of any event.

## 6. Login and reading

- **Browser:** "Connect" calls `getPublicKey()`, fetches and shows the user's profile, then signs a `login` event to start a session. Writes are signed batches, as above.
- **Bots:** sign a `login` event once to get a bearer token for MCP calls, then sign each write batch with their own key.
- Every read is scoped to collections the session's pubkey is a member of.

## 7. Migration

All existing records are migrated into events. How the old unsigned rows get signed is decided at migration time.
