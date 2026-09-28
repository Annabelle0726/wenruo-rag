# Question-Value Feature Correctness Repair (repository implementation + offline gates)

**Scope, as authorised:** the extraction/classification semantics of `decomposition.question_values`, the
metadata-vs-evidence boundary in `chunk_profile._values_text`, the internal helpers those need, their
tests, and this documentation. **The consumers were not touched.**

Explicitly **not** this window's goal: recovering the Q/GDW target chunk into the final 12 passages.
`QGDW_RECOVERY_VERDICT` is reported separately below and remains `NOT_ESTABLISHED`; its materiality is
G4-bound.

**Not modified:** `×1.3` `VALUE_PAIRING_BOOST`, `×0.8` `VALUE_LIST_PENALTY`, `TABLE_PENALTY`,
`CORE_DOCUMENT_BOOST`, route page size / Top-30, the `.55` threshold, `final_top_n`, the table/prose
selection policy, multi-route merge/fusion, the reranker, the embedding leg, the planner/P1-2, the
`retrieval_health` DTO, the P0-7 frozen event, the reason taxonomy.
**No deployment. No retag.** Production remains `latest` = `6e926b5d8ef6`.

---

## `FEATURE_BUG_ROOT_CAUSE`

A stable, pure text-and-arithmetic defect with three parts, all at the input to the value rules.

1. **No type distinction.** `question_values` took every token matching `\d+(?:[.．]\d+)?` with at least
   two digits or a decimal point. A standard's part number, its year, a model-code fragment and a
   genuine technical value were one class.
2. **A discrimination proxy that selects backwards.** The surviving tokens were then filtered by
   `_pool_share(value, pool) <= 0.80`, whose stated purpose was to drop figures "the pool already carries
   everywhere". On a single-standard corpus the verdicts invert: an **answer-bearing** value is carried
   by 83–100 % of the window, because every table of that standard lists it, so it is **discarded**;
   a **document identity** token is carried by 29–41 %, because it names exactly one document, so it is
   **kept**. Measured: `800` (share 0.95) dropped, `73286.2` / `73286.3` / `2026` (0.41 / 0.33 / 0.29) kept.
3. **The ingest's own identity preamble counted as evidence.** `_values_text` read
   `_plain(_content(chunk))`, which includes the pipeline-written
   `[标准号: Q/GDW 73286.3 | 文档: … | 电压: 220kV | …]`. Because that preamble is in every chunk of the
   standard, `carries_value` was true for **22 of 22 tables**, so the rule that exists to separate a
   table which merely LISTS the question's figures from one that PAIRS them degenerated into a flat
   `×0.8` on the whole type.

Measured consequences on the composite question before the repair: the `×1.3` pairing boost fired on
three prose chunks, all of them pairing the standard's **year**; the target table was penalised `×0.8`
for "carrying" its own designation; and on a cable-model question a fragment (`0.6`) of
`WDZC-YJY-0.6/1kV` boosted a similarity-**0.0836** table by 30 %.

## `FILES_CHANGED`

| file | change |
| --- | --- |
| `rag/retrieval/chunk_profile.py` | added `_IDENTITY_SPAN_RE` and `identity_spans()` (designation **with** its year suffix, composed onto the existing pattern so `_STANDARD_DESIGNATION_RE` and `standard_designations` are untouched); added `_INGEST_METADATA_RE`; `_values_text` now strips the ingest preamble |
| `rag/retrieval/decomposition.py` | `question_values` classifies before it filters: `_is_document_identity`, `_is_code_fragment`, `_YEAR_REFERENCE_RE`, `_YEAR_CUE_RE`, `_UNIT_SUFFIX_RE`; `MAX_VALUE_POOL_SHARE` removed and the share test replaced by the universal-carry degeneracy |
| `deploy/repair_gates/test_question_value_feature_gates.py` | 32 offline gate cases: regression matrix A–F plus the frozen-consumer proof |
| `deploy/repair_gates/question_value_materiality.py` | materiality isolation (old vs new value sets on the SAME pool, plus the header-contamination isolation) |
| `test/unit_test/rag/retrieval/test_question_value_semantics.py` | 18 repository unit tests for the same semantics |
| `deploy/repair_gates/question_value_attribution.py` | the stage-three tracer records the pre-repair share limit as a literal, since the constant it measured no longer exists |

**The rule is semantic, not token-specific.** No literal (`73286`, `2026`, `800`, `1200`) appears in any
condition. Identity is decided by three shapes: inside a designation span, a four-digit year carrying a
年/版 cue, or a digit run embedded in a letter-bearing chunk that is not a bare unit suffix.

## `IDENTITY_VALUES_EXCLUDED`

| question shape | before | after |
| --- | --- | --- |
| standard number + year, composite | `73286.2`, `2026`, `73286.3` | **`[]`** |
| standard number + year | `73286.2`, `2026` | **`[]`** |
| standard number + year (other part) | `73286.3`, `2026` | **`[]`** |
| standard + year + one figure | `73286.2`, `2026`, `800` | **`800`** |
| cable model number | `0.6`, `25` | **`25`** |
| year only | `2026` | **`[]`** |

## `TECHNICAL_VALUES_PRESERVED`

| question shape | before | after |
| --- | --- | --- |
| genuine technical values (`220kV … 800 mm²`) | `220`, `800` | **`220`, `800`** |
| multi-value comparison (`800` / `1200`) | `800`, `1200` | **`800`, `1200`** |
| standard + year + one figure | `800` **discarded** | **`800` kept** |

At a pool share of **0.95** (the measured corpus case) a technical value is now kept; so is **0.833**.
The only value still dropped is one that **every** candidate carries, and that is stated as an equality
(`share < 1.0`) rather than a tuned ratio: a token the entire window carries cannot separate any two of
its members. `2000 mm²` is not mistaken for a year because the year rule requires its 年/版 cue.

## `HEADER_CONTAMINATION_REMOVED`

Same pool, same value set, the only difference being whether the ingest preamble counts as evidence:

| measurement | before | after |
| --- | --- | --- |
| tables the ingested `[标准号: …]` makes "carry" the value | **22 / 22 (100 %)** | **5 / 22 (23 %)** |
| real `VALUE_LIST_PENALTY` reach | 22 of 22 tables | **5** of 22 |
| the target chunk "carries" `73286.3` | **True** | **False** |

The removal is scoped to the bracketed metadata block, so a figure that also occurs in the document's
own body still matches — asserted for the body-only, header-only, header+body and
designation-plus-technical-value cases, and for an **ordinary** bracketed phrase
(`[温度 20 ℃ 湿度 60 %]`), which is not metadata and is left in place.

## `CONSUMER_MULTIPLIERS_CHANGED`

**None.** Proven two ways in the gate:

* `rag/retrieval/rerank.py` is **byte-identical** to the deployed image (`sha256 1152c59a782766bf…` is
  asserted in the gate, and `git diff` over that file is empty), so the selection consumer and the
  warning consumer cannot have changed either.
* Feeding a **known** value set through the **real** `apply_rank_adjustments` reproduces the exact
  multipliers: a table pairing the value ⇒ `rank_score / base == 1.3`; a table listing it without
  pairing ⇒ `0.8`; a table with `table_penalty=0.85` ⇒ `0.85 × 1.3`; prose carrying no value ⇒ `1.0`.
  All nine frozen constants are asserted unchanged.

## `QGDW_TARGET_BEFORE_AFTER`

Materiality observation only — computed on **one** pool with both value sets so that planner variance
(the chat decomposition is not deterministic) cannot be read as the repair's effect. Not a basis for
tuning anything.

| quantity | before | after | delta |
| --- | --- | --- | --- |
| target base similarity | 0.3491735928050112 | 0.3491735928050112 | — |
| target adjusted `rank_score` | 0.296423 | 0.296423 | 0 |
| target adjusted rank | 37 | **35** | **−2 (better)** |
| target overtakers | 9 | **7** | −2 |
| `×1.3` pairing boosts | 3 | **0** | −3 |
| `×0.8` table penalties | 5 | **0** | −5 |
| tables in the ordered top-12 | 1 | 1 | 0 |
| **tables actually selected** | **0** | **0** | 0 |
| prose selected | 12 | 12 | 0 |
| **target selected** | **False** | **False** | unchanged |

The target's score is unchanged because the header fix alone had already freed it from the spurious
`VALUE_LIST_PENALTY`; the two places it gains come from the three year-driven prose boosts disappearing.
Run-to-run the intermediate rank moves by ±2 in either direction because the route set itself varies —
which is exactly why the before/after comparison was isolated on one pool.

## `CONTROL_MATRIX`

| # | control | requirement | result |
| --- | --- | --- | --- |
| A | standard number + year | `73286.2 / 73286.3 / 2026` are not values | **PASS** — all three shapes yield `[]` |
| B | genuine technical values | `800 / 1200` survive a high pool share | **PASS** — share 0.95 and 0.833 both kept; only a universal value is dropped |
| C | model number | no answer value from the code | **PASS** — `0.6` excluded; `3×25`'s `25` retained as a measurement; the 0.0836 table no longer boosted |
| D | table body | a real body value is still `carries_value` | **PASS** — body-only, header+body, and result-paired cases |
| E | metadata only | a header-only figure does not trigger `carries_value` | **PASS** — `73286.3` and `220` both False; ordinary bracketed prose unaffected |
| F | ordinary query | no unrelated change | **PASS** — non-numeric, empty and structural-only questions all `[]` |

## `FEATURE_CORRECTNESS_VERDICT`

**PASS.** 32/32 offline gate cases and 18/18 repository unit tests, run against a container built from
the **deployed image** with only the two repaired files mounted, so the code under test is production
plus this delta.

**The gate is not vacuous — negative control on unmodified deployed code:**

```
question_values(composite)                  = ['73286.2', '2026', '73286.3']   (identity admitted)
carries_value(header-only table, '73286.3') = True                            (preamble read as evidence)
question_values('800 mm²', pool share 0.95) = []                              (technical value discarded)
```

All three gate groups fail there and pass here.

## `QGDW_RECOVERY_VERDICT`

**NOT_ESTABLISHED / TARGET_STILL_NOT_SELECTED.** The target is still not selected, and the window still
seats **0 tables** of 12 — before and after. The repair removed spurious signals and moved the target
two places, but the seat is lost to the clause-intent context cut, which is out of this window's scope
and was not touched. No parameter was adjusted to change that, and none will be.

## `G4_STATUS`

`BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY` — unchanged. This repair is deterministic text and
arithmetic, which is why it could be gated with the dense leg degraded. **No claim is made that Q/GDW
retrieval quality is restored on the healthy hybrid path**, where the base score — and therefore every
rank above — is different and unmeasured.

## `P1_2_STATUS` / `PRODUCTION_MUTATED`

**P1-2: PAUSED** — no planner, cache or `plan_hash` work in this window.
**PRODUCTION_MUTATED: NO** — repository implementation, offline gates and read-only production
comparison only. No build, no deploy, no retag (`latest` = `6e926b5d8ef6`), no write to production ES,
MySQL or Redis (the materiality run bypassed the LLM cache in-process).
