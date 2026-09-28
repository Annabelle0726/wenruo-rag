# Phase B P0-B — Healthy-Path Leg Attribution Repair + Re-acceptance: **P0 CORE RUNTIME: PASS**

The defect was a **producer/wiring truth defect**, exactly as diagnosed: a healthy deployed hybrid retrieval
executed successfully, but the route layer reported only `lexical=success`, erased/never reported `dense`, and
the DTO came out `overall=degraded, degradation_reason=null` — which the contract itself flags as
`SILENT_DEGRADATION`. It is now repaired at the real execution boundaries, all pre-deployment gates pass, and
the live acceptance passed end to end **without any rollback**.

Machine-readable artifact: `phase_b_p0b_leg_attribution_acceptance_result.json`

---

## Decision

| milestone | status |
| --- | --- |
| `GENERATOR_ANCHOR_GATE` | **PASS** |
| `RUNTIME_SYMBOL_BINDING_GATE` | **PASS** |
| `HEALTHY_PATH_CONTRACT_GATE` | **PASS** |
| `P0-A Health Contract` | **PASS** |
| `P0-B Production Wiring` | **PASS** |
| `P0-C Live Core Acceptance` | **PASS** |
| `P0 CORE RUNTIME` | **PASS** |
| `P0-6 User Disclosure UI` | **DEFERRED_NOT_IMPLEMENTED** |
| `C1–C6 User-visible Acceptance` | **NOT RUN / NOT IMPLEMENTED** |
| `P0-7 Operator Observability Sink` | **NOT_ACCEPTED_NOT_WIRED** |
| `P1` | **LOCKED / NOT ENTERED** |

`Phase B P0 complete` is **not** declared: P0-6, C1–C6 and P0-7 remain outstanding.

---

## 1. Where the truth defect actually was, and how it was repaired

**The route abstraction genuinely cannot distinguish the two legs.** One hybrid route call covers the dense
leg *and* the lexical leg, so the route loop cannot know which of them ran, returned, or failed. It therefore
cannot produce either fact — and the previous code did the worst thing available: it popped both legs and then
re-declared one of them (`lexical`) as `success`, erasing the real dense fact and leaving `dense` `UNKNOWN`.
It never inferred from chunk counts or route names to reach `full`, which is why the DTO was `degraded` rather
than a fabricated `full` — the honesty held, the attribution was missing.

The fact source was therefore added at **the minimal producer boundary** where each leg actually executes:

| leg | real boundary | fact produced |
| --- | --- | --- |
| `dense` | `rag/nlp/search.py::Dealer.get_vector` — the single point where the query-embedding request is issued | executed / failed (reason read from the exception, leg-aware) / not_triggered when no embedding model was supplied |
| `lexical` | `rag/nlp/search.py::Dealer.search` — the store round trip that carries the lexical expression | executed when the round trip carrying it returned / not_triggered when the question produced no lexical expression |

`health_bridge._bump` now keeps **route counters only**. It no longer pops legs and no longer declares a
success leg; on a route failure it attributes the leg only when no deeper boundary already owns it. Each leg's
attempts are counted and aggregate to exactly one status: all ok → `success`; mixed → `degraded` *with a
reason*; all failed → `failed`. So a partial failure reports honestly instead of being rounded to success or
to silence.

**Nothing forbidden was done.** `UNKNOWN` was not made neutral; an unresolved dense leg was not auto-promoted;
`validate()` was not relaxed; `degraded + null reason` was not permitted; `KNOWN_LEGS` was not altered to hide
dense; `skipped` and `not_triggered` were not mixed; dense success was never guessed from chunk counts or route
names. No retrieval parameter, routing, fusion, exception semantics, embedding model, index, prompt, reranker or
answer-policy change was made.

One deliberate, documented asymmetry, stated honestly: a dense **failure** is now reported at the embedding
boundary, so it gets a leg-accurate reason (`EMBEDDING_QUOTA_EXHAUSTED` vs `EMBEDDING_TIMEOUT` — the old
route-level text heuristic could not tell a timeout from a store error). A lexical failure is still attributed
at the route level from the store exception.

## 2. `HEALTHY_PATH_CONTRACT_GATE` — the gate that was missing

The P0-C suite hand-fills every leg in its fixtures, which is precisely how a candidate that could not run
passed 5/5 twice. This gate **never hand-fills a leg**. It drives the real candidate wiring
(pipeline → multi_route → the store layer's own producers) with only the two innermost boundaries doubled —
the embedding provider and the document store — and the DTO under test is the one the real pipeline attached.

| assertion | result |
| --- | --- |
| every `KNOWN_LEG` resolved | PASS (`dense, lexical, rerank, followup, decomposition`) |
| required dense execution explicitly observed | PASS |
| `dense = success` | PASS |
| `lexical = success` | PASS |
| legitimately unused legs explicitly `not_triggered` | PASS (`rerank`, `followup`) |
| no required leg absent/unknown | PASS |
| `overall = full` | PASS |
| `degradation_reason = null` | PASS |
| `validate() == []` | PASS |
| legacy retrieval payload unchanged | PASS (`chunks, doc_aggs, retrieval_health, total`) |
| answer-policy enforcement remains DISABLED | PASS |

**Required negative regression — the gate verifies producer truth, it does not re-implement an ideal state.**
With the dense producer silenced (simulating a producer that should have reported the leg but did not), the
gate returns **FAIL**: `dense` is missing, the DTO degrades, and `SILENT_DEGRADATION` is flagged. It does not
self-heal the missing leg into success. Both directions are asserted together, so the PASS cannot come from a
gate that would accept anything.

## 3. `GENERATOR_ANCHOR_GATE` — the accident is now a regression case

The original incident came from the generator, not the patch text: `build_multi_route_candidate` anchored its
import injection on `from rag.retrieval.rerank import`, which does not exist in the file, and `str.replace()`
returned the source unchanged **without raising**.

* every transformation anchor now declares an expected match count (`replace_exact`), and `replace_once` is the
  declared-count-1 form;
* 0 matches → hard FAIL; more than expected → hard FAIL;
* a post-transformation proof (`verify_candidate_symbols`) fails the build if any reporter symbol the candidate
  calls is not bound in the module that calls it;
* no bare `str.replace(` remains in any builder function.

| check | result |
| --- | --- |
| exactly one match succeeds | PASS |
| zero matches hard-fails | PASS |
| more than expected hard-fails | PASS |
| **stale `rerank` anchor now hard-fails** | PASS |
| incident mechanism demonstrated (old call silently no-opped) | PASS |
| no bare `replace` in builders | PASS |
| all reporter symbols bound | PASS |
| generator output byte-identical to approved build inputs | PASS |

## 4. Other pre-deployment gates

* **Existing unit tests** — the relevant subset is **255 passed** (`rag/retrieval`, `rag/test_search_*`,
  `rag/nlp/test_search_rerank`, `rag/advanced_rag/test_hybrid_search_multi_route`). The full suite is
  5965 passed / 33 skipped / 41 failed / 22 collection errors, and those failures are **pre-existing and
  environmental**: `git status` shows **no production code modified** in the repo working tree (only `deploy/`
  build inputs and the generator), and the failures are Windows GBK `UnicodeDecodeError`s, sqlite3
  unraisable-warning groups, a missing `ZHIPU_AI_API_KEY`, and collection errors for `ragflow_sdk` / the
  `tools` package / `api.apps` import roots — none touching retrieval, health or search.
* **P0-A fault injection** — 6/6 PASS, 0 silent degradation, 0 quota.
* **P0-C host injection suite** — 5/5 PASS + frozen negative control, 0 silent degradation, 0 quota.
* **Semantic-diff suite** — PASS on all four scopes. For `search.py` this is proven by AST normalisation:
  after removing reporter statements and unwrapping the single report-then-bare-re-raise handler, **every
  pre-existing function body is byte-identical to the deployed baseline** and every signature is unchanged;
  only three allowlisted helpers were added, and the only new bare-name calls are reporting. For
  `health_bridge.py`, `health.py` and `health_producers.py` are **byte-identical to the approved candidate**, so
  `full` cannot have been reached by weakening the contract.
* **`RUNTIME_SYMBOL_BINDING_GATE`** — PASS, with both directions: the frozen unbound fixture **FAILS** with the
  original `NameError`, the repaired candidate **PASSES**.
* **Image-level runtime smoke** — PASS against the actual built image: symbol binding *and* the healthy
  producer-path DTO, the latter executed inside the image with the embedding provider and store doubled and the
  provider host blocked.

## 5. Rebuild

`my-wenruorag:p0b-leg-6543f5a3` → **`sha256:8694a5b943dc…`**. Nothing was overwritten: `latest` and the rollback
tag remain `c50436820cb9`, and both earlier candidate images (`99d0ee210004`, `be80f1b49b45`) are retained. All
four changed files were hashed **in-container** and are byte-identical to the approved build inputs.

## 6. Live re-acceptance (Steps 3–7)

Premises verified before deploying: production `c50436820cb9`, credential `062bcd934443`, model
`gemini-embedding-001`, KB binding unchanged, 5 KBs. **Credential rotation was not repeated.**

**Steps 3–4 PASS** — recreated through the same Compose service with `p0b3_leg_image_override.yml` (tracked
compose file untouched, `latest` never used). Running image id exactly `8694a5b943dc`; ports, three mounts,
network, restart policy, command, ulimits preserved; environment diff empty.

**Step 5 — live healthy negative control: PASS.** Real deployed pipeline, real KB, real store, real credential,
no test doubles:

```
leg_status          = {decomposition: success, dense: success, lexical: success,
                       rerank: not_triggered, followup: not_triggered}
retrieval_health    = {overall: full, evidence_completeness: partial, degradation_reason: null}
validate()          = []            (zero contract violations)
result keys         = chunks, doc_aggs, retrieval_health, total
```

**Step 6 — frozen five injections against the deployed modules: PASS.** 5/5 with the frozen expectations
(dense 429 → `EMBEDDING_QUOTA_EXHAUSTED`; planner failure → `PLAN_VALIDATION_FAILED`; empty plan → `PLAN_EMPTY`;
lexical failure → `STORE_UNAVAILABLE`; circuit breaker → `CIRCUIT_BREAKER_OPEN`), plus the frozen negative
control (`overall=full`). Additionally, every leg is explicitly resolved, a partial retrieval still returns the
legacy payload rather than an error code, and no silent degradation occurs. Boundary-attribution checks all
pass: dense executed → success; quota → `EMBEDDING_QUOTA_EXHAUSTED`; timeout → `EMBEDDING_TIMEOUT`;
`not_triggered` **cannot** override an observed execution fact; one route ok + one failed → `degraded` with a
reason; genuinely unused legs are explicitly `not_triggered`. External quota consumed: **0**. Answer-policy
enforcement: **DISABLED**.

**Step 7 — decision: PASS, candidate retained.** No rollback. Container running with 0 restarts, ES healthy,
data sync ready, no `NameError` or fatal error in the logs.

---

## Production state at the end of the window

| item | state |
| --- | --- |
| running image | `my-wenruorag:p0b-leg-6543f5a3` = `8694a5b943dc` |
| container | running, 0 restarts, healthy |
| credential | **KEY_2 `062bcd934443`** — unchanged; no rotation, KEY_1 not restored |
| model / KB binding | `gemini-embedding-001` / `f79e37e5ab7611f18ecb3887d563fb04`, 5 KBs, unchanged |
| health signal | honest: healthy = `full`, failures carry a reason, no silent degradation |
| index / mapping / prompts / reranker | untouched |
| answer-policy enforcement | remains DISABLED |
| backing services | mysql, elasticsearch, redis, minio never restarted |

**Honesty notes carried forward.** `evidence_completeness` stays `partial` by design — the retrieval layer may
not self-certify `full`, and only an explicit authority validator may upgrade it, which is P1 scope and remains
off. The pre-existing `settings` ↔ `redis_conn` import-order fragility in this codebase is untouched and known.

Files: `phase_b_p0b_leg_attribution_acceptance_result.json`, `deploy/p0_gates/healthy_path_contract_gate.py`,
`deploy/p0_gates/generator_anchor_gate.py`, `deploy/p0_gates/semantic_diff_suite.py`,
`deploy/p0_gates/step6_frozen_injections.py`, `deploy/p0_gates/binding_gate.py`,
`deploy/p0_gates/image_runtime_smoke_result.json`,
`deploy/p0_gates/fixtures/multi_route.UNBOUND-reporter-regression.py`,
`deploy/p0_baseline/p0b3_leg_image_override.yml`, `deploy/p0_build/search.py`, the attribution repair in
`deploy/p0_build/health_bridge.py`, and the hardened `tools/scripts/p0_option_a_candidate.py`.

## Remaining work (explicitly not claimed)

P0-6 user disclosure UI, C1–C6 user-visible acceptance, and P0-7 operator observability sink remain
outstanding; P1 has not been entered.
