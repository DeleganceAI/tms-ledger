# Writing Claims

A claim is the record links attach evidence to and contradiction findings are built from. A good claim is one where two readers mean the same thing by it and evidence can land on it cleanly. The ledger stores claims as opaque text and enforces none of this ([DOCS.md](DOCS.md)). Contributors apply it before publishing a claim; reviewers use it to decide what links to add.

## Template

> *subject* · *relation verb* · *outcome* · *magnitude against a comparison* · *conditions* · *domain* · *time window*

Not every slot is needed. Each empty slot is a question a reviewer should ask.

Claim text is the strong form. Uncertainty does not belong in the verb; it belongs in a `QUALIFIES` link on the claim.

## Checklist

| # | Check | Test | Red flags |
|---|---|---|---|
| 1 | Rebuttable | Write one sentence describing evidence that would count against it. | Nothing comes to mind. |
| 2 | Not trivially true | Write the negation. An informed person could hold it. | "can", "may", "might", "could", "is possible" |
| 3 | One proposition | Evidence supports the whole sentence or none of it. | "and", commas, lists |
| 4 | Concrete terms | Each noun names something identifiable or measurable. | "exposure", "impact", "performance" with no referent |
| 5 | Scoped | Who or what, where, when, under what conditions. | No timeframe, no population |
| 6 | Direction and size | Increases or decreases, by how much, compared with what. | "affects", "changes", "differs" |
| 7 | Relation named | When two things are related: causes, is associated with, precedes, predicts. A plain event has no relation to name. | "linked to", "related to" |
| 8 | About the world | True or false regardless of who said it. | "the paper finds", "according to", "X argues" |
| 9 | Contestable | Someone would bet against it, or act differently if it were false. | Definitions, how-to statements |
| 10 | Right size | Several independent sources could bear on this exact sentence. | Too broad to settle, or a single datum (that is an observation) |
| 11 | Not normative | An observation could rebut it. | "should", "good", "important" |

Checks 1 and 2 do most of the work. A claim that fails them is either not a claim or a definition.

## From draft to claim

Drafts an agent actually proposed, and where each one fails. The rewrites are the numbered claims in the next section.

| Draft | Problem | Rewrite |
|---|---|---|
| Foreign investors can sell dollar exposure through hedging while keeping their US securities. | Vague (4), "can" (2): nobody disputes that forwards exist. The precise version is compound (3), so it becomes two claims. | Claims 2 and 3 |
| Quantizations with similar average accuracy can behave differently over multi-step agent tasks. | "can behave differently" (2, 6): any two things can. | Claim 4 |
| Diet can alter histamine produced inside the gut, separately from the histamine eaten. | "can" (2); "alter" has no direction (6); "histamine produced inside the gut" has no measurement (4). | Claim 5 |
| Anticipatory preparation can reach a point where its costs exceed the failures it avoids. | "can" (2); no domain or threshold (5): every cost curve crosses somewhere. | Claim 6 |

## Claims that pass

Nothing here is asserted; the claims illustrate form. Each carries the rebuttal line an agent should emit, then the checklist applied.

### 1. Tesseralia

**Tesseralia reduced its workforce by 15% in September 2026.**

Would be rebutted by: headcount or payroll figures for August and October 2026 showing a smaller cut or none.

This is the first claim in [EXAMPLES.md](EXAMPLES.md), with a year added. Its partner there, that no permanent employees were laid off in September, passes the same way, and the contradiction between them turned on scope: contractors versus permanent staff.

| # | Check | How it passes |
|---|---|---|
| 1 | Rebuttable | Headcount before and after September settles it. |
| 2 | Not trivially true | "Tesseralia did not cut 15% in September" is a position a reporter could hold. |
| 3 | One proposition | One company, one cut, one month. |
| 4 | Concrete terms | A named company, a percentage, a month. |
| 5 | Scoped | September 2026. |
| 6 | Direction and size | Reduced, by 15%, against the August headcount. |
| 7 | Relation named | A plain event; nothing to name. |
| 8 | About the world | True or false whatever the news article said. |
| 9 | Contestable | The company's own statement denies it. |
| 10 | Right size | Filings, payroll data, press reports and employee accounts all bear on it. |
| 11 | Not normative | Says nothing about whether the cut was right. |

### 2. Hedge ratios

**Between January and September 2025, Danish and Dutch pension funds raised their dollar hedge ratios on US equity holdings.**

Would be rebutted by: the funds' quarterly disclosures showing flat or falling hedge ratios over the period.

| # | Check | How it passes |
|---|---|---|
| 1 | Rebuttable | Disclosed hedge ratios at the two dates settle it. |
| 2 | Not trivially true | "Hedge ratios were unchanged" is a position a fund analyst could hold. |
| 3 | One proposition | One population, one variable, one direction. Whether the hedging moved the dollar is claim 3. |
| 4 | Concrete terms | Named funds, a ratio they publish, a named asset class. |
| 5 | Scoped | Danish and Dutch pension funds, January to September 2025. |
| 6 | Direction and size | Raised, against the January level. Size is open; a `QUALIFIES` link can narrow it. |
| 7 | Relation named | A plain change; nothing to name. |
| 8 | About the world | True or false whatever the article that prompted it said. |
| 9 | Contestable | Dollar-flow analysts would change their models if it were false. |
| 10 | Right size | Each fund's disclosures, central bank surveys and dealer data all bear on it. |
| 11 | Not normative | No "should". |

### 3. Hedging versus selling

**In the first half of 2025, currency hedging by foreign holders of US securities moved the dollar more than their net sales of those securities did.**

Would be rebutted by: a flow decomposition attributing most of the dollar's move to outright sales.

| # | Check | How it passes |
|---|---|---|
| 1 | Rebuttable | A decomposition of flows settles it either way. |
| 2 | Not trivially true | "Sales mattered more than hedging" is the mainstream prior. |
| 3 | One proposition | One comparison between two flows. |
| 4 | Concrete terms | Hedging flow, net sales and the dollar's move each have published measures. |
| 5 | Scoped | Foreign holders of US securities, first half of 2025. |
| 6 | Direction and size | More than, against net sales. |
| 7 | Relation named | Causal: "moved". |
| 8 | About the world | About flows, not about what any analyst wrote. |
| 9 | Contestable | A central bank would read dollar weakness differently if hedging rather than selling drove it. |
| 10 | Right size | Treasury flow data, BIS surveys and bank flow research all bear on it. |
| 11 | Not normative | No "should". |

### 4. Quantization

**4-bit weight-only quantization of Llama-3.1-70B-Instruct loses more accuracy on τ-bench than on MMLU, relative to the bf16 checkpoint.**

Would be rebutted by: an evaluation where the τ-bench drop is equal to or smaller than the MMLU drop.

| # | Check | How it passes |
|---|---|---|
| 1 | Rebuttable | Two benchmark runs settle it. |
| 2 | Not trivially true | "Quantization degrades benchmarks evenly" is a position many practitioners hold. |
| 3 | One proposition | One model, one quantization, one comparison. |
| 4 | Concrete terms | A named checkpoint, a named quantization scheme, two named benchmarks. |
| 5 | Scoped | That model, that scheme, those benchmarks. |
| 6 | Direction and size | Loses more, measured as the gap to bf16 on each benchmark. |
| 7 | Relation named | Causal: quantization causes the loss. |
| 8 | About the world | Reproducible by anyone with the weights. |
| 9 | Contestable | Teams deploying quantized agents would change their evaluation if it were true. |
| 10 | Right size | Any lab can run it; several independent runs could bear on it. |
| 11 | Not normative | No "should". |

### 5. Gut histamine

**In adults on a low-histamine diet, four weeks of increased fermentable fiber intake raises fecal histamine concentration.**

Would be rebutted by: a controlled feeding study showing no change or a decrease.

| # | Check | How it passes |
|---|---|---|
| 1 | Rebuttable | A feeding study with fecal sampling settles it. |
| 2 | Not trivially true | "No effect" is a position a gastroenterologist could hold. |
| 3 | One proposition | One intervention, one outcome. |
| 4 | Concrete terms | Fermentable fiber and fecal histamine are both measurable; the draft's "histamine produced inside the gut" was not. |
| 5 | Scoped | Adults on a low-histamine diet, four weeks. |
| 6 | Direction and size | Raises, against the same people before the change. |
| 7 | Relation named | Causal, since it is an intervention claim. |
| 8 | About the world | Nothing about a paper. |
| 9 | Contestable | Low-histamine diet guidance would change if it were true. |
| 10 | Right size | Several feeding studies could each bear on it. |
| 11 | Not normative | Nothing about what anyone should eat. |

### 6. Preparedness spending

**For hurricane-prone US counties, preparedness spending above the FEMA-recommended level avoids less than one dollar of storm damage per dollar spent.**

Would be rebutted by: cost-benefit studies showing avoided damage above one dollar per dollar at those spending levels.

| # | Check | How it passes |
|---|---|---|
| 1 | Rebuttable | Cost-benefit studies at those levels settle it. |
| 2 | Not trivially true | "Preparedness pays for itself at any level" is a common position. |
| 3 | One proposition | One ratio, one threshold. |
| 4 | Concrete terms | A named spending threshold, a dollar ratio. |
| 5 | Scoped | Hurricane-prone US counties, spending above the FEMA level. |
| 6 | Direction and size | Less than one dollar per dollar; the comparison is break-even. |
| 7 | Relation named | Causal: spending avoids damage. |
| 8 | About the world | About outcomes, not about what any agency recommends. |
| 9 | Contestable | County budgets would change if it were true. |
| 10 | Right size | Multiple county-level studies could bear on it. |
| 11 | Not normative | Says what the ratio is, not what counties should spend. |

## For agents proposing claims

Emit, beside every candidate, one line: **would be rebutted by:** … as in the examples above. A candidate with nothing to put there is dropped. This one habit catches most failures of checks 1, 2 and 9.

## Not enforced

The schema stays opaque text with no server verdicts. If claim quality slips, the next step is a warning at the API edge for modals, conjunctions and source phrases, or a judge that returns this checklist as a struct. Neither exists yet.
