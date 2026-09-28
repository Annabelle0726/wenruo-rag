# Phase B — Question-Value Feature Correctness Repair (REVISION after the Codex Red-Team Audit)

**Verdict of this window: the repair was revised to pass the independent audit. Direction kept,
implementation replaced.**
`CODEX_QV_REPAIR_AUDIT` was `REJECT`; this window is the answer to it, not a defence of it. No deploy,
no retag, no Stage-3 multi-route attribution was performed, and the frozen scope was not touched.

Baseline: `HEAD = 42ca64339` (the rejected repair). All "before" numbers below are that revision's
behaviour, reproduced first and then closed.

## 1. What the audit found, and what each finding became

| # | Audit blocker | Reproduction | Resolution in this revision |
|---|---|---|---|
| A | unit-aware technical detection, no hardcoded `kV`/`mm`/`°C` | `2000mm²`, `90°C`, `1.5mm`, `800～1200mm²`, `0.6/1kV` → `[]` | `_unit_end()` reuses `query_router._NUMERIC_UNIT_RE` (the tree's own unit lexicon) and requires the match to extend past the digits and not run into another letter |
| B | metadata boundary from the real producer of the header | mid-body `原文明确要求：[标准号: GB/T 10000 | 电压: 220kV]。` stripped, table-cell quotations stripped, nested-bracket titles half-deleted | boundary is the producer's own `rag/nlp/retrieval_projection._HEADER_RE` — leading, bracket-balanced, anchored at 0 — taken from that module when the build ships it, verbatim fallback when it does not; residual ambiguity **reported**, not papered over |
| C | pool-share must leave value identity entirely | 20 candidates all carrying `800` → `question_values` returned `[]` while `['800']` was correct | pool-share deleted from extraction; `_pool_share` retained as a **diagnostic**; pool independence asserted directly (values, pool-independence tests, `co_names`) |
| D | complete identity classification | `123ABC` → `['123']`, `IEC 60502-1:2021` → `['60502','2021']` as ANSWER values | `_IDENTITY_SPAN_RE` composed from `_STANDARD_DESIGNATION_RE` **and** `_REFERENCE_NUMBER_RE` (which carries `IEC`/`ISO`/`第`/`表`/`图`/`附录`) plus a `[-–—:]\d{4}` suffix; model-run and adjacency rules classify `123ABC`/`AB123CD`/`WDZC-YJY-0.6/1kV` as `MODEL_IDENTITY` |
| E | publish the semantic categories, prefer UNKNOWN over guessing | — | five constants published; `UNKNOWN_NUMERIC` is the conflicting-evidence class and is **kept**; the classes the extraction could not settle are counted and reported |
| F | adversarial cases into the formal suite, proved both ways | — | 22 node IDs **FAIL on the rejected revision and PASS on this one** (§3) |
| H | repair diff and checkout-vs-production scope reported **separately** | — | §4: the checkout is not deployable as-is |
| I | materiality only *after* the fix; `FEATURE_CORRECTNESS != QGDW_RECOVERY` | — | §5: live re-observation on the frozen production pool |

## 2. The changes

`rag/retrieval/chunk_profile.py`
* `_strip_ingest_preamble()` / `_split_ingest_header()` / `_header_re()` replace the marker-sniffing
  `_INGEST_METADATA_RE`. `_values_text()` = `_plain(_strip_ingest_preamble(_content(chunk)))`.
* `_IDENTITY_SPAN_RE` now composes the two designation vocabularies and appends the year/edition suffix;
  `_STANDARD_DESIGNATION_RE` and `standard_designations()` are byte-unchanged, so document resolution is
  unaffected.
* Published classes: `DOCUMENT_IDENTITY`, `MODEL_IDENTITY`, `TECHNICAL_MEASUREMENT`,
  `ANSWER_REQUESTED_NUMERIC_VALUE`, `UNKNOWN_NUMERIC`, with `NUMERIC_VALUE_CLASSES` naming the three that
  are figures a question asks about. `classify_numeric_token()` is the single classifier, with
  `_alnum_run`, `_is_model_designation`, `_unit_end`, `_letter_adjacent`, `_is_multiplication_sign`,
  `_is_range_continuation` as its evidence helpers.

`rag/retrieval/decomposition.py`
* `question_values()` classifies each candidate and keeps `NUMERIC_VALUE_CLASSES`; `MAX_VALUE_POOL_SHARE`
  and the universal-carry filter are gone; `chunks` is accepted (the frozen `rerank.py` passes it) and
  **cannot** influence the result. `question_value_classes()` exposes the per-figure decision for a
  diagnosis. `_pool_share()` is documented as diagnostic-only.

Not modified: `rag/retrieval/rerank.py` (sha256 `1152c59a…`, identical to production), `query_router.py`,
`multi_route.py`, `health*.py`, `rag/nlp/search.py`, the pipeline, the planner, the DTOs, the reason
taxonomy.

## 3. Two-arm proof (`deploy/repair_gates/question_value_two_arm_run.py`)

Identical gate files run against arm A (the two product files exactly as committed at the rejected
revision, `git show HEAD:…`) and arm B (this working tree). The gate files are never swapped, so a PASS
means something.

| Gate | Arm A (rejected) | Arm B (revision) |
|---|---|---|
| `test_question_value_adversarial_gate.py` | 20 failed, 17 passed | **37 passed** |
| `test_question_value_class_gate.py` | collection error (the API does not exist there) | **19 passed** |
| `test_question_value_feature_gates.py` | 2 failed, 31 passed | **33 passed** |
| **total** | 48 passed / 22 failed | **89 passed / 0 failed** |

The 22 closed regressions: 4 technical-positive shapes, 6 identity shapes (incl. `IEC 60502-1:2021`,
`123ABC`, `AB123CD`, `GB/T 19666 表 6.2`), 1 context-sensitive year question, 7 pool-share/pool-independence
cases, 3 metadata-boundary cases (mid-body quotation, table-cell quotation, no partial strip of a
bracketed title), and 2 pre-existing feature expectations. Full node list and machine-readable verdicts:
`deploy/repair_gates/question_value_two_arm_result.json`.

Repository unit tests on the revision: `test_question_value_semantics.py` (27) +
`test_value_pairing_cut.py` (9) = **36 passed**. `test_value_pairing_cut.py`'s
`test_a_figure_the_whole_pool_carries_is_not_a_signal` now asserts `["220"]` instead of `[]`, which is the
mandated reversal of the removed pool-share semantics and is documented in place.

## 4. The two scopes, reported separately (audit requirement H)

**`REPAIR_DIFF_SCOPE`** — working tree vs `HEAD`, this window only:

```
rag/retrieval/chunk_profile.py                                   | 317 +++++++++++++--
rag/retrieval/decomposition.py                                   | 127 +++------
test/unit_test/rag/retrieval/test_question_value_semantics.py    | 132 ++++---
test/unit_test/rag/retrieval/test_value_pairing_cut.py           |  17 +-
```
(that `git diff --stat` was filtered to `rag/ test/`; the same window also edited
`deploy/repair_gates/test_question_value_feature_gates.py` and added the new gate and artifact files in §7)

**`CHECKOUT_VS_PRODUCTION_SCOPE`** — working tree vs the deployed image's `/ragflow`:

| File | Verdict |
|---|---|
| `rag/retrieval/rerank.py`, `query_router.py`, `multi_route.py`, `health.py`, `health_bridge.py`, `health_producers.py`, `rag/nlp/search.py` | **SAME** as production |
| `rag/retrieval/chunk_profile.py`, `rag/retrieval/decomposition.py` | DIFFERS — this window's repair |
| `rag/retrieval/pipeline.py`, `rag/retrieval/__init__.py`, `rag/nlp/doc_context.py` | DIFFERS — **pre-existing** checkout drift |
| `rag/retrieval/planner.py`, `deploy/p1_gates/p1_2_live_replay_probe.py` | present in the checkout, **absent from the image** |

**Consequence, stated plainly: the working tree must not be built into a deployable image.** It carries
suspended P1-2 material (planner, modified pipeline and package init) and the unrelated `doc_context.py`
drift that this window neither wrote nor reviewed. A future build must take the deployed image and overlay
exactly `chunk_profile.py` and `decomposition.py`.

## 5. Materiality, re-observed after the fix (audit requirement I)

Live run: production ES/MySQL read-only, in-process LLM-cache bypass so nothing is written to the
deployed Redis, the REVISION mounted into a container on `wenruo-rag_ragflow`. Artifact:
`deploy/repair_gates/question_value_materiality_after_fix_result.json` (the earlier window's
measurement is preserved unchanged at `question_value_materiality_result.json`).

Value sets, old semantics vs this revision, on the frozen question matrix:

| Query shape | before | after |
|---|---|---|
| QGDW composite | `['73286.2','2026','73286.3']` | `[]` |
| standard + year (Part 2 / Part 3) | `['73286.2','2026']` / `['73286.3','2026']` | `[]` |
| voltage only (STRUCTURE) | `['220']` | `['220']` |
| value lookup | `['73286.2','2026','800']` | `['800']` |
| cable model number | `['0.6','25']` | `['25']` |
| genuine technical values | `['220','800']` | `['220','800']` |
| multi-value comparison | `['800','1200']` | `['800','1200']` |
| year only | `['2026']` | `[]` |
| no numbers | `[]` | `[]` |

Composite question, live pool of 39, target `d1d75672f2dbc333`:

| Observation | before | after | delta |
|---|---|---|---|
| value-list penalties firing on tables | 5 | **0** | −5 |
| value-pairing boosts firing | 3 | **0** | −3 |
| target adjusted rank | 29 | 33 | +4 |
| target adjusted score | 0.422540 | 0.422540 | 0.0 |
| target overtakers | 12 | 16 | +4 |
| tables chosen / target selected | 0 / false | 0 / false | none |

Header contamination, same pool, same value set, the only difference being whether the ingest header
counts as evidence: 14 of 15 tables "carried" the identity value through their header; **5 do so from
their body** after the fix; the target's carry changes `true → false`.

Reading, and the required separation:

* **`FEATURE_CORRECTNESS`: achieved.** The identity tokens no longer enter the value set, the technical
  values survive, the header is no longer evidence, and the pool cannot influence either.
* **`RETRIEVAL_QUALITY` / QGDW recovery: NOT established, and unchanged in kind.** The target is still
  not selected (`chosen_tables = 0` in both arms), and its adjusted rank moves *worse* (29 → 33) because
  the removed penalties had been hitting five OTHER tables that carried the standard number through their
  own ingest header. `FEATURE_CORRECTNESS != QGDW_RECOVERY`: this window repaired a rule's input, it did
  not recover the document, and it makes no claim about recall.

## 6. Reported limitations (not fixed here, deliberately)

1. **A bracketed document title is unreadable to the producer itself.** `retrieval_projection._HEADER_RE`
   forbids `[`/`]` inside a field and `render_retrieval_header` does not escape them, so a title like
   `…专用技术规范[第3部分].pdf` yields a header neither this consumer nor the producer's own
   `split_retrieval_header`/`token_fields`/`declared_prefix_kind` can read back. The contract implemented
   is: **nothing is stripped** (a partial deletion is the dangerous half — what the rejected version did)
   and the residual stays visible. A real fix is producer-side (escaped field values or a chunk flag set
   at ingest) and is out of this window's scope.
2. **The deployed image does not ship the backfill module.** `/ragflow/rag/nlp/` has `doc_context.py` and
   no `retrieval_projection.py`, so a hard import would have crashed the retrieval path; hence the
   producer-preferred, verbatim-fallback boundary, with an equivalence assertion that runs whenever the
   module IS present. The richer headers on live chunks were written by the Phase A backfill running that
   module from the repository, while the deployed ingest still writes the legacy three-field prefix — both
   shapes match the same anchored pattern.
3. **The measurement/identity decision inherits the unit lexicon's coverage.** A unit absent from
   `query_router._NUMERIC_UNIT_RE` (e.g. `mg`, a bare `m2` written without the second `m`) reads as a
   designation, exactly like `123ABC`. Extending that lexicon is a change to the routing contract and was
   not authorised here.
4. **Part numbers are still removed before classification.** `第2部分` figures never reach the classifier
   because the pre-existing structural stripper `strip_section_references` (shared with
   `parse_sub_queries`) runs first. Unchanged by this window, and pinned by a test that records the actual
   behaviour rather than claiming it fixed.
5. **`UNKNOWN_NUMERIC` is reachable but rare.** A letter-led run with a unit suffix is a designation, so
   conflicting evidence only survives in shapes like `X2000%` (one-letter prefix, symbol unit). Those are
   counted in a diagnosis rather than resolved by a guess.
6. The live materiality process printed `MATERIALITY_END` and wrote a complete, parseable report, then
   exited non-zero during teardown (consistent with the degraded embedding client); the observation is
   unaffected and is reported with that caveat rather than smoothed over.

## 7. Artifacts

* `deploy/repair_gates/test_question_value_adversarial_gate.py` — the audit matrix, behaviour level.
* `deploy/repair_gates/test_question_value_class_gate.py` — the published classes and the producer boundary.
* `deploy/repair_gates/test_question_value_feature_gates.py` — groups A–G, updated for pool independence.
* `deploy/repair_gates/question_value_two_arm_run.py` + `question_value_two_arm_result.json` — the proof.
* `deploy/repair_gates/question_value_materiality_after_fix_result.json` — the live re-observation.
* `test/unit_test/rag/retrieval/test_question_value_semantics.py`, `…/test_value_pairing_cut.py` — the
  repository's own unit tests for the same semantics.

## 8. Production state (untouched by this window)

Container `wenruo-rag-cpu` runs `sha256:6e926b5d8ef6…` (`my-wenruorag:repair-798288f8`), 0 restarts,
started `2026-09-28T05:04:48Z`; `my-wenruorag:latest` is still `6e926b5d8ef6`; the rollback anchor
`my-wenruorag:rollback-pre-p0-20260927` = `c50436820cb9` and the previous production
`my-wenruorag:p0-7-obs-9f3d2c79` = `ea93cd3bb795` are unchanged. **No deploy, no retag, no parameter
change, no write to the production Redis or index.** P1-2 remains PAUSED; G4 remains `BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`.
