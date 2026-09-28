# Phase B — Metadata Provenance Contract: implementation + offline gates

Scope: repository implementation and offline gates only. No deploy, no candidate build, no retag, no
production mapping change, no backfill, no re-index, no retrieval parameter change, no QGDW tuning, no P1-2.
`METADATA_PROVENANCE_CONTRACT = ACHIEVED` (G1-G10 pass). Numeric Rev-3.1 is untouched.

## 1. The contract

Four fields, written by the producer at the moment it injects, never recovered by parsing:

| field | written by | type via existing template |
|---|---|---|
| `content_prefix_kind_kwd` | producer | `keyword` (`*_kwd`) |
| `content_prefix_version_int` | producer | `integer` (`*_int`) |
| `content_prefix_chars_int` | producer | `integer` (`*_int`) |
| `content_prefix_hash_kwd` | producer | `keyword` (`*_kwd`) |

Invariant: `kind != none` -> the extent was recorded by the producer -> `hash(content[:extent])` equals the
recorded hash -> and only then is `content[extent:]` the body. **Absent, malformed, unknown-kind,
out-of-range, unverifiable or stale provenance means the whole `content_with_weight` is the passage's
text.** `content_prefix_body_hash_kwd` was deliberately NOT added: the four fields enforce every invariant
the gates need, and the body hash would add state coupling without a gate that requires it.

Hash: `xxhash.xxh64(prefix.encode("utf-8")).hexdigest()`, 16 lowercase hex characters - the same algorithm
the repo already uses for chunk ids, and available to BOTH producers (`xxhash` in Python, `cespare/xxhash/v2`
already in `go.mod`).

## 2. Producer authority, not consumer authority

The old idempotency test - `body.lstrip().startswith("[标准号: ")` in `doc_context.py` and
`strings.HasPrefix(strings.TrimSpace(text), contextPrefixOpen)` in `doccontext.go` - is GONE. Both producers
now ask `verifiedPrefixExtent(chunk)`; a chunk with no trustworthy provenance is treated as un-prefixed and
is injected, so a body whose own first bytes look like a header is still prefixed and its text survives
intact with a recorded extent that covers only the injected part. Behaviour by case:

| case | behaviour |
|---|---|
| fresh parser body | inject; record kind/version/extent/hash |
| fresh body that LOOKS like a header | **inject** (this is the defect the contract removes); the look-alike text stays in the body |
| already-provenanced chunk | no-op: provenance, not text, says a prefix exists |
| legacy unprovenanced content | treated as un-prefixed (a re-run over stored legacy content WOULD add a second prefix), so re-processing stored chunks is the projection path's job, and the projection never certifies a boundary it did not write |
| projection/backfill | `apply_projection` records `identity_profile`/version 2 for what IT wrote when the input was proven; over an unprovenanced input it performs the legacy text replacement and records `kind: none` |
| repeated invocation | provenanced chunks are skipped; extent, hash, content and chunk id are unchanged |
| manual chunk edit | provenance survives only when the edited content still begins with the recorded prefix bytes; otherwise cleared |
| other `content_with_weight` writers | chunks they CREATE carry no provenance (= `none`); the two that MUTATE an existing chunk (`dataflow_service.py`, `harness/tools/text_processing.py`) clear it |

## 3. Consumer

`chunk_profile._values_text` reads `split_prefix(chunk)[1]`; `_verified_header_end`, `_header_labels`,
`_document_names`, `_strip_ingest_preamble`, `_HEADER_FALLBACK_LABELS` and `_CONTEXT_PREFIX_OPEN` were
DELETED (116 lines), so no second authority exists - asserted by the gate. Consumers never derive or repair
an extent. Numeric Rev-3.1 classification is untouched.

## 4. Gates (written RED first)

RED against the pre-contract revision: **24 failed / 8 passed, 1 error**. GREEN after implementation:
contract gate + mutation arm **41 passed**; whole suite **348 passed / 0 failed**, with all Numeric
Rev-1/2/3/3.1 suites unchanged.

| gate | result |
|---|---|
| G1 exact producer boundary (incl. a code-point, not byte, extent) | pass |
| G2 collision impossibility (identical bytes, two provenances, two bodies) + the producer no longer skipping on text | pass |
| G3 hostile names (`] [ | :`, unicode, double spaces, tabs/newlines, nested brackets) cannot shift the boundary; no heuristic remains | pass |
| G4 tamper/stale: one prefix byte, a wrong extent with the original hash, a wrong hash, a truncated prefix, malformed/missing provenance | fail closed, never partially stripped |
| G5 idempotency: second producer pass changes nothing; content, extent, hash, id unchanged | pass |
| G6 manual-edit invalidation (both directions) + the API uses the helper | pass |
| G7 mixed pool (legacy + new + malformed) deterministic and per-chunk | pass |
| G8 byte freeze: content, chunk id, token fields, embedding input identical; only provenance added | pass (§5) |
| G9 rollback: old consumer on a new chunk, new consumer on a legacy chunk, new on new, new on corrupted | pass |
| G-mapping: isolated harness index types and stores the four names from the existing dynamic templates | pass (2/2) |
| G10 negative arm: regex-derived extent, filename-derived provenance, extent trusted without the hash, stale provenance after an edit, string-skip producer | 5/5 killed |

## 5. Byte freeze, measured against the previous revision

`metadata_contract_freeze_run.py` runs the same fixtures through the producer as committed at `b873fcb03`
and through this one, and through the previous and current consumer:
`corpus_bytes_frozen_outside_the_collision_fixture = True`, `provenance_is_additive_only = True`,
`collision_fixture_fixed_as_intended = True` (the old producer skipped the look-alike body and the new one
prefixes it, gaining only the prefix). Old consumer on a new chunk: `body = '3.9'` - today's behaviour is
preserved. New consumer on an unprovenanced chunk: the whole content is evidence. Artifact:
`metadata_contract_freeze_result.json`.

## 6. Producer coverage and the two things left out

Covered: the normal ingest and its safety gate (both call `apply_document_context`), the refactored ingest
(`chunk_service` calls the same function), the projection/backfill entry point (`apply_projection`), and - for
the first time in this chain - the **Go ingestion backend**, which shares both the prefix format and the
string skip; it now records the same four fields with the same hash. The Go change is parse-verified
(`gofmt -e`) and compiles in isolation (`go build` on the two changed files, temp package removed); the
package's own `go build`/`go test` cannot run in this environment because an unrelated cgo dependency
(`office_oxide.h`) is missing from the checkout - a pre-existing condition, not caused by this change.

Not wired: the retrieval field projection. `rag/nlp/search.py` selects an explicit field list
(`search.py:452-468`) that does not include the four fields, and that file carries the frozen incident
repair, so this window did not touch it. Until those four names are added there, a consumer reading chunks
from ES sees no provenance and fails closed - safe, but inert. That is a one-block change to a frozen file
and is reported as the first follow-up rather than made silently.

## 7. Non-ES backends

ES/OpenSearch need **no mapping change** (proved by the isolated gate). Infinity (`conf/infinity_mapping.json`
declares an explicit field list), OceanBase (`ob_conn.py` SQLAlchemy columns), GaussDB
(`gaussdb_conn.py` field list) and SereneDB (`serenedb_conn.py` column map) declare their schemas explicitly,
so the four columns would have to be added for those backends to store provenance. Not implemented here: no
gate in this window requires them and the authorisation excludes unrelated backend migrations.

## 8. Files

Product: `rag/nlp/doc_context.py` (contract + provenance-aware idempotency + invalidation helper),
`rag/nlp/retrieval_projection.py` (`apply_projection`), `rag/retrieval/chunk_profile.py` (consumer;
heuristic deleted), `api/apps/restful_apis/chunk_api.py` (edit invalidation),
`rag/svr/task_executor_refactor/dataflow_service.py` and
`rag/advanced_rag/harness/tools/text_processing.py` (mutators clear provenance),
`internal/ingestion/component/chunker/doccontext.go` + `prefixprovenance.go` (Go producer).
Gates: `test_metadata_contract_gate.py`, `test_metadata_contract_mutation_arm.py`,
`test_metadata_contract_mapping_gate.py`, `metadata_contract_freeze_run.py` (+ result JSONs).
Fixture adaptations with NO expectation change: `test_qv_revision2_gate.py`,
`test_qv_revision2_mutation_arm.py`, `test_question_value_adversarial_gate.py`,
`test_question_value_feature_gates.py`, `test/unit_test/rag/retrieval/test_question_value_semantics.py` -
each now records, for tests that assert about a PRODUCER-WRITTEN header, exactly what a producer records;
tests that assert the fail-closed direction keep fixtures with no provenance and are unchanged.

## 9. Production

Unmutated: `wenruo-rag-cpu` runs `sha256:6e926b5d8ef6…`, 0 restarts, `latest` still `6e926b5d8ef6`, rollback
anchor `c50436820cb9`. Mappings, index, documents and parameters untouched; the mapping gate ran against the
isolated harness ES and removed its throwaway index. `rerank.py`, `health*.py`, `multi_route.py`,
`query_router.py` and `rag/nlp/search.py` remain byte-identical to production; `pipeline.py` still carries
its pre-existing unrelated drift.
