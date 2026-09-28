# Question-Value Feature Attribution

**Read-only.** Nothing under `rag/` is modified; no multiplier, threshold, window, `top_n`, merge,
fusion, selection or planner rule is changed; no filtering rule and no new value class is introduced;
Top-30, 0.55 and `top_n` are untouched; P1-2 stays PAUSED. The counterfactuals call the **real**
`apply_rank_adjustments` and `select_context` on deep copies of a real pool with a policy whose
`question_values` differ — a diagnostic re-evaluation whose output never re-enters the pipeline.

Nine questions traced: the composite incident question, the four stage-two table controls, and four
extra shapes (model number, genuine technical value, multi-value comparison, year only).

---

## 1. `QUESTION_VALUES_SOURCE`

### The derivation, stage by stage (composite question)

```
question       根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，…各是多少？
strip_section_references()   removes 第N章/附录/… — "标准表 1" is not a section word, so "1" survives
_QUESTION_NUMBER_RE  \d+(?:[.．]\d+)?  matches:  ["73286.2", "2026", "73286.3", "2026", "1"]
digit filter  len(digits) < 2 and "." not in token  ->  "1" DROPPED (short)
dedupe        ->  the second "2026" DROPPED (duplicate)
_pool_share() <= MAX_VALUE_POOL_SHARE (0.80)  ->  nothing dropped here
final        ['73286.2', '2026', '73286.3']      (order: as the question names them, then MAX 6)
```

### Why each token is a "value"

| token | survives on | real pool share | carried by | class |
| --- | --- | --- | --- | --- |
| `73286.2` | 7 digits, so the length filter passes; share **0.4138** < 0.80 | 24 / 58 chunks | 第2部分 rows | **standard part designation** |
| `2026` | 4 digits, so the length filter passes; share **0.2931** < 0.80 | 17 / 58 chunks | body text naming the year | **standard year** |
| `73286.3` | 7 digits (decimal present); share **0.3276** < 0.80 | 19 / 58 chunks | 第3部分 rows | **standard part designation** |

**`2026` is a value because it is rare, and it is rare because the ingest writes the designation
without its year** (`[标准号: Q/GDW 73286.3 | 文档: …]`). Its scarcity is a property of document
identity, not of answer-bearingness — and scarcity is the only test the filter applies.

### `INTENDED_SEMANTICS`

From `question_values`' own contract: *"The literal figures a question asks about … These are the one
class of term a passage can be checked against without a model: **the answer either writes the figure
the question named or it does not**."* Its worked example is `800 mm² / 1200 mm²`. And the share filter
states its intent explicitly: *"A figure is only worth matching when the pool does NOT already carry it
everywhere. `220kV` is named by most passages of a 220kV corpus, so matching on it would move every
candidate by the same factor — noise dressed as a signal."*

**Intended class: answer-bearing measurement values that discriminate between candidate passages.**

### Is there any type distinction today? **No.**

One regex, one length filter, one frequency filter. Standard designations, years, model-number
fragments and technical parameter values are one undifferentiated class:

| question shape | extracted as "the question's figures" | what they actually are |
| --- | --- | --- |
| standard number + year | `73286.2`, `73286.3`, `2026` | document identity |
| cable model number | `0.6`, `25` (from `WDZC-YJY-0.6/1kV`, `3×25`) | model-number fragments |
| genuine technical value (`800 mm²`) | **`[]`** — `800` dropped, share 0.95 | answer-bearing value |
| multi-value comparison (`800`, `1200`) | **`[]`** — both dropped, share 0.8333 | answer-bearing values |

---

## 2. `CONSUMER_RULES`

Every consumer of `question_values` in the codebase (verified by grep over `rag/`), with its
**measured** effect on the composite question's real pool:

| # | consumer | input | predicate | multiplier / effect | affected chunks (measured) |
| --- | --- | --- | --- | --- | --- |
| 1 | `apply_rank_adjustments` (rerank.py:316) | `policy.question_values` | `paired_values(chunk, values)` — the value appears **and** a result figure sits within ±20 chars | `boost *= VALUE_PAIRING_BOOST (1.3)` | **3 chunks, all prose**: `66f462a9de91e03c` (.2285), `bc2a6dfa54206eab` (.2218), `0b4e3c1a73c1e334` (.2106) |
| 2 | `apply_rank_adjustments` (rerank.py:318) | same | `is_table and carries_value(chunk, values)` **and not** paired | `penalty *= VALUE_LIST_PENALTY (0.8)` | **22 chunks — every table in the pool** |
| 3 | `select_context` step 1b (rerank.py:520) | same | `candidates = [c for c in candidates if paired_values(c, values)] or candidates` | changes **which** passage holds a compared-document reserved slot | 0 chunks here (no paired chunk in either compared document) |
| 4 | `_warn_when_a_value_passage_was_cut` (rerank.py:629) | same | `paired_values(chunk, values)` | **log line only** — no ranking effect | diagnostic: emitted the "the cut dropped result-bearing passage(s) … the question names 2026, 73286.2, 73286.3" warning |
| — | `_pool_share` (decomposition.py:239) | candidate token | `carries_value(chunk, (value,))` | extraction-time filter, not a ranking rule | selects the value set itself |

**Two measured consequences that matter more than the ranks:**

* **Rule 2 is uniformly applied, so it discriminates nothing.** It fires on **22 of 22 tables**,
  because every table carries the standard designation in the ingest-written header. Its intent is to
  separate a table that *merely lists* the question's figures from one that *pairs* them; here it is a
  flat ×0.8 on the entire type.
* **Rule 1 fires only on prose, and only through an identity token.** All three boosted chunks pair
  **`2026`**, and all three are exactly the lower-score prose passages that overtook the target in
  stage two. So the pairing boost's entire measurable effect on this question is to promote prose by
  30 % on the strength of the document's year.

---

## 3. `COUNTERFACTUAL_WITHOUT_IDENTITY_VALUES`

Computed in the tracer through the real ordering and the real cut, never in the pipeline.
`pure_by_similarity_target_rank = 28`, `pure_by_similarity_top12_tables = 6` for reference.

| variant | value set | target rank | target `rank_score` | target chosen | **overtakers** | tables in ordered top-12 | tables chosen | prose chosen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A** current | `2026, 73286.2, 73286.3` | **45** | 0.237138 | no | **17** | 0 | 0 | 12 |
| **B** without year | `73286.2, 73286.3` | **45** | 0.237138 | no | 17 | 0 | 0 | 12 |
| **C** technical only | `[]` | **35** | **0.296423** | no | **7** | **1** | 0 | 12 |
| **D** classes separated (identity excluded) | `[]` | 35 | 0.296423 | no | 7 | 1 | 0 | 12 |
| **E** no values at all | `[]` | 35 | 0.296423 | no | 7 | 1 | 0 | 12 |

Readings:

* **Removing the year changes nothing at all** — identical rank, score and overtaker count. `2026` is
  not the token that costs the target; it is the token that *promotes three prose passages above it*.
* **Removing the identity values recovers 10 places** (45 → 35) and the score rises from `0.237138` to
  **`0.296423`** — exactly `0.303246 × TABLE_PENALTY(0.85) × CORE_DOCUMENT_BOOST(1.15)`, i.e. the
  `VALUE_LIST_PENALTY` 0.8 no longer applies. **Overtakers fall from 17 to 7.**
* **One table enters the ordered top-12** (0 → 1). The six tables a pure-similarity top-12 would seat
  are cut to one by `TABLE_PENALTY` alone once the value penalty is gone.
* **The target is still not chosen, and chosen tables stay 0** in every variant: the cut defers tables
  behind prose regardless of ordering, so no value-set change seats it.
* **C = D = E for this question** because the technical class is empty here — all three tokens are
  identity. Separating the classes therefore has no effect on this question, and the honest reading is
  that D's value is a correctness argument, not a recovery mechanism.

### `OVERTAKERS_REMOVED`

**10 of 17.** Overtakers = (chunks ahead of the target after adjustment) − (chunks ahead of it by raw
similarity). Removing the identity values takes that from **17 → 7**; removing the year alone removes
**0**. The ten removed are the ones whose advantage came from the `×1.3` pairing boost on `2026` and
from the target's `×0.8` value-list penalty.

---

## 4. `CONTROL_QUERY_EFFECT`

| query | shape | extracted values | classes | rule 1 fires on | rule 2 fires on | tables in pool / chosen |
| --- | --- | --- | --- | --- | --- | --- |
| INCIDENT_COMPOSITE | std + year, composite | `2026, 73286.2, 73286.3` | 3 identity | 3 prose | **22 (all)** | 22 / **0** |
| TABLE_SINGLE_PART2 | std + year | `2026, 73286.2` | 2 identity | 0 | 10 tables | 10 / 5 |
| TABLE_THREE_PART3 | std + year | `2026, 73286.3` | 2 identity | 0 | 11 tables | 12 / 4 |
| TABLE_STRUCTURE | no numbers (`220` dropped, share 1.0) | `[]` | — | 0 | 0 | 11 / 5 |
| TABLE_VALUE_LOOKUP | std + year + `800 mm²` | `2026, 73286.2` — **`800` dropped (share 0.95)** | 2 identity | 0 | 13 tables | 20 / 12 |
| SHAPE_MODEL_NUMBER | cable model number | `0.6, 25` | 2 technical (fragments) | **1 — a TABLE with similarity 0.0836** | 8 tables | 10 / 5 |
| SHAPE_TECHNICAL_VALUE | genuine technical value | **`[]`** — `800` dropped (share 0.95) | — | 0 | 0 | 20 / 12 |
| SHAPE_MULTI_VALUE | multi-value comparison | **`[]`** — `800`, `1200` dropped (share 0.8333) | — | 0 | 0 | 20 / 12 |
| SHAPE_YEAR_ONLY | year only | `2026` | 1 identity | 3 prose | 2 tables | 10 / 5 |

**The conflation is systematic, and it has two directions:**

1. **Identity tokens are admitted and act as spurious signals.** `73286.2`/`73286.3`/`2026` pass
   because they are rare in the pool, and rarity is exactly what document identity produces. The
   measured damage: rule 2 becomes a flat ×0.8 on 100 % of tables (non-discriminating), and rule 1
   promotes prose on the standard's year.
2. **Answer-bearing technical values are rejected.** On this corpus `800`, `1200` and `220` are
   carried by 83–100 % of the window, so `_pool_share ≤ 0.8` discards them — the feature is **inert
   exactly where it was designed to work** (`SHAPE_TECHNICAL_VALUE`, `SHAPE_MULTI_VALUE`: empty value
   sets, zero effects). A question carrying *both* kinds (`TABLE_VALUE_LOOKUP`) ends up identity-only.
3. **Model-number fragments are admitted and boost a bad passage.** `0.6` (from `WDZC-YJY-0.6/1kV`,
   pool share **0.0**) triggers the pairing boost on a table of similarity **0.0836** — the
   lowest-scoring table in that pool is raised by 30 % over its peers.

So the frequency proxy is **anti-correlated with the intent on a single-standard corpus**: the
answer-bearing figures are ubiquitous (a 220kV cable corpus's tables all list the 800/1200 mm² series)
while the identity tokens are rare by construction.

---

## 5. `CAUSAL_VERDICT`

**A — `question_values` extraction/classification defect.** Two sub-defects in one layer:

* **A1 — no type distinction.** Document-identity values (standard part number, standard year,
  model-number fragments) and answer-bearing technical values are one class, decided by one regex and
  one length filter.
* **A2 — the discrimination proxy selects the wrong way.** `_pool_share ≤ 0.80` was designed to drop
  figures "the pool already carries everywhere"; on this corpus it drops the technical values (0.83–1.0)
  and keeps the identity tokens (0.29–0.41), inverting its own stated intent.

Consumers are **not** defective: rules 1 and 2 implement exactly what they claim (boost a passage that
pairs the question's figures with results; demote a table that only lists them) at the declared
multipliers, and rule 3 and 4 are a reservation and a log line. They are simply handed the wrong
figures.

**One secondary note inside the same feature, not a separate verdict:** rule 2's predicate reads
`_values_text(chunk) = _plain(_content(chunk))`, which **includes the ingest-written identity header**
(`[标准号: Q/GDW 73286.3 | …]`). That is why "carries a value" is true for every table and the rule
loses its discriminating power. It is a text-scope question at the input/predicate boundary; it does
not make the rule wrong as designed, but it is the narrowest place a fix could act.

**Not C:** the penalty does not fall on this question because it "naturally" deserves one — it falls on
a token that cannot serve as an answer check.
**Not D:** extraction and both predicates are pure text and arithmetic; the dense leg never touches
them, so the conflation persists unchanged on the healthy path. Only the *ranks and seats* reported
here are degraded-mode numbers.

---

## Outputs

### `QUESTION_VALUES_SOURCE`

`_QUESTION_NUMBER_RE = \d+(?:[.．]\d+)?` over `strip_section_references(question)` →
length filter (`len(digits) < 2 and "." not in token`) → dedupe → `_pool_share(value, pool) <= 0.80` →
`found[:MAX_QUESTION_VALUES]`. For the composite question: matches
`["73286.2","2026","73286.3","2026","1"]`, `"1"` dropped as short, the second `2026` dropped as a
duplicate, shares 0.4138 / 0.2931 / 0.3276 all below 0.80, final
`['73286.2','2026','73286.3']`. Consumers: `apply_rank_adjustments` (rules 1, 2),
`select_context` step 1b (rule 3), `_warn_when_a_value_passage_was_cut` (rule 4, log only).

### `INTENDED_SEMANTICS`

Answer-bearing, discriminating measurement values — figures the *answer* must contain, whose presence
separates the passage that answers from passages that merely repeat the question's words. Its own
docstring and the share filter's rationale both say so; the worked example is `800 mm² / 1200 mm²`.

### `IDENTITY_VALUE_CONFLATION`

**YES, systematic, in both directions.** Standard part numbers, the standard year and model-number
fragments are admitted as values (they pass because document identity is rare in the pool), while
genuine technical values (`800`, `1200`, `220`) are rejected as "carried everywhere". Every table then
carries an identity token in its ingest header, so the list penalty becomes uniform, and the pairing
boost fires on prose that places the standard's year beside a number.

### `CONSUMER_RULES`

Four consumers, one of them log-only. `apply_rank_adjustments` → `paired_values` → `×1.3` (fires on
**3 prose** chunks, all pairing `2026`, all three being overtakers) and
`is_table ∧ carries_value ∧ ¬paired` → `×0.8` (fires on **22 of 22 tables** — non-discriminating);
`select_context` step 1b → `candidates = paired or candidates` (chooses which passage takes a
compared-document reserved slot; 0 chunks here); `_warn_when_a_value_passage_was_cut` → log line only.

### `TARGET_CURRENT_ADJUSTMENT`

`similarity 0.30324606239931556 × TABLE_PENALTY(0.85) × VALUE_LIST_PENALTY(0.80) ×
CORE_DOCUMENT_BOOST(1.15) = 0.23713842079626477`; rank **28 → 45**. The value rules contribute the
`0.80` factor; the total multiplier is `0.782`.

### `COUNTERFACTUAL_WITHOUT_IDENTITY_VALUES`

Target rank **45 → 35**, `rank_score` `0.237138 → 0.296423` (exactly the value penalty removed),
overtakers **17 → 7**, tables in the ordered top-12 **0 → 1**, tables chosen **0 → 0**, target chosen
**no → no**. Dropping only the year: no change whatsoever. C, D and E coincide because this question's
technical class is empty.

### `OVERTAKERS_REMOVED`

**10 of 17** (17 → 7). Removing the year alone removes **0**. The ten are those whose advantage came
from the `×1.3` pairing boost on `2026` and from the target's `×0.8` list penalty.

### `CONTROL_QUERY_EFFECT`

Table-fact controls behave correctly and are *insensitive* to the defect in the outcome: they still
seat 5, 4, 5 and 12 tables of 12, because their questions do not enter the clause-intent branch, so
`table_cap = top_n` and the cut is a plain top-N. The value rules nevertheless fire on them — 10, 11
and 13 tables penalised, and on `TABLE_THREE_PART3` **the target itself is penalised ×0.8** yet still
seated at rank 6. This is the clean demonstration that the value rules move **ranks**, while the
**seat** is decided by the cut policy. On the two queries carrying genuine technical values the value
set is **empty**, so the feature is inert.

### `CAUSAL_VERDICT`

**A** — extraction/classification defect (A1 no type distinction, A2 an inverted discrimination
proxy), with a secondary text-scope note on rule 2's predicate (it reads the ingest-written identity
header as content). Consumers are not defective. Not C. Not D — the defect is leg-independent, though
every rank reported here is a degraded-mode number.

### `FIX_REQUIRED_OR_NOT`

**Required for the feature's own correctness; not sufficient to recover this chunk.**

* Required: three demonstrable wrong outcomes — a penalty applied uniformly to 100 % of tables (so it
  discriminates nothing), a `×1.3` boost on the standard's year that promotes three low-score prose
  passages above a higher-score table, and a `×1.3` boost on a similarity-0.0836 table driven by the
  `0.6` of a cable model number — plus complete inertness on the questions the feature exists for.
* Not sufficient: with the identity values removed the target still ends at rank 35 and is still not
  chosen, and tables chosen remain **0**. The seat is lost to the clause-intent cut, not to the value
  input.

### `MINIMAL_FIX_LAYER`

**The extraction layer** — `decomposition.question_values`: separate document-identity tokens
(standard part designation, 4-digit year, model-number fragments) from answer-bearing technical values,
and stop letting the pool-share proxy discard technical values on a corpus where they are ubiquitous.
**And the predicate's text scope** — `chunk_profile._values_text`, so the ingest-written
`[标准号: …]` identity header does not count as the passage "carrying" a value, which is what restores
rule 2's ability to discriminate at all. Neither touches a multiplier, a policy, a window, a
threshold, merge or fusion.

### `G4_DEPENDENCY`

**Split, and worth stating precisely.** The *defect* is not G4-dependent: extraction, `paired_values`,
`carries_value` and both multipliers are pure text and arithmetic, and the dense leg never enters them,
so the conflation and its uniform penalty persist unchanged on the healthy path. The *materiality of
any fix to this chunk* is G4-dependent: the target's rank (28/45/35), the overtaker counts and every
table/prose composition reported here are degraded-mode pure-lexical measurements, and on the healthy
path the base score itself changes, moving the target and all 57 other candidates at once. The
extraction defect can therefore be fixed and gated independently, but no recovery claim should be made
for this chunk until G4 unblocks and the rank is re-taken.

---

## Artifacts

* tracer: `deploy/repair_gates/question_value_attribution.py` (observation + diagnostic re-evaluation)
* record: `deploy/repair_gates/question_value_attribution_result.json`
* `git diff -- rag/` is empty for this window; production (`latest` = `6e926b5d8ef6`), the index, the
  planner and the P0 contract are untouched.
