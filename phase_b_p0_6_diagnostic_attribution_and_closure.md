# P0-6 Diagnostic Attribution — Four-Stage Trace, First Divergence, and Phase B P0 Closure

**The previously reported "product-path defect" was a defect in my acceptance harness, not in the product.**
The diagnostic build proved the P0-6 notice chain works end to end, C1–C6 then passed 5/5 against the real
production bundle, and the agreed promotion sequence was executed to completion.

---

## 1. Diagnostic and production build provenance

| build | tag | image id | deployed |
| --- | --- | --- | --- |
| **production (at acceptance time)** | `my-wenruorag:p0-6-ui-copy-984e7036` | **`bf990b5846f4`** | yes (now superseded) |
| **diagnostic (throwaway)** | `my-wenruorag:p0-6-ui-diag-40cc959e` | **`7796e6ab2e26`** | **never deployed** |
| P0-7 observability | `my-wenruorag:p0-7-obs-9f3d2c79` | **`ea93cd3bb795`** | deployed, now the baseline |
| rollback anchor | `my-wenruorag:rollback-pre-p0-20260927` | `c50436820cb9` | retained |

The diagnostic build instrumented **only** `web/src/utils/retrieval-health-notice.ts` and was served to the
browser by intercepting non-API requests (the real origin and real backend were used unchanged). The
production source was then reverted and verified: **0 tracked changes, 0 instrumentation references**.

Two build facts worth recording:

* Production terser sets `drop_console: true`, so a console-based probe is **silently stripped**. The
  diagnostic therefore recorded into `window.__P06_DIAG` — which also satisfies "never pollute production
  logs" and "never log sensitive data": only `overall`, `evidence_completeness` and `degradation_reason`
  were captured, never a response body.
* The production bundle was **not** modified: no retag of `latest` and no deployment happened until after
  C1–C6 passed.

## 2. Four-stage trace matrix (C1 / C3 / C4)

Real send path: `/chat/ccddcfdeba3a11f1a4910547a12ee1d1?conversationId=8878fd6aba4311f1a14689aca29561bb`,
a plain `Enter`, intercepted `POST /api/v1/chat/completions`, production SSE framing, only
`retrieval_health` substituted.

| point | C1 `full` | C3 `degraded` | C4 `failed` |
| --- | --- | --- | --- |
| **A** data received — `retrieval_health` present on the mapper's input | **present** (`reference_keys` includes `retrieval_health`; `overall=full`) | **present** (`overall=degraded`, `EMBEDDING_QUOTA_EXHAUSTED`) | **present** (`overall=failed`, `STORE_UNAVAILABLE`) |
| **B** mapper — invoked + returned | invoked, **returned `null`** | invoked, **returned `degraded`** | invoked, **returned `failed`** |
| **C** Sonner — invoked / count / threw | **0 calls** | **1 call, `threw: false`** | **1 call, `threw: false`** |
| **D** DOM — toast node after the call | **0 nodes** | **`toast_nodes: 1`** (t+300 ms) | **`toast_nodes: 1`** (t+300 ms) |

Trace counts per run: C1 `{A:1, B:1, C:0, D:0}`; C3 `{A:1, B:1, C:2, D:2}`; C4 `{A:1, B:1, C:2, D:2}`.
Every case had exactly one intercepted completion and the stub answer rendered, proving the terminal frame
reached the driver.

## 3. Exact First Divergence

> **There is no divergence in the product path. The divergence was in the acceptance harness's DOM sampling
> window.**

Applying the agreed decision matrix to the trace:

| rule | outcome |
| --- | --- |
| A has no data → frame/reference/argument binding | **not the case** — A present all three runs |
| A present + mapper invoked + returned `null` → mapper classification | **not the case** — mapper returned the right kind for C3/C4, and correctly `null` for C1 |
| mapper returned a kind + C not executed → mapper→notification control flow | **not the case** — C executed exactly once, `threw: false` |
| C executed once + D DOM empty → Sonner call/config/render | **D was NOT empty** — `toast_nodes: 1` |

So all four points were healthy. The earlier "0 toasts" arose because the acceptance script queried
`[data-sonner-toast]` **after** sonner's `NOTICE_DURATION_MS = 4000` lifetime had elapsed (it sampled at
~5–7 s post-send). The trace's own DOM probe at **t+300 ms** found the node, which is decisive.

**Corrected classification: TEST_HARNESS_STATE_ARTIFACT (sampling window).** Product-path defect claim
withdrawn — it was mine. The sampling window is now 1500 ms, inside the toast lifetime, and is the single
harness change that turned C3/C4 green.

## 4. Minimal Product Fix Proposal

**For the P0-6 notice path: none required.** The four-stage trace shows the chain is correct, and no product
file was changed to make it pass.

Two non-blocking observations, offered as backlog only (both explicitly **not** fixed in this window, per
instruction):

1. **Frontend API Shape Validation Debt** — `useFetchSessionList` types its payload as `IConversation[]`,
   declares `initialData: []`, then returns `data.data` unvalidated, so a non-array response (e.g.
   `{"code":108,"data":false}`) reaches `dialogList.find(...)` in `next-chats/chat/index.tsx:152` and drops
   the page into its error boundary. Minimal fix if ever authorised: normalise at the hook boundary
   (`Array.isArray(data.data) ? data.data : []`) and surface the API's message instead of crashing.
2. **Toast lifetime vs. disclosure** — `NOTICE_DURATION_MS` is 4000 ms. If operators later want the
   degradation notice to persist until dismissed, that is a copy/UX decision, not a defect.

## 5. C1–C6 Final Matrix (browser, production bundle)

| case | expected | observed | result |
| --- | --- | --- | --- |
| C1 `full` | silent | 0 toasts | **PASS** |
| C2 no `retrieval_health` | silent | 0 toasts | **PASS** |
| C3 `degraded` | exactly 1, exact approved zh copy | 1 toast, `exact_match: true` | **PASS** |
| C4 `failed` | exactly 1, exact approved zh copy | 1 toast, `exact_match: true` | **PASS** |
| C5 history hydrate | silent (no re-notify) | 0 toasts | **PASS** |
| — | removed exaggerated phrase absent | absent | **PASS** |
| — | zero sensitive leaks | none | **PASS** |

**C1–C6 BROWSER ACCEPTANCE: 5/5 — PASS.**

## 6. Live P0-7 Acceptance (from `docker logs`)

Triggered real retrievals through the app process on the deployed P0-7 image and read the container log:

```
INFO 44 [RetrievalHealth] {"contract_valid": true, "event": "retrieval_health",
 "evidence_completeness": "insufficient",
 "legs": {"decomposition":"success","dense":"failed","followup":"not_triggered",
          "rerank":"not_triggered","selection":"degraded"},
 "overall": "degraded", "reason": "EMBEDDING_UNAVAILABLE",
 "routes_attempted": 1, "routes_succeeded": 0, "schema_version": "1.0"}
```

| requirement | result |
| --- | --- |
| exactly the 9 approved fields | **PASS** — 9/9, no extras |
| one event per retrieval | **PASS** — 1 retrieval → 1 line, 2 → 2, 3 → 3 (proven by repeating) |
| exactly-once within a retrieval | **PASS** — no double emission |
| no sensitive content | **PASS** — no prompt, chunk content, key, endpoint, provider body or stack trace |
| reflects reality honestly | **PASS** — reports the live provider location restriction as `degraded` / `EMBEDDING_UNAVAILABLE` with `contract_valid: true` |

## 7. Promotion executed (strict order)

| step | action | verification |
| --- | --- | --- |
| 1 | C1–C6 PASS | 5/5 (§5) |
| 2 | `latest` → `bf990b5846f4` | mapping verified |
| 3 | deploy `p0-7-obs-9f3d2c79` = `ea93cd3bb795` | running image id exact; health chain present; 0 restarts |
| 4 | live P0-7 log acceptance | §6 PASS |
| 5 | promote P0-7 to baseline: `latest` → `ea93cd3bb795` | verified |

Final mapping: `latest` = `my-wenruorag:p0-7-obs-9f3d2c79` = **`ea93cd3bb795`**;
`rollback-pre-p0-20260927` = **`c50436820cb9`** (retained); all earlier candidates retained.

## 8. Phase B P0 Closure Verdict

**P0 CORE RUNTIME: PASS. P0-6 and P0-7 are delivered and in production.** The core P0 objectives — an
honest health contract, producer-truth wiring, live core acceptance, user disclosure, and an operator
observability sink — are all met and evidenced.

| milestone | status |
| --- | --- |
| P0-A Health Contract | **PASS** |
| P0-B Production Wiring | **PASS** |
| P0-C Live Core Acceptance | **PASS** |
| **P0 CORE RUNTIME** | **PASS** |
| P0-6 User Disclosure UI | **PASS** — deployed, C1–C6 5/5 |
| C1–C6 User-visible Acceptance | **PASS (5/5 browser)** |
| P0-7 Operator Observability | **PASS** — log-first event live, exactly-once, 9 fields, no leaks |
| P1 | **LOCKED / NOT ENTERED** |

**`Phase B P0 complete` — the remaining caveats, stated plainly rather than buried:** the dense (embedding)
leg is still unavailable for an **external provider reason** (`400 FAILED_PRECONDITION: User location is not
supported`), so production currently answers with `degraded / EMBEDDING_UNAVAILABLE` — now **visible to
users and operators** instead of silent. That is a provider/geo-policy matter outside P0's scope, and P0's
own acceptance (which is about honest reporting, not provider availability) passes with it present.

**Outstanding, explicitly not done:** the shape-validation debt in §4 (log-only), the recommended
`EMBEDDING_LOCATION_RESTRICTED` reason code (deliberately not added — no taxonomy change was authorised),
and P1.
