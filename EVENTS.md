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
- `tags` is `[]` on every kind except profiles (kind 0). Profiles come from other Nostr clients, which often add tags, so a profile may carry any tags (a list of non-empty lists of strings). The server stores them verbatim, because the signature covers them, and ignores them everywhere else.
- `content` is a JSON object, serialized to a string. Its fields depend on `kind` (section 4). The server stores this exact string, because the signature covers those bytes.
- `created_at` is the time the signer claims. The server separately records `received_at`, and only `received_at` orders the ledger.
- The `id` is the record's ID everywhere. References between records are IDs, so a record commits to the exact bytes of everything it points at.

## 3. Collections and access

Every collection is **private**. Only its members can read, write or download it.

A pubkey can use the service at all only if the operator has approved it (`TMS_APPROVED`), or it is a member of at least one collection, or an approved pubkey has named it as a steward (below). An owner can add any pubkey to their collection without operator approval. Only approved pubkeys can create collections they themselves own. A steward can create collections owned by the pubkey that granted them. Everyone else gets nothing beyond the tool list.

- A collection is a free slug (`^[a-z0-9][a-z0-9_-]*$`). The first accepted event that names a new slug creates it, if its signer is approved. That event's signer becomes the collection's **owner** and its only member. A collection has exactly one owner, and ownership never transfers.
- Three roles, and a key holds at most one of them. **Owner** is the pubkey stored when the collection is created. **Admin** may change the member list and the topic. **Member** may read and write records and may not change who else is here. The owner is always a member. An admin is always a member, whether or not the member list names them. A member cannot become an admin or an owner by anything it signs itself.
- The owner names admins with an `admins` event (section 4). The latest one the owner signed, by `received_at`, is the whole admin set. Until the owner has signed one, the steward who opened the collection with a `found` event is its admin. An `admins` event replaces that founder, including when the list is empty.
- The owner, or an admin at that moment, changes membership with a `members` event. The latest such event, by `received_at`, is the member list. An event signed by anyone else does not count, including one signed by an admin after they were revoked. Revoking an admin does not rewrite the list they already signed; it only stops them signing another. The owner is unioned in, so a members event cannot remove the owner.
- An approved pubkey names **stewards** with a `stewards` event (no collection). The latest one that pubkey signed is the set of keys that may open new collections **owned by the grantor**. A steward is not thereby a member or an admin of collections that already exist. Opening one is a `found` event: the collection's owner is the grantor, and the signer becomes its admin. A key cannot name itself as a steward, and a steward cannot name further stewards.
- Every record belongs to exactly one collection, except profiles, terms, snapshots and stewards grants, and every reference must stay inside that collection. That way, reading one collection can never reveal records from another.
- Any member can download a full export of the collection (every event, as JSONL). Each line verifies on its own.
- Before their first write, each user signs the current terms (section 4): they have the right to upload everything they upload.

## 4. Kinds

Kind numbers stay within 0–65535, because common Nostr libraries reject larger values. They are placeholders: check them against the NIPs kind list before freezing.

| Kind | Name | Fields in `content` | Stored |
|---|---|---|---|
| 0 | profile | `name`, `about`?, `picture`? | yes |
| 4701 | evidence | `collection`, `text`, `url`?, `title`?, `source`?, `archive_url`?, `retrieved_via`? | yes |
| 4702 | claim | `collection`, `text` | yes |
| 4703 | link | `collection`, `from`, `to`, `relation`, `quote`, `reason` | yes |
| 4704 | contradiction | `collection`, `claims`, `reason` | yes |
| 4705 | members | `collection`, `members` | yes |
| 4706 | terms | `version`, `sha256` | yes |
| 4707 | request | `tool`, `args`, `nonce`? | no |
| 4708 | snapshot | `date`, `cid`, `sha256`, `count`, `last_received_at` | yes |
| 4709 | about | `collection`, `topic`, `public` | yes |
| 4710 | admins | `collection`, `admins` | yes |
| 4711 | stewards | `stewards` | yes |
| 4712 | found | `collection`, `owner` | yes |

Fields marked `?` are optional. All other fields are required, and unknown fields are rejected (kind 0 excepted, since profiles come from other clients).

### profile (0)
A standard Nostr profile. At login the page fetches the user's latest kind 0 from `wss://relay.damus.io` and `wss://relay.primal.net` and posts it to the server, which verifies and stores it like any other event. Its `tags` are stored as signed and otherwise ignored. Users without one can sign a new one on the site. Readers show the latest by `received_at`; every version is kept. Whether a key is a human or an agent is self-declared in `about`, not verified.

### evidence (4701)
A document as the signer saw it: a paper, a page, a post, or an excerpt. `text` is the full text the signer is vouching for, so the signature proves "this key submitted exactly this text". `source` is a free-text publisher or site name (`"Journal of Allergy"`, `"x.com/@someone"`), replacing the old `sources` table. Statements about how reliable a source is are ordinary claims. When the text came from somewhere other than `url` (a publisher blocks bots), `archive_url` is where it was actually read (a Wayback snapshot, a syndicated copy) and `retrieved_via` says how (`"Wayback"`, `"NewsAPI.ai"`), so `text` holds only the document.

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
Signed by the collection's owner, or by a pubkey that is an admin of that collection when the server receives the event. `members` is the complete list of other pubkeys allowed to read and write. The owner is always a member, and so is every current admin, even if this list leaves them out. Any other signer is rejected. The latest event that was authorized when it was received is the list; a later event from a revoked admin is ignored, and the list they signed earlier stays until a current owner or admin publishes a new one.

### admins (4710)
Signed by the collection's owner only. `admins` is the complete list of pubkeys who may change members and about. It must not include the owner: the owner is not an admin, and the two roles do not overlap. Duplicates are rejected. The latest owner-signed event is the whole set, and an empty list means there are no admins. An admin cannot sign this event, so an admin cannot promote anyone, including itself. If the owner has never signed one, the steward who published the collection's `found` event is the admin instead; the first `admins` event replaces that founder.

### stewards (4711)
Signed by an approved pubkey. There is no collection. `stewards` is the complete list of pubkeys who may create collections owned by the signer. The signer cannot name itself. Duplicates are rejected. The latest event from that signer is the whole set; an empty list revokes every steward. A steward is allowed to use the service even before it belongs to a collection, but only while the grantor is still approved. A member or an admin who is not themselves approved cannot sign this event, so the grant cannot be passed on.

### found (4712)
Signed by a steward. `owner` is the approved pubkey that named the signer as a steward, and `collection` is a slug that does not exist yet. The collection's owner is `owner`, not the signer. The signer becomes the collection's admin (and therefore a member) until the owner publishes an `admins` event. A key does not use `found` to create a collection it will own; an approved key does that by publishing any other event that names a new slug.

### terms (4706)
A user's acceptance of the terms in [TERMS.md](TERMS.md). `version` names the document, and `sha256` is the hash of its exact text, so the signature commits to what was accepted. The server rejects writes from a key that hasn't signed the current version.

### request (4707)
A signed tool call. `tool` names the MCP tool (or `login` for the browser), and `args` holds its arguments. The server reads the arguments from this signed content, so nothing else has to be hashed or matched. It accepts a request only if:
- the signature verifies;
- `tool` is the tool being called;
- `created_at` is within 60 seconds of server time;
- the `id` hasn't been seen before (replay protection, checked against a short-lived `auth_seen` table).

`nonce` is any string. `created_at` is in whole seconds, so two identical calls signed in the same second would get the same `id` and the second would look like a replay; a random `nonce` keeps them apart.

Requests are not stored in the ledger.

### about (4709)
Signed by the collection's owner, or by a pubkey that is an admin when the server receives the event. `topic` is a one-line description, at most 140 characters. `public` (true or false) says whether the public [Communities](/communities) page may show the collection's name, topic, and its counts of evidence, claims, links and contradictions. Its records, members and everything else stay private either way. The latest event that was authorized when it was received is in effect. Revoking the signer does not by itself revert the topic.

### snapshot (4708)
Signed by the server's own key after each daily backup upload to Filecoin. The backup is the whole ledger, encrypted with a server-held key. It's for disaster recovery; members get their own copies from the export. `cid` and `sha256` identify the encrypted file, `count` is the number of events in it, and `last_received_at` marks where it ends. This gives a signed, dated history of what the ledger held.

## 5. Server acceptance rules

The server accepts an event only if:

1. Recomputing the `id` matches, and `sig` verifies for `pubkey`.
2. `kind` is a stored kind from section 4, and `content` parses to an object with exactly that kind's fields. Required strings are non-blank.
3. The signer is approved, a member of some collection, or a steward of a pubkey that is still approved. For `profile` and `terms` events, that is enough. A `stewards` event must be signed by an approved pubkey. A `found` event must be signed by a current steward of the named owner, and that owner must still be approved; it creates the collection. For every other kind, the signer must also have signed the current `terms`, and must be a member of the event's collection, or be approved and creating it. `admins` events must be signed by the owner. `members` and `about` events must be signed by the owner or by a current admin.
4. Every referenced ID exists, either in the ledger or earlier in the same batch, has the kind the field requires, and belongs to the same collection.
5. Link quotes appear in the `from` evidence text.
6. `snapshot` events are signed by the server's key, and no other kind is.
7. `request` events are never published; they only accompany tool calls.

Submissions are batches: either every event in the batch is accepted, or none is. A batch can contain evidence, claims and the links between them, because IDs are known before signing.

If an event with the same `id` already exists, it is skipped silently: the same ID means the same signed bytes, so retries are safe.

Embeddings are derived by the server and are not part of any event.

## 6. Login and reading

- **MCP:** the endpoint is open, so anyone can list the tools, and there's no shared token. `publish(events)` needs nothing extra, because every event in the batch is already signed. Every other tool takes a single `request` argument (kind 4707), signed fresh for each call. This works with any MCP client, because it's just a tool argument.
- **Browser:** "Log in" calls `getPublicKey()`, fetches and shows the user's profile, then signs a `request` with `tool: "login"`. The server returns a signed HttpOnly cookie, valid for 12 hours, so the extension doesn't prompt on every page. Writes are still signed batches.
- Every read is scoped to the collections the signer is a member of.

## 7. Migration

Nothing is migrated. The cloud ledger starts empty, and agents re-upload.
