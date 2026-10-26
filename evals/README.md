# Murdle-style eval

This measures how an agent does on deductive grid puzzles (who, with what, where) when the clues live in a [tms](../README.md) collection, and how the same agent does when those clues are only in the prompt.

A puzzle is a Latin grid. Every category has the same number of entities, one entity from each category sits in each row, and each entity is used once. An ordered category (house, seat, time) is the row axis, which is what "immediately left of" means. The scorer lines predicted rows up on that axis.

Nothing here changes the server, the schema, or the MCP tools.

## What is in v0 and v1

v0 is three hand-written puzzles with known answers:

| id | grid | what it is |
|---|---|---|
| `zebra` | 6 by 5 | The folk five-house riddle (who drinks water, who owns the zebra), restated. Memorization risk is high. |
| `terrace` | 3 by 3 | Original. Small enough to check by hand. |
| `gallery` | 4 by 4 | Original Murdle-shaped puzzle: four people, rooms, objects, and times. |

`zebra` uses the familiar constraints and new sentences. It is not the 1962 magazine text, and it is not a Murdle. Published Murdle books are copyrighted; none of that text is in this tree.

v1 is `evals/murdle/generate.py`. It draws a completed grid from a seed, emits only clues that are true of that grid, and keeps a subset the solver can prove is the only solution. Parameters:

- `dimensions` and `entities` (2 to 12 categories, 2 to 80 entities)
- `clues`, a target count. Uniqueness wins if the target is too small or too large to certify.
- `clue_types`: `direct`, `negative`, `relational`, `red_herring`

When `relational` is included, one dimension is an ordered `house` axis. A red herring is a true clue the uniqueness proof does not need, written in the same shape as the others, or (in the hand-written puzzles) a flavor sentence that is not a grid fact. Red herrings are never false. An agent that treats every sentence as a constraint is not punished with a contradiction.

The solver is forward checking plus backtracking. It stops at two solutions. "Unique" means one solution and a finished search. Grids past 80 entities are rejected: past that, the search stops being a check. Direct clues still pin a 20 by 4 grid immediately, which is already far past what a person can hold in their head, so a scale sweep can look for the size where a model stops.

## How a run uses tms

In tms mode the harness stores each clue as a kind 4701 evidence event in an in-memory collection. The events are signed and verified with `tms.events`. A link is accepted only when its quote survives the same folding as `normalize_quote` in `db/init.sql` (case, whitespace, curly quotes, dashes, soft hyphens, fi/fl ligatures) and still occurs in that evidence. A bad event rolls the batch back. `check_proof` applies the same three rules as the server: citations resolve, there is one root, and every step has a ledger event in its ancestry or is marked `gap`.

The collection is not Postgres. It does not check terms, approval, or membership, it does not embed claims, and `search_claims(method="vector")` falls back to keyword overlap and says so. Tool arguments are already scoped to the puzzle, so the agent does not send `collection` or a signed kind 4707 request. `publish_claim`, `publish_link`, and `publish_contradiction` sign kind 4702–4704 events with an ephemeral key on the agent's behalf. A stricter harness could make the model return content and sign outside the tool. The bytes are the same shape the server stores.

Baseline mode puts the same clue sentences in the prompt and offers no ledger tools. The comparison is then answer accuracy against trail: claims, verbatim links, contradictions, proof check, steps, and tokens.

## Agents

| name | credentials | what it does |
|---|---|---|
| `reference` | none | Oracle. Solves from the formal clues (not the answer key) and, in tms mode, writes claims, verbatim links, one contradiction when a clue is negative, and a checked proof. This is the offline stand-in. It is not a subject. |
| `mock` | none | Same solver, writes nothing. Useful as a "correct answer, empty trail" control. |
| `openai` | a key and a model name | Tool-calling chat model. In tms mode the prompt does not contain the clues. |

`openai` reads, in order, `TMS_EVAL_API_KEY` or `OPENAI_API_KEY` or `CHAT_API_KEY`, and `TMS_EVAL_MODEL` or `CHAT_MODEL`. The URL is `TMS_EVAL_BASE_URL` or `OPENAI_BASE_URL` or `CHAT_URL`, otherwise `https://api.openai.com/v1`. That value is the prefix in front of `/chat/completions` (the same shape as `CHAT_URL` in the server). No key is written to disk. Without a key the command exits before any puzzle runs. `--max-steps` caps model rounds (default 24).

Claim text the scorer understands is one tab-separated line:

```text
PAIR<TAB>category<TAB>entity<TAB>category<TAB>entity
NOT<TAB>category<TAB>entity<TAB>category<TAB>entity
REL<TAB>category<TAB>entity<TAB>relation<TAB>category<TAB>entity
```

Relations: `immediately_left_of`, `immediately_right_of`, `next_to`, `left_of`, `right_of`.

## Run

From the repo root, after `uv sync`:

```bash
uv run python -m evals.murdle list
uv run python -m evals.murdle solve --puzzle zebra
uv run python -m evals.murdle run --puzzle terrace --agent reference
uv run python -m evals.murdle run --all --agent mock --json
uv run python -m evals.murdle generate --dimensions 4 --entities 5 --clues 18 --seed 1 --out evals/runs/sample.json
uv run python -m evals.murdle run --file evals/runs/sample.json --agent reference --strict
uv run python -m evals.murdle scale --entities 3,4,5 --dimensions 3 --seeds 0 --agent reference
```

`--strict` exits 1 unless every mode solved the grid and reported no error. One puzzle's `--json` output is an object; more than one is a list. `scale` prints accuracy, steps, tokens, seconds, links, and valid contradictions at each size. `generate` writes the answer key into the JSON. Do not hand that file to a model as its prompt. `run --file` strips the key before the agent sees the task.

A model sweep:

```bash
TMS_EVAL_API_KEY=... TMS_EVAL_MODEL=... TMS_EVAL_BASE_URL=https://api.deepinfra.com/v1/openai \
  uv run python -m evals.murdle run --puzzle terrace --agent openai --max-steps 30 --strict
```

Generated puzzles are the control for memorization. `zebra` is flagged `memorization_risk=high` in the report; generated puzzles are `low`.

## Score

`accuracy` is the fraction of non-anchor cells that match. `exact_match` is the whole grid. `answer_accuracy` is the asked questions (`water` and `zebra` on the five-house puzzle, for example). `solved` means both the grid and the questions are right.

In tms mode `trail_score` is the mean of:

- link integrity: accepted links divided by accepted plus rejected quotes
- pair recall: gold pairs mentioned by a true `PAIR` claim
- 1 if `check_proof` passed, else 0
- the fraction of false claims that sit in a contradiction or are the target of a `REBUTS` link (1 when there is no false claim)

A contradiction counts as valid when the claims it names cannot all be true (`PAIR` against `NOT` of the same pair, or two `PAIR`s that give one entity two partners in one category). A contradiction whose claims are all true of the answer key is spurious. Baseline `trail_score` is null.

`steps` is agent actions (tool calls for `reference`, model rounds for `openai`). `tokens` is 0 unless a model reported usage.

## Tests

```bash
uv run python -m evals.test_murdle
```

That covers the quote folding, the three hand-written grids, generator determinism, uniqueness with and without red herrings, direct / negative / relational clue sets, a 20 by 4 grid, rejected paraphrases, batch rollback, `check_proof`, both harness modes, and the CLI. No network and no database.

`uv run python test_events.py` and `uv run python test_smoke.py` are unchanged. The smoke test still needs Postgres.

## Open questions

- v0's zebra constraints are widely memorized. The report flags that. Generated puzzles are the comparison that does not leak through training data, as long as we do not publish the answer key beside the clues the model sees.
- Which models, and what step or dollar budget, is still a product choice. The harness records tokens and seconds and stops an `openai` run at `--max-steps`. It does not enforce a price cap.
- Eval runs are JSON files (`--out`, gitignored under `evals/runs/`). They are not written into a tms collection. Doing that needs an approved key, a signed terms event, and embeddings, and it would mix eval traffic with research collections. The in-memory events are already signed, so a later `--publish` flag can submit the same batch without a server change.
- The eval signs tool writes itself. A model that must call `tms-sign` (or return unsigned content for the harness to sign) would be a stricter test of the real MCP loop, including kind 4707 requests.
- Keyword search is not the server's vector search. A run against a real collection would also need `DATABASE_URL` and an embeddings endpoint. That path is not wired, on purpose: CI has neither.
