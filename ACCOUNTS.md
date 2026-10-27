# Accounts

**Status: steps 2 and 3 are built; the block list is not.** [EVENTS.md](EVENTS.md) section 3 is how access works today, and it stays the spec until each part below lands. [ROLES.md](ROLES.md) is about what contributors do, not what they may do, and is unchanged.

## Today

A key can use the service only if the operator approved it (`TMS_APPROVED`, or Approve in `/admin`), it is a member of a collection, or an approved key named it as a steward. Approved keys create collections without limit. Everyone else files an access request and waits.

Each key stands alone. Nothing records that a set of bot keys belongs to one person, so there is no way to say "this person and their bots" when counting, granting or removing access.

## The model

An **account** is a person and the keys that act for them:

- **The human key.** The person. They log in with a Nostr extension or by email, in which case the server holds the key and signs for them while they are logged in.
- **One Ledger key.** An agent that can do almost anything the human can, on their behalf: create collections, add and remove the account's agents, manage collection members, and choose which agents work in which collection. It cannot name a different Ledger key, remove an owner, or do anything with the human's own key.
- **Agent keys.** The account's bots. Each agent belongs to exactly one account.

### Collections

The owner of a collection adds **people**, not bots. They paste another person's npub (an email account has one too) into the member list.

Each person in a collection, owner included, chooses which of **their own** agents may work there. Creating a collection and joining one show the same checklist of the account's agents. When the owner removes a person, that person's agents lose access with them. The owner never has to handle anyone else's bot keys.

Admins, from [EVENTS.md](EVENTS.md) section 3, keep their meaning: people who may change the member list and the topic.

### Sign-up

Anyone can create an account on the Login page, with an extension or by email. The sign-up view carries a Cloudflare Turnstile check, verified on the server before the account is created. It also guards every **Email me a code**, new address or not, since every code is an email someone pays for, and checking only new addresses would tell anyone which addresses have accounts. It runs invisibly and shows a challenge only when Cloudflare asks for one. Logging back in with an extension does not run it. Agents never see it: they get access through their account.

Signing up makes a **free account** at once. There is no approval queue, so the access-request form and its admin emails go away.

### Limits

| | Free account | Approved account |
|---|---|---|
| Agent keys | 100 | Unlimited |
| Collections it owns | 1 | Unlimited |
| Evidence, claims, links and contradictions | 10,000 in total | Unlimited |

- The record limit is account-wide. A record counts against the account whose human, Ledger or agent signed it, wherever it is written, including collections the account was invited into. Profiles, terms and other bookkeeping events do not count.
- Joining someone else's collection does not use the one-collection slot.
- A key that belongs to no account but writes as a plain member of a collection counts against that collection's owner. That closes the gap of adding bots as plain members instead of as agents.
- Reaching a limit refuses the write with: *You have reached the free-account limit. Please email `<TMS_CONTACT>` to increase your limits.* The website shows it, and agents get the same text as their error so they can pass it on. `TMS_CONTACT` is an environment setting, so each ledger names its own operator.
- Approving an account in `/admin` lifts every limit for the whole account: the human, the Ledger and every agent.

## Records

Proposed kinds, numbered after the ones in use:

- **account (4713)**, no collection. Content: `{"ledger": "<hex pubkey or null>", "agents": ["<hex pubkey>", ...]}`. The latest one counts. The human signs it, or the Ledger signs it with `ledger` unchanged. The server rejects an event that names a key already claimed by another account, or the human's own key.
- **collection agents (4714)**, in a collection. Content: `{"agents": ["<hex pubkey>", ...]}`. Signed by a person in that collection, or by their Ledger. The latest one per person is the set of that person's agents that may work there. Only keys in that person's account count, and only while that person is in the collection.

The server reads these to decide access, the same way it reads `members` and `admins` today. Whether an account is free or approved is operator data, not ledger data, and lives in a table next to `approvals`.

`stewards` (4711) and `found` (4712) keep working: a Ledger key is treated as a steward of its human. Plain membership of a bot key, as most members are today, keeps working as well. It is the fallback for a key that has no account, and its writes count against the collection owner.

## Not yet

- **Blocking a bad actor.** The `events` table is append-only by trigger, and other people's links can point at a bad actor's records, so deleting them is not an option. The plan is a block list in `/admin` that hides every event an account signed and refuses its writes, and can be undone. It gets built when it is first needed. A true purge, for content that legally has to go, is a separate admin-only script for that day.
- **Document size.** Evidence has no per-document size cap. The record limit is enough while the ledger is a demo.
- **Many accounts per person.** A new key costs nothing. Turnstile, plus a limit on email codes per address and per IP, is the brake for now.

## Order of work

1. This document.
2. Sign-up and limits: Turnstile, free accounts, the limits above, and the `TMS_CONTACT` message. Until accounts exist, the record limit counts keys the way the rule for plain members does. **Built.** An extension sign-up is a row in `signups`; an email sign-up is its `email_accounts` row. The 100-agent limit waits for step 3.
3. Accounts: the two new kinds, the account and collection screens, and limits counted per account. **Built.** Account state is derived from the events by the `accounts` and `collection_agents` views. Which human a Ledger signs for comes from that human's own account events at the moment of signing (`ledger_human`), so replacing a Ledger never rewrites what the old one signed. The Ledger and the agents a person picks are members of a collection, not on its roster.
4. The block list, when needed.
