# Phase B — Nine-File Runtime Merge Audit (ninth file: `api/db/services/dialog_service.py`)

**Scope of this record.** Consolidates the merged-file audit for the nine-file runtime release set:
baseline provenance, the reconstruction of the ninth file, the file-purity proofs, the adjudicated
degradation invariant, and every bounded gate result produced in this round.

**Verdict.** `DIALOG_SERVICE_RELEASE_DIFF = QUOTE_HEALTH_ONLY` ·
`DEGRADATION_GATE_RESULT = PASS (26/26)` · `NINE_FILE_RELEASE_CLOSURE = COMPLETE` ·
`SAFE_TO_BUILD_NINE_FILE_CANDIDATE = YES` · `PRODUCTION_MUTATED = NO`.

---

## 1. Production baseline (the only legitimate source for the ninth file)

| Item | Value |
| --- | --- |
| Image | `my-wenruorag:repair-798288f8` |
| Image digest | `sha256:6e926b5d8ef641d15a4ef623002531a5490b54154e0fa93648ff3cd61fb41bd0` |
| Extraction | `docker create` + `docker cp` (byte-exact), **never** the working-tree file |
| `DIALOG_SERVICE_PRODUCTION_BASE_SHA256` | `77aef9dcb78a92563d7fb3c1ed02ee1444e1898582673c86ebcc047c697198f6` |

The extracted bytes matched the historical audit value, so the run continued.

## 2. The audited impurity in the previous ninth file

| Item | Value |
| --- | --- |
| `DIALOG_SERVICE_DIRTY_CHECKOUT_SHA256` | `50cfd8d44ef36624153edd62fd3f38462eec05dbb7fae7571eee234ffa4b92e7` |
| Diff vs baseline | 23 insertions, exactly 2 hunks |

```
@@ -966,6 +966,20 @@ async def async_chat(dialog, messages, stream=True, **kwargs):
+    # A cross-part fallback means the mandatory baseline came from the GENERAL part of ...
+    cross_part = kbinfos.get("generic_fallback") if isinstance(kbinfos, dict) else None
+    if cross_part:
+        system_content += ( ... 通用技术规范 ... )            <-- EXCLUDED (unrelated prompt behaviour)
@@ -1084,6 +1098,15 @@ async def async_chat(dialog, messages, stream=True, **kwargs):
+        if not refs and isinstance(kbinfos, dict) and isinstance(kbinfos.get("retrieval_health"), dict):
+            refs = {"retrieval_health": deepcopy(kbinfos["retrieval_health"])}   <-- AUTHORISED (kept)
```

Origin of the excluded branch: commit **`98ffddcd5`** — "feat(rag,chat): fall back to a standard's
generic part, and give the core count a field". It is present in `HEAD` and absent from the production
baseline image, i.e. exactly the release impurity Codex flagged.

## 3. Clean reconstruction

Method (harness script `deploy/repair_gates/rebuild_clean_ninth_file.py`): **byte-level splice**, not a
text edit. Every byte of the result comes from the baseline; the 9 inserted lines are copied verbatim
from the already-validated file, so the repair text is identical to the one the RED/GREEN matrix proved.
Abort guards: unique return anchor (`len(anchors) == 1`), unique repair block, block absent from the
baseline, excluded marker absent from the result, result different from both inputs.

| Item | Value |
| --- | --- |
| `DIALOG_SERVICE_CLEAN_SHA256` | `91b8bfc6254e70e631065f3ed1bdc3ef1c11ba2a204b4c869fd9ae271171e726` |
| Lines | 2601 (baseline 2592) |
| Bytes added | 914 |
| Line endings | CRLF preserved consistently (2591 CR/LF in the baseline) |
| Anchor | after baseline line 1086, before the `decorate_answer` return |

**Purity diff — `production baseline → clean` is exactly one hunk (9 insertions):**

```
@@ -1084,6 +1084,15 @@ async def async_chat(dialog, messages, stream=True, **kwargs):
             )
             langfuse_generation.end()

+        # `retrieval_health` is retrieval OBSERVABILITY metadata, not citation content, so its survival
+        # must not depend on whether citation quotation is enabled. With quoting on, the reference is the
+        # whole retrieval dict (deepcopy(kbinfos) above) and already carries it; with quoting off nothing
+        # populated `refs`, so the health record was dropped on the floor and the degradation notice became
+        # invisible to the client. Carry the AUTHORITATIVE DTO forward in that case only: copied, never
+        # recomputed, never inferred from chunks, no default when it is absent, and the citation content
+        # stays exactly as built - `quote=False` keeps suppressing chunks and doc_aggs.
+        if not refs and isinstance(kbinfos, dict) and isinstance(kbinfos.get("retrieval_health"), dict):
+            refs = {"retrieval_health": deepcopy(kbinfos["retrieval_health"])}
         return {"answer": think + answer, "reference": refs, "prompt": re.sub(r"\n", "  \n", prompt), "created_at": time.time()}
```

`clean → dirty` residual = exactly the 14 excluded prompt lines. No other difference exists.

## 4. AST release-diff classification

`deploy/repair_gates/ast_release_diff_classify.py` (nested definitions are replaced by placeholders in
the enclosing body, so a change inside a closure never makes its parent look changed):

| Check | Result |
| --- | --- |
| Functions only in baseline / only in clean | `[]` / `[]` |
| Functions with changed own bodies | `["async_chat.decorate_answer"]` |
| Added statements | one: the `if not refs …` guard |
| Removed statements | none |
| Module-level statement kinds | equal |
| Imports | equal |
| Prompt string literals changed | no |
| **`DIALOG_SERVICE_RELEASE_DIFF`** | **`QUOTE_HEALTH_ONLY`** |

No prompt change, no `generic_fallback`, no model-selection, retrieval, citation-algorithm, answer
wording, logging or import change.

## 5. Quote-health RED/GREEN (isolated harness, per-arm in-container hash verified)

| Arm | File | Result |
| --- | --- | --- |
| RED | production `77aef9dc…` | `FAIL_AS_EXPECTED` — B/F/G/H "authoritative retrieval_health did not survive" |
| GREEN | clean `91b8bfc6…` | `PASS` — 8/8 executed, 0 failures |

Cases: A quote=True+chunks, B quote=False+chunks, C quote=True no health, D quote=False no health,
E quote=True healthy, F quote=False healthy, G quote=True zero chunks, H quote=False zero chunks.

- **A/E unchanged** in both arms (quote=True behaviour and citation content identical to baseline).
- **B/F/G/H**: `[]` → `{"retrieval_health": {…}}`; exactly one key; no citation content exposed.
- **C/D**: shape unchanged; no health invented when none is authoritative.
- **Aliasing contract**: returned health equals the authoritative DTO by value, is a *different* object,
  and mutating it downstream leaves the source `kbinfos` untouched.
- **Serialization**: after `structure_answer` + JSON, `reference.retrieval_health` is visible and the
  reference still carries `chunks`.

Harness: `deploy/repair_gates/quote_health_red_probe.py`, `quote_health_red_wrapper.py`,
`run_quote_health_matrix.ps1` (committed at `999ded504`).

## 6. Degradation differential gate

**Harness ES root cause (two defects, infrastructure only):**

1. the disposable `wenruo-repair-es` (network `wenruo-repair-test`, alias `repair-es`, `172.20.0.6:9200`)
   and `repair-redis` were `Exited (255)` → every fixture failed during setup (26 setup errors);
2. once ES was up, all 26 failed as *"async def functions are not natively supported"* because the gate
   file lives outside the config rootdir, so `asyncio_mode = "auto"` from `/ragflow/pyproject.toml` was
   not applied — fixed with an explicit `/tmp/pytest.ini` (container-local harness config).

No mocking or bypassing: the gate drives the real `Dealer.retrieval` against real ES, real lexical
fallback, real dense-failure handling, real health reporting and real result construction.

**Adjudicated invariant (gate layer only — `deploy/repair_gates/test_degradation.py`).** Byte-identical
whole-trace equality is NOT retained; `_source` is NOT globally ignored. Permitted difference is exactly
the four-field provenance widening of the first ES call, and the quartet is then removed so the remainder
must deep-equal the frozen baseline:

* `AUTHORISED_SOURCE_WIDENING = (content_prefix_kind_kwd, content_prefix_version_int, content_prefix_chars_int, content_prefix_hash_kwd)`
* each appears exactly once in the candidate and zero times in the baseline;
* the quartet is contiguous at the approved position (`AUTHORISED_SOURCE_INSERTION_INDEX = 18`, baseline
  anchor `mom_id`);
* fields before and after the quartet are byte-identical to the baseline, in original order;
* every later ES call (the vector/knn probe, which has no `_source`) must be byte-identical;
* provider call count (1), health equality and non-empty-evidence retrieval equality are asserted.

| Item | Value |
| --- | --- |
| `DEGRADATION_GATE_EXECUTED` | `YES` (26 collected) |
| `DEGRADATION_GATE_RESULT` | **`PASS` — 26 passed, 0 failed**, 83 warnings, 83.11s |

Before the adjudication the same suite was 2 failed / 24 passed, failing only on the stale
whole-trace-equality expectation.

## 7. P0 health/taxonomy bounded gate

`deploy/p0_gates/healthy_path_contract_gate.py` → **`verdict: PASS`**

* healthy path: `all_known_legs_explicitly_resolved`, `dense_is_success`, `lexical_is_success`,
  `legitimately_unused_legs_not_triggered`, `overall_is_full`, `degradation_reason_is_null`,
  `zero_contract_violations`; result keys `["chunks", "doc_aggs", "retrieval_health", "total"]`;
* negative arm (dense producer muted) still fails correctly — the gate does not self-heal.

## 8. Eight-file guard and nine-file runtime manifest

`EIGHT_FILE_HASH_GUARD = PASS` (8/8 identical to the authorised manifest, verified after all work).

| # | Path | SHA-256 |
| --- | --- | --- |
| 1 | `rag/nlp/doc_context.py` | `d0a61bda36c0632367d265ffd11bc8248637d59289f9107df333b968317a14e6` |
| 2 | `rag/nlp/retrieval_projection.py` | `5618bfb01fded4f429a51a6ecbe2714ed60f31f306b8bf606d74674b62ecab98` |
| 3 | `rag/retrieval/chunk_profile.py` | `248a6af9bcf8a83582b38b3b2c197c4405c77e72da0c6304f6931c7d8ae362da` |
| 4 | `rag/retrieval/decomposition.py` | `ee2a060d95be16acc099d18a15cc0ef630857ea6e38c047edd80d8828fdffc9f` |
| 5 | `rag/nlp/search.py` | `abdf9a25813c00dda59b393ae3cd29143a33e98409e9cbfa056a92b8c7ea6912` |
| 6 | `api/apps/restful_apis/chunk_api.py` | `e63a7ac4df731da35dc636a809e4a3ec6795df18aa81a14f5d7152b74ef9bd79` |
| 7 | `rag/svr/task_executor_refactor/dataflow_service.py` | `0132bdc4bf425d00a7dd38badb74dacd5da788ac3720d3a2d86dcbdc85ea8965` |
| 8 | `rag/advanced_rag/harness/tools/text_processing.py` | `a3007bdbb6ba95a21faf0720d8e1171e817f4d80e3b4d6fbd67e6efba6e3299d` |
| 9 | `api/db/services/dialog_service.py` | `91b8bfc6254e70e631065f3ed1bdc3ef1c11ba2a204b4c869fd9ae271171e726` |

## 9. Harness artifacts added/changed by this work

| Artifact | Kind |
| --- | --- |
| `deploy/repair_gates/rebuild_clean_ninth_file.py` | reconstruction (byte splice + abort guards) |
| `deploy/repair_gates/ast_release_diff_classify.py` | release-diff classification |
| `deploy/repair_gates/degradation_diff_diagnose.py` | structural ES-trace diff diagnostic |
| `deploy/repair_gates/test_degradation.py` | gate layer: adjudicated `_source` invariant |
| `deploy/repair_gates/quote_health_red_probe.py`, `quote_health_red_wrapper.py`, `run_quote_health_matrix.ps1` | quote-health RED/GREEN harness (earlier commit `999ded504`) |
| `/tmp/pytest.ini` inside `wenruo-repair-gates` | container-local pytest config (`asyncio_mode = auto`) |

Reproduce: `run_quote_health_matrix.ps1` (RED/GREEN + identity + eight-file guard) ·
`python -m pytest -c /tmp/pytest.ini /tmp/test_degradation.py` in `wenruo-repair-gates` with
`wenruo-repair-es` up · `python /tmp/healthy_path_contract_gate.py`.

## 10. Frozen state and non-goals

* `PRODUCTION_MUTATED = NO` — `wenruo-rag-cpu` runs `sha256:6e926b5d8ef6…`, restart count 0.
* `EXPECTED_PROJECTION_DELTA = 2` kept separate and unchanged; no baseline rewritten.
* No build, deploy, retag, production datastore access, external provider call, QGDW work or P1-2.
* Numeric adversarial design, provenance architecture, QGDW ranking, G4 and P1-2 were not reopened.
* The excluded `generic_fallback` prompt branch from `98ffddcd5` is superseded by this reconstruction;
  re-introducing it requires its own authorisation and its own acceptance evidence.

## 11. Verdict block

```
DIALOG_SERVICE_PRODUCTION_BASE_SHA256 = 77aef9dcb78a92563d7fb3c1ed02ee1444e1898582673c86ebcc047c697198f6
DIALOG_SERVICE_DIRTY_CHECKOUT_SHA256  = 50cfd8d44ef36624153edd62fd3f38462eec05dbb7fae7571eee234ffa4b92e7
DIALOG_SERVICE_CLEAN_SHA256           = 91b8bfc6254e70e631065f3ed1bdc3ef1c11ba2a204b4c869fd9ae271171e726
DIALOG_SERVICE_RELEASE_DIFF           = QUOTE_HEALTH_ONLY
GENERIC_FALLBACK_PROMPT_DELTA_PRESENT = NO
QUOTE_HEALTH_RED_RESULT               = FAIL_AS_EXPECTED (B, F, G, H)
QUOTE_HEALTH_GREEN_RESULT             = PASS (8/8)
QUOTE_TRUE_BEHAVIOR                   = UNCHANGED
QUOTE_FALSE_BEHAVIOR                  = HEALTH-ONLY REFERENCE, CHUNKS/DOC_AGGS SUPPRESSED
HEALTH_ABSENT_BEHAVIOR                = ABSENT, NOTHING SYNTHESIZED
ALIASING_CONTRACT                     = PASS
SERIALIZED_HEALTH_VISIBILITY          = VISIBLE
DEGRADATION_GATE_INVARIANT            = EXACTLY_FOUR_FIELD_SOURCE_WIDENING_AT_APPROVED_POSITION
DEGRADATION_GATE_RESULT               = PASS (26 passed, 0 failed)
P0_HEALTH_REGRESSION                  = PASS
EIGHT_FILE_HASH_GUARD                 = PASS
NINE_FILE_RELEASE_CLOSURE             = COMPLETE
SAFE_TO_BUILD_NINE_FILE_CANDIDATE     = YES
PRODUCTION_MUTATED                    = NO
```
