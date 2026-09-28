# Phase B — QV Semantic Boundary Repair, Revision 2

**Verdict of this window: the second Codex REJECT was accepted and reproduced first; the repair was
rebuilt around occurrence-level provenance, a provenance-checked metadata boundary and an identity /
answer-intent split. No deploy, no retag, no Stage-3, frozen scope untouched.**

Baseline rejected: the revision documented in `phase_b_question_value_feature_correctness_repair_revision.md`
(sha256 `fb98a3a4…` / `555bdf2b…`, snapshotted before this window edited anything, because that revision
existed only as uncommitted work).

## 1. RED first: the reject reproduced in the formal gate

A new four-layer gate was written BEFORE any product change, and run against the rejected revision:

```
deploy/repair_gates/test_qv_revision2_gate.py            11 failed, 33 passed
deploy/repair_gates/test_qv_revision2_occurrence_gate.py 1 collection error (no per-occurrence model)
```

The eleven behavioural failures are the audit's counterexamples, each failing on its own semantics:
C (`储能容量100kWh`), D (`电缆长度100m时` and the spaced/unspaced equivalence), E (`ISO 9001:2015`),
F (`Q_GDW_73286.2-2026`), G (`标准发布的是2026年版还是2025年版？`), A (the body bracket
`[800 mm²：厚度3.9 mm]`), B (a title containing `]` deleted only up to the first bracket), plus the three
fail-closed clauses (malformed metadata, missing document name, unlabelled leading bracket) that the
revision satisfied only by stripping anyway. Counterexample H is a provenance-collapse defect: the
behaviour happened to survive it, and the occurrence gate's collection error is the finding - there was no
per-occurrence record in which the two `0.6`s could be distinguished. Artifact:
`question_value_revision2_red_result.json`.

## 2. The metadata chain, audited before any decision

Read from the live index and the deployed image, read-only:

* **Producer.** Two coexist. The deployed ingest calls `doc_context.apply_document_context`, which
  PREPENDS `render_document_context(standard_id, title, section)` into
  `ck["content_with_weight"]` and prepends the matching tokens into `content_ltks`/`content_sm_ltks`.
  The Phase A backfill wrote the richer `retrieval_projection` header. Both write into the text.
* **Stored chunk.** The live mapping has exactly these fields: `available_int, compile_kwd,
  content_ltks, content_sm_ltks, content_with_weight, create_time, create_timestamp_flt, deleted_doc_id,
  doc_id, doc_type_kwd, docnm_kwd, id, img_id, kb_id, knowledge_graph_kwd, lat_lon, page_num_int,
  position_int, q_3072_vec, title_sm_tks, title_tks, top_int`. **No field records the injected header, its
  offset or its length**; samples confirm the header lives only inside `content_with_weight`.
* **Consumer.** `chunk_profile._values_text` receives the chunk dict, so it has `docnm_kwd` and nothing
  else about where the header ends.

**`METADATA_PROVENANCE_AVAILABLE = PARTIAL`.** There is no byte-level provenance (the injected extent is
recorded nowhere), so the audit's `BLOCKING_AMBIGUITY` is correct as stated. What does exist is one
structured field the consumer can check against: the stored document name, which the legacy producer
writes into the header's `文档` field verbatim (`document_title` strips only the extension) and which the
backfill also uses as `metadata.title`.

## 3. Metadata boundary: provenance-checked, fail-closed, never partial

`_verified_header_end(text, chunk)` accepts a leading `[标准号: …` block only when **every** field parses
as `label: value` with a label the PRODUCERS declare (`doc_context`'s three plus
`retrieval_projection.PROFILES`, taken from that module when the build ships it) **and** the `文档` field
equals the passage's stored document name (with or without its extension). Candidates are tried at every
closing bracket, so a title that itself contains `]` is matched at its true end: such a header is removed
WHOLE or not at all. Any failure returns the text untouched.

This satisfies the four guarantees demanded, each as a gate: no partial deletion (B), no deletion of an
ordinary bracketed body (A), malformed metadata fails closed, and an unprovable boundary strips nothing.

Residual ambiguity, reported rather than hidden: a body that opens with a field list whose title field
reproduces the document name exactly would still read as metadata. Closing that needs a representation
change, and the minimal contract repair is: **have the producer record the injected extent** - a
`retrieval_header` string, or a `header_len_int`, or a `content_prefix_kind` per chunk, written by
`apply_document_context`/the projection at ingest and by any backfill - after which the consumer can
require byte equality with that field. That touches ingest, the backfill and the index mapping, and
therefore needs re-indexing and a deploy; it is reported as a **contract boundary** for authorisation
rather than guessed around, which is exactly what the audit's section 2 asks for.

## 4. Numeric semantics: occurrence-aware classification

`NUMERIC_CLASSIFICATION_MODEL = OCCURRENCE_AWARE`. `chunk_profile.NumericOccurrence` carries, per
occurrence: `text`, `start`, `end`, `kind`, `unit`, `unit_end`, `relation`
(`bare`/`range`/`ratio`/`tolerance`/`compound`), `designation_span`, `model_span`. Six published classes:

| class | meaning |
|---|---|
| `IDENTITY_USED_TO_LOCATE_DOCUMENT` | a name used to find the document |
| `IDENTITY_VALUE_EXPLICITLY_ASKED_BY_USER` | the same kind of figure, asked FOR by the question |
| `MODEL_IDENTITY` | an article's type code |
| `TECHNICAL_MEASUREMENT` | a quantity with a unit or a range/ratio/tolerance relation |
| `ANSWER_REQUESTED_NUMERIC_VALUE` | a bare figure the question asks about |
| `UNKNOWN_NUMERIC` | conflicting evidence; kept, and visible in a diagnosis |

`question_value_occurrences()` projects OCCURRENCES; `question_values()` is its text projection. The
string-keyed `question_value_classes()` is gone, which is what removes the audit's inconsistency
(`question_values` keeping `0.6` while a string map reported `MODEL_IDENTITY` for it).

Validation during this window: the first full-suite run caught a real defect in my own edit - the Rev-1
`classify_numeric_token` was still present and shadowed the new definition, so the identity path raised
`NameError` and direct callers reverted to Rev-1 behaviour. It was removed before any artifact was
published; the gate that caught it was the repository's own unit test, not a new one.

## 5. Unit adapter (section 4 of the audit)

`UNIT_BOUNDARY_VERDICT = LONGEST_VALID_UNIT + BOUNDARY_AWARE`. The lexicon stays
`query_router._NUMERIC_UNIT_RE`; the ADAPTER changed: its alternation is parsed once into one pattern per
unit, trailing `\b` is dropped (ASCII word boundaries cannot see the boundary between `m` and `时`), and
the boundary is enforced by this module (an ASCII letter or digit continues the token; anything else ends
it). Longest match resolves `kWh` against `kW` without naming either, so no `kWh`/`MPa`/`dB` whitelist
exists - `dB`, `MPa`, `MΩ`, `N·m`, `℃`, `mm²`, `±0.5mm`, `800～1200mm²`, `0.6/1 kV` and `100m时` all
resolve from the shared lexicon alone.

## 6. Identity vs answer intent (section 5)

`IDENTITY_AS_ANSWER_VERDICT = SPLIT`. An identity or model occurrence is answer-bearing only when the
question asks for that attribute: an explicit cue per attribute (`版本是`/`哪一版`/`发布的是` for editions,
`标准号是多少` for designations, `型号是什么` for models, `第几部分`/`表几` for references) or a choice
between two occurrences of the SAME attribute joined by `还是`/`或者`. `根据 Q/GDW 73286.2-2026，导体截面是
多少？` therefore keeps `2026` as a locator while `标准发布的是2026年版还是2025年版？` returns both years as
the answer. No context-free `year -> delete` rule remains, and none of it consults the corpus.

## 7. Gate and negative arm (section 7)

Four layers, all in the formal suite: occurrence classification, question projection, chunk evidence, and
consumer integration through the real frozen `apply_rank_adjustments`.

| run | result |
|---|---|
| rev 1 (rejected) | 33 passed / **11 failed** / 2 gate files failed |
| rev 2 (this) | **59 passed / 0 failed** |
| whole suite, rev 2 | **224 passed / 0 failed** (gates + repo unit tests) |
| mutation arm | **11 passed**, 4/4 defect classes caught |

The mutation arm applies each defect the audit named as a MUTANT of the real code and asserts the gate's
expectation is violated: metadata regex guessing (deletes `[800 mm²：厚度3.9 mm]`), shortest-unit-prefix
(returns `kW` for `100kWh` and leaves the figure looking like a code), string-key provenance collapse
(reports the voltage `0.6` as `MODEL_IDENTITY`), unconditional year removal (returns `[]` for a question
whose answer is the edition). Artifacts: `question_value_revision2_result.json`,
`question_value_revision2_red_result.json`.

## 8. Materiality (section 8) - observed, never a correctness gate

Live, production ES/MySQL read-only, LLM cache bypassed in process, the revision mounted. Pool of 33 for
that run (the live route set varies between runs, which is why the numbers below are an observation and
not a threshold):

| observation | before | after |
|---|---|---|
| value-list penalties firing on tables | 6 | **0** |
| value-pairing boosts firing | 3 | **0** |
| target adjusted rank | 9 | 9 |
| target overtakers | 0 | 0 |
| tables chosen | 4 | 6 |
| ordered top-12 tables | 3 | 8 |
| target selected | true | true |
| header contamination (identity value "carried" by header only) | 12/12 tables | 6/12 (body only) |

Value sets on the frozen question matrix are unchanged from the previous window's observation and now
semantically correct: composite `['73286.2','2026','73286.3'] -> []`, year-only `-> []`, model number
`['0.6','25'] -> ['25']`, value lookup `-> ['800']`, STRUCTURE `['220']`, technical and multi-value
unchanged. **`FEATURE_CORRECTNESS != QGDW_RECOVERY`**: no rule targets `d1d75672f2dbc333`, its rank moved
in neither direction in this run, and the seat it loses or keeps is the clause-intent context cut, which is
out of scope. Artifact: `question_value_materiality_rev2_result.json`.

## 9. Limitations reported

1. **Representation.** No chunk records the injected header, so the boundary is verified against the stored
   document name rather than proven byte-for-byte. A body that opens with a field list reproducing the
   document name would read as metadata. The minimal contract repair is specified in section 3 and needs
   producer + ingest + backfill + re-index + deploy, i.e. an authorisation this window does not hold.
2. **Lexicon coverage is the router's.** A unit the router's lexicon lacks cannot be recognised; extending
   it is a routing-contract change, not this repair's.
3. **`strip_section_references` runs first**, so `第2部分` figures never reach the classifier - pre-existing,
   shared with `parse_sub_queries`, recorded by a test instead of silently claimed.
4. The live materiality process printed `MATERIALITY_END` and wrote a complete report, then exited non-zero
   during teardown (the same degraded-embedding teardown seen last window); the observation is unaffected.

## 10. Artifacts

`rag/retrieval/chunk_profile.py`, `rag/retrieval/decomposition.py`,
`deploy/repair_gates/test_qv_revision2_gate.py`, `test_qv_revision2_occurrence_gate.py`,
`test_qv_revision2_mutation_arm.py`, `qv_revision2_run.py`, `question_value_revision2_result.json`,
`question_value_revision2_red_result.json`, `question_value_materiality_rev2_result.json`,
`test/unit_test/rag/retrieval/test_question_value_semantics.py`, `test_value_pairing_cut.py`,
`deploy/repair_gates/test_question_value_feature_gates.py`,
`deploy/repair_gates/test_question_value_adversarial_gate.py`, `phase/…_revision.md`, `AGENTS.md`.
Deleted as superseded: `deploy/repair_gates/test_question_value_class_gate.py` (its cases are the
occurrence gate's).

## 11. Production

Untouched: `wenruo-rag-cpu` runs `sha256:6e926b5d8ef6…`, 0 restarts, `my-wenruorag:latest` still
`6e926b5d8ef6`, rollback anchor `my-wenruorag:rollback-pre-p0-20260927` = `c50436820cb9`. No deploy, no
retag, no parameter change, nothing written to the production Redis or index. G4 remains
`BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`; P1-2 remains PAUSED.
