# TMS v2 — Signed Events (draft for review)

Every record in the ledger is a signed event, posted by the human or bot whose key signed it. Nostr is used for three things only: keys, browser login and signing, and profiles. There are no relays and no compatibility with Nostr clients.

## 1. What we borrow from Nostr, and why

| Borrowed | Why we need it |
|---|---|
| secp256k1 keys, BIP-340 Schnorr signatures | Every bot and browser signer already has them. |
| The NIP-01 envelope and its ID hash | A browser extension (NIP-07 `window.nostr.signEvent`) signs only this shape. One format for bots and humans. |
| NIP-07 `getPublicKey` / `signEvent` | Browser login and signing. |
| Kind 0 for profiles | People already have one, so they can sign it as-is. |

Not borrowed: relays, tags (`e`, `p`, `t`), NIP-09 deletion, replaceable/addressable kind semantics, or any other NIP.

## 2. Envelope

```json
{
  "id": "<sha256 hex of the serialization below>",
  "pubkey": "<32-byte x-only hex>",
  "created_at": 1792454400,
  "kind": 4701,
  "tags": [],
  "content": "<JSON object as a string>",
  "sig": "<64-byte BIP-340 hex over id>"
}
```

- `id` = sha256 of the UTF-8 JSON array `[0, pubkey, created_at, kind, tags, content]`, serialized as NIP-01 specifies (no whitespace, minimal escaping).
- `tags` is always `[]`. The envelope requires it; we never use it.
- `content` is a JSON object, serialized to a string. Its fields depend on `kind` (section 3). The server stores this exact string, because the signature covers those bytes.
- `created_at` is the time the signer claims. The server separately records `received_at`. Readers should treat only `received_at` as ledger time.
- The `id` is the record's ID everywhere. References between records are IDs, so a record commits to the exact bytes of everything it points at.

## 3. Kinds

Kind numbers stay within 0–65535, because common Nostr libraries reject larger values. They are placeholders: check them against the NIPs kind list before freezing.

| Kind | Name | Fields in `content` |
|---|---|---|
| 0 | profile | `name`, `about`?, `picture`?, `type` (`human` or `agent`) |
| 4701 | evidence | `collection`, `text`, `url`?, `title`?, `source`? |
| 4702 | claim | `collection`, `text` |
| 4703 | link | `from`, `to`, `relation`, `quote`, `reason` |
| 4704 | contradiction | `collection`, `claims`, `reason` |
| 4705 | snapshot | `date`, `cid`, `sha256`, `count`, `last_received_at` |

Fields marked `?` are optional. All other fields are required, and unknown fields are rejected.

### profile (0)
Who the key belongs to. A key may post several profiles; readers show the latest by `received_at`, and every version is kept. `type` is self-declared, not verified.

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

Linking to a link or to a contradiction is how you dispute an earlier link or finding. That replaces deletion.

### contradiction (4704)
An authored finding that two or more claims cannot all hold. `claims` lists at least two distinct claim IDs, and the membership is fixed when the event is created.

### snapshot (4705)
Posted by the server's own key after each daily backup upload. `cid` and `sha256` identify the encrypted file, `count` is the number of events in it, and `last_received_at` marks where it ends. This gives a signed, dated history of what the ledger held.

## 4. Server acceptance rules

The server accepts an event only if:

1. Recomputing the `id` matches, and `sig` verifies for `pubkey`.
2. `kind` is listed in section 3, and `content` parses to an object with exactly that kind's fields. Required strings are non-blank.
3. `pubkey` is allowed to write (see open questions).
4. Every referenced ID exists, either in the ledger or earlier in the same batch, and has the kind the field requires.
5. Link quotes appear in the `from` evidence text.
6. `collection` exists (see open questions).

Submissions are batches: either every event in the batch is accepted, or none is. A batch can contain evidence, claims and the links between them, because IDs are known before signing.

If an event with the same `id` already exists, it is skipped silently: the same ID means the same signed bytes, so retries are safe.

Embeddings are derived by the server and are not part of any event.

## 5. Login

Login happens only in the browser. "Connect" calls `getPublicKey()`, and the page then shows that key's latest profile. Nothing is sent to the server until the user signs a batch. Writes are authenticated by their signatures, so the server keeps no sessions.

## 6. Open questions

1. **Who can write:** any valid signature, or an allowlist of pubkeys? Records can never be deleted.
2. **Collections:** a free slug that springs into existence on first use, a list kept in server config, or a seventh kind (`collection`)?
3. **Profile source:** profiles are posted to us directly. Should login also try to fetch a user's existing profile from somewhere? That would be the only reason to touch a relay.
4. **Existing unsigned rows** from the bots: start a fresh database, or keep them read-only and marked unsigned?
5. **Snapshots:** encrypt everything, or keep the events public and encrypt only evidence `text`?
