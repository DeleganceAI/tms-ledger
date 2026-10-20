# Example — A Finding Corrected by New Evidence

This fictional story illustrates the [MCP interface](V1.md). [db/init.sql](db/init.sql) defines storage. IDs below are readable stand-ins for server-issued IDs.

An agent and a human register through `add_author` as `a1` (`agent`) and `a2` (`human`). These are operational identities, not verified logins. Working in the collection `tesseralia`, the agent uses `add_source` and `add_observation` to preserve a news article and a company statement, then `add_claim` to record **c1: “Tesseralia reduced its workforce by 15% in September”** and **c2: “Tesseralia laid off no permanent employees in September.”** It appends evidence citing each original observation, quoting the relevant passage verbatim. Every source, observation, claim and evidence write supplies `author_id`; the database records `asserted_at`.

## 1. Record the suspected contradiction

The agent interprets “workforce” as permanent employees and calls `add_contradiction`:

```json
{
  "collection": "tesseralia",
  "author_id": "a1",
  "claim_ids": ["c1", "c2"],
  "reason": "If workforce means permanent employees, a 15% reduction conflicts with the statement that no permanent employees were laid off in the same month."
}
```

The returned finding `k1` and its complete membership are written atomically. At least two distinct claims are required; membership cannot later be edited. This records the agent's incompatibility argument, not a server determination that the claims conflict.

## 2. Add a new observation and explain its bearing

The human finds a staffing memo stating that only contractor engagements ended and permanent headcount was unchanged. They register its source and use `add_observation` with `author_id: "a2"` to preserve the memo as `o3`. Follow-up research succeeds by adding this new, related observation, regardless of any later conclusion.

After inspecting the memo, the agent makes two `add_evidence` calls:

```json
{
  "author_id": "a1",
  "from_observation_id": "o3",
  "target_kind": "claim",
  "target_id": "c2",
  "relation": "SUPPORTS",
  "quote": "Permanent headcount is unchanged; the engagements that ended in September were all contractor engagements.",
  "reason": "The memo states that permanent headcount was unchanged and that all ended engagements were contractors."
}
```

```json
{
  "author_id": "a1",
  "from_observation_id": "o3",
  "target_kind": "contradiction",
  "target_id": "k1",
  "relation": "REBUTS",
  "quote": "the engagements that ended in September were all contractor engagements",
  "reason": "The memo distinguishes contractors from permanent employees, challenging the finding's assumption that the two claims describe the same group."
}
```

Both evidence records receive IDs and database timestamps. Had either quote not occurred in the memo, the server would have refused the write. Neither record disables the finding or alters its claims; evidence about one target does not automatically propagate to another.

## 3. Read the trail and draw a conclusion

A briefing agent calls `search_contradictions` for `k1`, `get_record` for each member claim, and `get_evidence` with `target_kind`/`target_id` for the finding and each claim. It follows `from_observation_id` through `get_record`, and reads sources and authors as needed. These calls return raw stored records, quotes, reasons, links, author IDs and timestamps—not an evaluated status.

The briefing agent builds a thinking proof, checks it with `check_proof`, and concludes: **“The apparent contradiction seems to rest on conflating contractors with permanent employees; the memo gives grounds to regard this finding as mistaken.”**

```json
{"question": "Did Tesseralia lay off permanent employees in September?",
 "steps": [
  {"id": "s1", "say": "A finding treats the two claims as incompatible.", "from": ["k1"]},
  {"id": "s2", "say": "The memo separates contractors from permanent headcount and rebuts the finding.", "from": ["o3", "e_memo_rebuts_k1"]},
  {"id": "root", "say": "On my reading the finding is mistaken: both claims can hold.", "from": ["s1", "s2"]}
 ]}
```

That conclusion is explicitly the downstream agent's interpretation, not a server verdict. Another reader can disagree using the same preserved records and the saved proof.

The retrieved links provide an evidence trail, not a stored explanation of why the human commissioned the research. There is no automatic resolution or claim-status change.
