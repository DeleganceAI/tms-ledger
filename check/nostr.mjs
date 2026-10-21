// Cross-check for tms/events.py (run by test_events.py): reads {python: [events], sign: [{sk, kind, content, created_at}]}
// on stdin and returns nostr-tools' ID and verification for each Python event, plus events nostr-tools signed itself.
import { getEventHash, verifyEvent, finalizeEvent } from 'nostr-tools/pure'
import { hexToBytes } from '@noble/hashes/utils'
let raw = ''
for await (const chunk of process.stdin) raw += chunk
const input = JSON.parse(raw)
const out = {
  python: input.python.map(ev => ({ id: getEventHash(ev), ok: verifyEvent({ ...ev }) })),
  signed: input.sign.map(t => finalizeEvent({ kind: t.kind, created_at: t.created_at, tags: t.tags || [], content: t.content }, hexToBytes(t.sk))),
}
process.stdout.write(JSON.stringify(out))
