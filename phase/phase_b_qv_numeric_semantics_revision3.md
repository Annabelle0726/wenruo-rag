# Phase B — QV Numeric Semantics, Revision 3

**Scope of this window: numeric semantics only.** Metadata provenance is frozen at
`METADATA_PROVENANCE_CONTRACT = BLOCKED` and was not touched; no regex heuristic was added; no producer,
mapping, index, consumer multiplier, Top-30, `.55`, `final_top_n`, merge/fusion, context selection,
embedding, health contract or planner file was modified; nothing was deployed, built or retagged.

## 1. Red first

`deploy/repair_gates/test_qv_revision3_gate.py` was written BEFORE any product change and run against
Revision 2: **22 failed / 12 passed**, then (after two of my own over-strict expectations were corrected,
both of which Revision 2 also satisfies) **20 failed / 14 passed** in the durable two-arm record. Failures
spanned all four families the audit named - intent binding (A1, A2, A3.1, A3.2, A3.3, the
sentence-global-cue test), the offset contract (the API did not exist, plus four round-trip cases, the
projection's offsets and the full-width-dot case), unit normalization (tab, newline, raw/projection
agreement) and the invariants (D1, D2, D3, D5). Artifact: `question_value_revision3_result.json`.

## 2. Intent binding is LOCAL (`INTENT_BINDING_MODEL`)

The rejected model asked *"does the sentence contain a cue"* and then promoted every occurrence of the
class. The replacement asks *"is THIS occurrence what the cue or the comparison is about"*:

* **Attribute cues** bind occurrences of their own attribute - `标准号是多少`, `型号是/为`, `哪一版`,
  `现行版本是`, `第几部分`/`表几`. That is what makes `GB/T 12706.2-2020的标准号是多少？` return the
  designation itself, and `型号为AB123CD吗？` return the model.
* **Comparison spans** are strictly local. A connective (`还是`/`或者`) binds the figure in front of it and
  the figure behind it, and nothing else; a choice interrogative (`哪一个`, `哪一部分`, `哪个`) binds the
  LIST immediately in front of it, walking backwards only across list connectors, whitespace and attribute
  suffixes (`年版、`). That is what makes `2026年版、2025年版，哪一个是现行版本？` and
  `Q/GDW 73286.2 和 73286.3 哪一部分规定了金属套厚度？` return their members.
* **Locator phrases** win over both. A `根据/依据/按照/参照/基于` cue at a CLAUSE EDGE binds the identity
  it introduces (and the rest of that designation span) as `IDENTITY_USED_TO_LOCATE_DOCUMENT`. The clause-edge
  requirement is what keeps the noun `依据` inside `投产依据` from demoting the year that follows it.

`根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？` -> `['3.9','4.1']`.
`根据2026版，投产依据是2025版还是2024版？` -> `['2025','2024']`, with `2026` a locator.

One real defect was found by the gate during this work and fixed: `_attribute_of` classified every
`GB/T`-style designation as a `reference` (its span test used the pattern that carries designation prefixes
too), so the designation cue could never bind it and A3.1 returned `[]`.

## 3. The offset contract (`OCCURRENCE_OFFSET_CONTRACT`)

Normalization (section-reference stripping, whitespace collapsing) is unchanged in EFFECT - it is still how
the extraction reads a question - but it now produces a normalized copy **plus a normalized-index to
original-index map**, and every published occurrence is translated back through it:

```
question[occurrence.start:occurrence.end] == occurrence.text
```

`decomposition.question_numeric_occurrences()` publishes all occurrences on original offsets;
`question_value_occurrences()` publishes the projected ones on the same contract. A figure normalization
DELETED (the `12` of `第12部分`) has no occurrence - the existing semantics, since an outline coordinate is
not a value. A figure whose original spelling differs from its canonical form (`1．5`) is published **as
written** with matching offsets while its CLASS is decided on the canonical form: a recorded equivalence,
asserted by the gate, rather than a silent rewrite.

## 4. Unit normalization (`_match_unit`)

The adapter now skips ANY whitespace between the digits and the unit, not just a space, so
`100m时`, `100 m 时`, `100\tm`, `100\nm` are one measurement, in the raw classifier and in the projection
alike. The lexicon is still the router's own and longest-valid-unit still resolves `kWh` against `kW`. No
whitelist was added.

Lexicon coverage is reported separately from classifier behaviour, as the audit required: `KWH`, full-width
unit spellings and scientific notation are NOT recognised because the router's lexicon does not contain
them - a coverage limitation, not a classifier defect, and extending that lexicon is a routing-contract
change outside this window.

## 5. Invariants as gates (D1-D5)

D1 locality (a connective changes nothing outside its comparison span, checked by prefixing locators to a
comparison question), D2 repeated-text independence (three `0.6`s in one sentence, three verdicts),
D3 projection legality (every projected occurrence is one of the input records, has an allowed class and
round-trips), D4 offset round-trip over a table of shapes including normalization-removing ones, D5 pool
independence asserted on the signature and name tables rather than by example.

## 6. Negative arm

`test_qv_revision3_mutation_arm.py` builds five mutants from the real module's helpers and proves the gate
catches each: sentence-global `还是`, string-key merging, normalized offsets published as original offsets,
unconditional year removal, and shortest-unit-prefix matching.

## 7. Results

| run | result |
|---|---|
| Rev 3 gate, Revision 2 arm | **20 failed / 14 passed** (`test_qv_revision3_mutation_arm.py` errors at collection: no original-offset API there) |
| Rev 3 gate + mutation arm, Revision 3 arm | **41 passed / 0 failed** |
| whole suite (Rev-1 gates, Rev-2 gate, Rev-2 occurrence gate, Rev-2 mutation arm, Rev-3 gate, Rev-3 mutation arm, repository unit tests) | **265 passed / 0 failed** |
| closed regressions (Rev-2 fail -> Rev-3 pass) | 20 |

Frozen isolation: `rerank.py`, `health.py`, `health_bridge.py`, `health_producers.py`, `query_router.py`,
`multi_route.py` byte-identical to the deployed image; the product diff of this window is exactly
`chunk_profile.py` (+174) and `decomposition.py` (+134); no P0 module, planner file or `pipeline.py` was
touched. The checkout's pre-existing `pipeline.py`/`planner.py` state was not used to establish anything.

## 8. Materiality - observation only

Live, read-only, LLM cache bypassed in process, Revision 3 mounted. Pool of 45 for that run (the live route
set varies between runs). Value sets on the frozen matrix unchanged from Revision 2: composite `-> []`,
year-only `-> []`, model number `['0.6','25'] -> ['25']`, value lookup `-> ['800']`, STRUCTURE `['220']`,
technical and multi-value unchanged. Movement: value penalties 6 -> 0, pairing 3 -> 0, target adjusted rank
36 -> 38, overtakers 9 -> 11, tables chosen 0 -> 0, target not selected either way, ordered top-12 tables
0 -> 1; header contamination 20/21 tables -> 6/21. **This is an observation on a degraded run and is not
evidence of recovery**; `FEATURE_NUMERIC_CORRECTNESS` and `QGDW_RECOVERY` remain separate, no rule targets
`d1d75672f2dbc333`, and `QGDW_RECOVERY_VERDICT` stays `NOT_ESTABLISHED`. Artifact:
`question_value_materiality_rev3_result.json`.

## 9. Artifacts

`rag/retrieval/chunk_profile.py`, `rag/retrieval/decomposition.py`,
`deploy/repair_gates/test_qv_revision3_gate.py`, `test_qv_revision3_mutation_arm.py`, `qv_revision3_run.py`,
`question_value_revision3_result.json`, `question_value_materiality_rev3_result.json`, this report,
`AGENTS.md`.

## 10. Production

Unmutated: `wenruo-rag-cpu` runs `sha256:6e926b5d8ef6…`, 0 restarts, `my-wenruorag:latest` still
`6e926b5d8ef6`, rollback anchor `c50436820cb9`. No deploy, no candidate build, no retag. G4 remains
`BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`; P1-2 remains PAUSED.
