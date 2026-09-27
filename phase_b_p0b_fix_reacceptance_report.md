# Phase B P0-B — Wiring Repair + Re-acceptance: **FAIL — ROLLED BACK**

The authorised repair was made, every pre-deployment gate passed, the candidate was rebuilt under a new
immutable tag and deployed. **The live negative control then failed on a second, independent wiring
defect** that the first defect had been hiding. Per the sequence the injections were suppressed, production
was recreated back onto the verified image, and the window stopped in a stable state.

Machine-readable artifact: `phase_b_p0b_fix_reacceptance_result.json`

---

## Decision

| item | status |
| --- | --- |
| `RUNTIME_SYMBOL_BINDING_GATE` | **PASS** (new gate, wired to a regression fixture) |
| `P0-A Health Contract` | **PASS** (host regression 6/6) |
| `P0-B Production Wiring` | **FAIL** — binding repaired and gate-verified, but the healthy-path leg wiring is still incomplete |
| `P0-C Live Core Acceptance` | **FAIL** — live negative control failed on a contract violation |
| `P0 CORE RUNTIME` | **NOT ESTABLISHED / FAIL** |
| `P0-6 User Disclosure UI` | **DEFERRED_NOT_IMPLEMENTED** |
| `C1–C6 User-visible Acceptance` | **NOT RUN / NOT IMPLEMENTED** |
| `P0-7 Operator Observability Sink` | **NOT_ACCEPTED_NOT_WIRED** |
| `P1` | **LOCKED / NOT ENTERED** |

`P0 CORE RUNTIME: PASS` is **not** used. `Phase B P0 complete` is **not** declared.

---

## 1. The authorised repair

One line, and nothing else. `deploy/p0_build/multi_route.py`:

```diff
 from typing import Any, Sequence
+
+from rag.retrieval.health_bridge import report_route_failure, report_route_success
```

`deploy/p0_baseline/multi_route.p0-candidate-fixed.py` archives the repaired candidate. No retrieval
refactor, no exception-boundary change, no `_guard` control-flow change, no `RouteResult` change, no
parameter, prompt, reranker, embedding-model, answer-policy or index change.

**Root cause of the original incident, now proven.** The incident did not come from the patch text — it came
from the *generator*: `tools/scripts/p0_option_a_candidate.py::build_multi_route_candidate` anchored its
import injection on the literal `from rag.retrieval.rerank import`, which **does not exist anywhere in
`multi_route.py`**. `str.replace()` returned the source unchanged without raising, and that third
`.replace()` call in the chain carried no match-count assertion. The build therefore produced a candidate
that called two symbols it never bound, and both existing gates passed it: the semantic gate compared call
sites, and the frozen harness never imported the deployed module.

## 2. Semantic-diff re-run + delta proof: PASS

The original approved gate was re-run against the repaired candidate with the deployed baseline as the base —
all reporter-only properties hold for both files.

More importantly, the explicit proof requested: **apart from the reporter symbol binding/import, the
previously approved candidate semantics are unchanged.**

| delta check | result |
| --- | --- |
| `every_function_body_byte_identical_in_ast` | **PASS** — every function in the old and new candidate is AST-identical |
| `no_module_level_node_removed` | PASS |
| `exactly_one_module_level_node_added` | PASS |
| `added_node_is_the_reporter_import` | PASS (`rag.retrieval.health_bridge`) |
| `added_import_binds_exactly_the_two_reporters` | PASS |
| `reporter_call_sites_identical` | PASS |
| `no_lines_removed_textually` | PASS |

The entire textual difference is those two added lines. `_guard`'s control flow, the exception boundary, the
return values and the `RouteResult` construction are untouched — proven at AST level, not by inspection.

## 3. `RUNTIME_SYMBOL_BINDING_GATE`: PASS

New gate at `deploy/p0_gates/binding_gate.py`. It does not compare call sites: it imports the candidate module
**in the candidate runtime environment** and then actually executes both reporter paths, asserting that each
reporter leaves an observable trace in the health session (so "it ran" is proven, not merely "it didn't
throw").

**The incident is now a regression case:**

| subject | verdict | evidence |
| --- | --- | --- |
| **old** candidate (`multi_route.p0-candidate.py`) | **FAIL** (exit 1) | reporters unbound; reproduced `NameError: name 'report_route_failure' is not defined` — exactly the production failure |
| **fixed** candidate | **PASS** (exit 0) | both reporters bound/callable and bound to the approved `health_bridge` implementation; success path executed (session legs `{lexical: success}`); failure path executed (session legs `{dense: degraded}`); failure reporter did not escape the `_guard` handler; no `NameError`, no `ImportError` |

Run with `--network none` and test doubles at the embedding/store boundary, so zero external quota was
structurally guaranteed rather than merely intended.

## 4. Build under a new immutable tag: PASS

`my-wenruorag:p0b-fix-b72e9540` → **`be80f1b49b45`**. Nothing was overwritten:

| tag | id |
| --- | --- |
| `my-wenruorag:latest` | `c50436820cb9` (untouched) |
| `my-wenruorag:rollback-pre-p0-20260927` | `c50436820cb9` (untouched) |
| `my-wenruorag:p0b-891572a71` | `99d0ee210004` (failed candidate, retained as the regression fixture) |
| `my-wenruorag:p0b-fix-b72e9540` | `be80f1b49b45` (new) |

All five retrieval files inside the built image were hashed **in-container** and are byte-identical to the
build inputs (an earlier host-side extraction differed only because PowerShell re-encoded the bytes).

## 5. Image-level runtime smoke gate: PASS

Executed with `docker run --rm --network none` against the actual built image, with `--entrypoint` overridden
and the real package imported from inside the image (`rag.retrieval.multi_route` →
`/ragflow/rag/retrieval/multi_route.py`): import succeeded, both reporter paths executed, no `NameError`.
The image that may reach a production recreate now has proof that its new wiring runs in the image runtime.

## 6. Existing regressions: PASS

P0-A host fault injection 6/6 PASS; P0-C runtime injection 5/5 PASS plus its negative control; zero silent
degradation, zero external quota in both.

---

## 7. Live re-acceptance: **FAIL**

Premises verified before deploying: production `c50436820cb9`, credential `062bcd934443`, model
`gemini-embedding-001`, KB binding unchanged. Credential rotation was **not** repeated.

**Steps 3–4 PASS.** Recreated via the same Compose service with `p0b2_fix_image_override.yml` (tracked
compose file untouched, `latest` never used). Running image id exactly `be80f1b49b45`; ports, three mounts,
network, restart policy, command, ulimits preserved and the environment diff was empty.

**Step 5 FAIL — and it is a genuinely different defect.** The `NameError` is gone: no exception, usable
evidence returned, `retrieval_health` present, the three original keys preserved. But the health DTO the
healthy path produced is dishonest:

```
leg_status          = {decomposition: success, lexical: success, rerank: not_triggered, followup: not_triggered}
dense               = ABSENT (never reported)
retrieval_health    = {overall: degraded, evidence_completeness: partial, degradation_reason: null}
validate()          = ["SILENT_DEGRADATION: status is not full but no reason code is present"]
```

**Root cause — `health_bridge._bump`.** On a successful hybrid route only one evidence leg is marked
successful, and the name chosen is `lexical`; `dense` is popped and never re-reported, so it stays
`UNKNOWN`. Since `KNOWN_LEGS` includes `dense` and `NEUTRAL` is only `not_triggered`, that unknown leg stays
active, the aggregator can therefore **never** return `full`, and the contract correctly flags the result as
silent degradation.

This is the single defect P0-B exists to close, still open on the healthy path: **every healthy production
retrieval would emit a contract-violating health DTO**, making the health signal unusable. It was invisible
until now because the `NameError` aborted every retrieval before the DTO was built — the first defect was
masking the second.

Corroborated independently by the binding gate's success path (test doubles, zero quota), which reported the
same shape: `{lexical: success}`, `dense` absent.

**Not repaired, deliberately.** The fix changes *how legs are reported* — reporter/health-wiring semantics —
which this window's authorisation explicitly excluded; scope was limited to symbol binding/import.

**Step 6 — injections not run.** The sequence requires the negative control to pass first, so no injection was
run and no synthetic 429 was manufactured.

**Step 7 — rollback.** Recreated through the same Compose service onto `rollback-pre-p0-20260927` =
`c50436820cb9`, identity re-verified, no in-place fix. Production confirmed serving: **7 chunks, 2 document
aggregates, no exception**.

---

## Production state at the end of the window

| item | state |
| --- | --- |
| running image | `my-wenruorag:rollback-pre-p0-20260927` = `c50436820cb9` |
| container | running, 0 restarts, data sync ready |
| ports / mounts / network / env | identical to pre-window |
| credential | **KEY_2 `062bcd934443`** — unchanged this window; KEY_1 not restored |
| model / KB binding | `gemini-embedding-001` / `f79e37e5ab7611f18ecb3887d563fb04`, 5 KBs, unchanged |
| retrieval | serving |
| repaired candidate | `p0b-fix-b72e9540` = `be80f1b49b45` retained, not deployed |

Credential isolation held: the credential was neither re-rotated nor rolled back. Evidence does not implicate
it — the dense leg did execute against the real provider and returned usable evidence, and the rolled-back
image serves retrieval with KEY_2.

Files: `phase_b_p0b_fix_reacceptance_result.json` (this artifact), `deploy/p0_gates/binding_gate.py`,
`deploy/p0_gates/semantic_diff_rerun.py`, `deploy/p0_gates/semantic_diff_rerun_result.json`,
`deploy/p0_baseline/p0b2_fix_image_override.yml`, `deploy/p0_baseline/multi_route.p0-candidate-fixed.py`,
and the one-line repair in `deploy/p0_build/multi_route.py`.

## What the next window needs

1. **Authorise the `health_bridge._bump` leg-reporting fix** — report both evidence legs on a successful
   hybrid route (or explicitly report the leg that did not run), so a healthy route yields
   `dense = success` and `lexical = success`.
2. **Add a healthy-path contract gate**: a live retrieval must yield `overall = full`,
   `degradation_reason = null`, every `KNOWN_LEG` explicitly resolved, and zero `validate()` violations. The
   unit and injection suites cannot see this class of defect because their fixtures report each leg by hand —
   which is precisely how a broken candidate passed 5/5 injections twice.
3. **Harden the candidate generator**: every `.replace()` anchor in
   `tools/scripts/p0_option_a_candidate.py` must assert its match count, so a stale anchor fails the build
   instead of silently emitting a candidate with a missing import.
4. Then re-run the full pre-deployment gate set and Steps 3–7, negative control first.

Status: core deployment FAIL and rolled back; production stable; P0-6, C1–C6 and P0-7 outstanding; P1 not
entered.
