# Phase B — Provenance retrieval wiring + candidate readiness

Scope: wire the already-implemented provenance contract so retrieval can see it, and determine the candidate
overlay. No build, deploy, retag, backfill, re-index or production mutation. Numeric Rev-3.1 frozen; P1-2
paused.

## 1. RED first, through the real projection

`deploy/repair_gates/test_metadata_wiring_gate.py` drives the REAL projection: an isolated index
(`metadata_wiring_gate`) created from `conf/mapping.json`, four chunks written as the producer writes them,
then `Dealer.search` - the method `Dealer.retrieval` calls at `search.py:1009` with no `fields=` override, so
the default list at `search.py:443-468` IS the retrieval projection (asserted on the source by the gate).
The returned `SearchResult.field` entries are handed to `chunk_profile._body_text` / `carries_value`
unchanged; no final chunk dictionary is mocked.

RED on `bfe9660ee`: **4 failed / 3 passed**, the failures being `KeyError: 'content_prefix_kind_kwd'` and
`KeyError: 'content_prefix_chars_int'` - the stored document had provenance, the retrieved chunk did not, so
`_body_text` returned the whole content and an injected header could still contaminate `carries_value`. The
three passing tests are the ones that do not need provenance (collision, legacy, and the call-site check).

## 2. The wiring change, and its exact diff against production

One additive hunk in `rag/nlp/search.py`, inside `Dealer.search`'s default field list:

```
@@ -463,2 +463,11 @@ class Dealer:
+                # The producer's record of what IT injected at the head of content_with_weight: ...
+                "content_prefix_kind_kwd",
+                "content_prefix_version_int",
+                "content_prefix_chars_int",
+                "content_prefix_hash_kwd",
```

9 added lines, **0 removed**, no hunk anywhere else - so the deployed FALSE_EMPTY repair is byte-equivalent
and nothing touching scoring, ES expressions, the lexical query, the dense query, fusion, similarity,
Top-30, `.55`, the reranker, multi-route or context selection changed. `test_metadata_wiring_gate`'s
`test_the_projection_carries_the_provenance_fields` now passes: the four fields travel with the content.

## 3. The blocker this window found: the datastore stringifies the two integers

`rag/utils/es_conn.py:640-648` stringifies every non-list value read back by `get_fields`, with exactly one
exemption:

```python
if n == "available_int" and isinstance(v, (int, float)):
    m[n] = v
    continue
if not isinstance(v, str):
    m[n] = str(m[n])
```

So after wiring, `content_prefix_chars_int` arrives as `'105'` and `content_prefix_version_int` as `'1'`,
while `verified_prefix_extent` requires `isinstance(extent, int)`. The consequence is measured, not argued:
the wiring gate's end-to-end cases fail with `assert isinstance('105', int)` and `None == 105` - **every**
chunk would fail closed, so the contract would still be inert, for a second reason.

Per this window's instruction ("If any other product file is required, STOP and report why before modifying
it") the wiring stops here and the decision is escalated:

* **(A) `rag/nlp/doc_context.py`** - let `verified_prefix_extent` accept the datastore's declared read-back
  representation: a strict canonical decimal string (`str.isdigit()`, no sign, no whitespace) alongside a
  real int. The invariant is unchanged (positive, in range, hash verifies); the file owns the contract, and
  the change is a few lines. **Recommended.**
* **(B) `rag/utils/es_conn.py`** - add the two `*_int` provenance fields to the `available_int`-style
  exemption so the connector stops stringifying them. Smaller diff, but it is a shared connector read by
  every path and it special-cases two field names in the transport layer.

Neither is authorised yet, so the implementation is left exactly as wired.

## 4. End-to-end results (isolated index → real projection → consumer)

| case | stored | retrieved | consumer |
|---|---|---|---|
| provenance | fields present | `kind`/`hash` byte-identical, extent `'105'` (stringified) | rejects the stringified extent → whole content (blocker above) |
| body collision | no provenance | none returned | whole body survives; `carries_value(['220']) == True` |
| corrupted | extent inconsistent with hash | transported unchanged | rejected; no partial strip |
| legacy | no provenance | none returned | fail closed; whole content is evidence |

The collision and legacy cases pass end-to-end today; the provenance and corrupted cases expose the blocker,
and the projection-fidelity assertions (field-for-field, no coercion beyond the datastore's own) are what
detect it.

## 5. Regression status

* Whole gate suite + repository unit tests: **352 passed / 5 failed** before the blocker analysis; the 5 are
  the 3 wiring cases blocked on §3 and 2 in `test_degradation.py`.
* `test_degradation.py`: **14 passed / 2 failed**, both failures at `test_degradation.py:167`
  (`assert old_trace == traces`) - the frozen-baseline comparison sees the projection requesting four more
  fields. That is the additive wiring being detected, not a behaviour regression: the non-retryable
  embedding failure degrades to lexical, the retryable connector failure degrades, auth/config/permission/
  unknown raise, lexical executes after dense failure, late dense completion cannot overwrite timeout or
  failure state, and the health event stays honest - all green. The gate was neither weakened nor rewritten.
* Metadata G1-G10, the metadata mutation arm, the mapping gate, the corpus freeze runner and the Numeric
  Rev-1/2/3/3.1 suites are unchanged by this window (only `search.py` was touched) and remain green as of the
  immediately preceding window's run; this window's suite run re-exercised them (they are part of the 352).

## 6. Candidate overlay (relative to `my-wenruorag:repair-798288f8`, `sha256:6e926b5d8ef6`)

**A. Python runtime overlay (7 files, sha256 prefixes as measured; full digests to be recomputed at build)**

| file | sha256 (first 16) |
|---|---|
| `rag/nlp/doc_context.py` | `ddd4000595e83b37` |
| `rag/nlp/retrieval_projection.py` | `5618bfb01fded4f4` |
| `rag/retrieval/chunk_profile.py` | `248a6af9bcf8a835` |
| `rag/nlp/search.py` | `f4078a9574541c64` |
| `api/apps/restful_apis/chunk_api.py` | `e63a7ac4df731da3` |
| `rag/svr/task_executor_refactor/dataflow_service.py` | `0132bdc4bf425d00` |
| `rag/advanced_rag/harness/tools/text_processing.py` | `a3007bdbb6ba95a2` |

**B. Go provenance files NOT required:** `internal/ingestion/component/chunker/doccontext.go` and
`prefixprovenance.go` - this deployment ingests with the Python backend; they are repository parity for the
Go backend and must not enter a Python runtime overlay.

**C. Must not enter the runtime overlay:** everything under `deploy/repair_gates/` (gates, runners, result
JSONs), `test/`, `phase/`, `AGENTS.md`.

**D. Unrelated checkout drift (never overlay):** `rag/retrieval/pipeline.py` and `rag/retrieval/__init__.py`
(pre-existing P1-2-era differences), `rag/retrieval/planner.py` (absent from the image), the operator's lint
edits in `deploy/p0_*/` and `tools/scripts/`, and the four provenance columns the non-ES backends
(Infinity/OB/GaussDB/SereneDB) would need.

## 7. `CANDIDATE_OVERLAY_READY = NO`

Not because the wiring is wrong - it is correct and additive - but because with the datastore's declared
read-back representation the contract cannot activate, so a candidate built from this set would ship a
fail-closed-only contract. The single remaining decision is §3(A) or §3(B); after it, the overlay above is
sufficient and no further file is required.

Production remains unmutated: `wenruo-rag-cpu` runs `sha256:6e926b5d8ef6`, 0 restarts, `latest` unchanged,
rollback anchor `c50436820cb9`.
