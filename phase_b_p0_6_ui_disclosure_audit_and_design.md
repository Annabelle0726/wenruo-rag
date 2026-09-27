# P0-6 User Disclosure UI — Audit & Design Spec (Phase 1 deliverable, **no code written yet**)

**Baseline lock:** `my-wenruorag:p0b-leg-6543f5a3` (`8694a5b943dc`), KEY_2 `062bcd934443` unchanged.
This document is read-only analysis. No code, no build, no container mutation was performed.

---

## 1. Headline audit result

> **The backend transport is already complete. `retrieval_health` reaches the browser today, unmodified, in
> every chat and search response. P0-6 is therefore a frontend-only change plus two i18n files — no backend
> edit, no new endpoint, no contract change.**

Verified in the locked image, per path:

| surface | code | what the client receives |
| --- | --- | --- |
| chat, streaming | `dialog_service.py:897` (`kbinfos = await retrieve_multi_route(...)`) → `:956` `yield {..., "reference": kbinfos, "final": True}` | the **whole** kbinfos dict, including `retrieval_health` |
| chat, non-streaming | `:1039` `refs = deepcopy(kbinfos)` → `:1087` `return {..., "reference": refs}` | same, minus chunk vectors |
| search, non-streaming | `:2010` `refs = deepcopy(kbinfos)` → `:2018` `return {..., "reference": refs}` | same |
| search, streaming | `:1999 decorate_answer` builds `refs = deepcopy(kbinfos)` → `:2035` `final = await decorate_answer(...)` | terminal frame carries it |

`deepcopy` and the `chunks_format` projection both preserve unknown top-level keys — `chunks_format`
(`rag/prompts/generator.py:41`) only rebuilds `reference["chunks"]`, it does not whitelist the parent dict.
The DTO the pipeline attached (`rag/retrieval/pipeline.py:341` `attach_retrieval_health(...)`) therefore
survives every hop.

For reference, the payload the UI can rely on is exactly the contract's `api_view()`:

```json
"retrieval_health": { "overall": "full|degraded|failed",
                      "evidence_completeness": "full|partial|insufficient",
                      "degradation_reason": "EMBEDDING_QUOTA_EXHAUSTED|…|null" }
```

## 2. Audit — current notice logic (and why it must not be reused as-is)

`web/src` has **zero** references to `retrieval_health`, `degradation_reason` or `evidence_completeness`
(verified by repo-wide search). So `USER_VISIBLE_DISCLOSURE: NOT IMPLEMENTED`, confirming the earlier audit.

Existing toast machinery:

| mechanism | file | behaviour |
| --- | --- | --- |
| global axios interceptor | `utils/next-request.ts:136-141` | toasts **only** on HTTP 413 / 504 |
| API error mapper | `utils/api-error.ts:60-83` | friendly sentence for a classified model error; otherwise capped message + code |
| toast primitive | `components/ui/message.ts` | wraps `sonner`; `error(msg, options)` **passes `ExternalToast` through**, `warning/info` do **not** accept options |
| notification wrapper | `utils/notification.ts` | wraps `sonner` with `success/error/warning/info`, no `id` support today |

Historical failure modes (from the earlier forensic audit, both confirmed there):

1. **Toast storm.** The pre-isolation path raised a hard embedding failure, and the per-request
   `.catch()` in `pages/next-search/hooks.ts:108-110` toasts per request — *N requests, N toasts*.
2. **Silence.** Route isolation turned that failure into a 200 with partial chunks, so neither the
   interceptor (only 413/504) nor the page `.catch()` fires. There is no signal at all today.

P0-6 must add the missing signal **without** reintroducing (1). That is why the design below puts the
decision in one module with explicit dedup rather than adding another per-request `.catch()`.

## 3. Audit — dedup capability that already exists

* **Structural (the strongest one).** The backend aggregates 5 sub-routes into exactly **one**
  `retrieval_health` object per retrieval call (`HealthSession.build()` is called once, at
  `pipeline.py:341`). "Five sub-routes fail → one notice" is therefore satisfied by the data model, not by
  frontend throttling. This still needs an assertion, because the frontend can receive the same DTO on
  more than one render (see §4).
* **Sonner `id`.** `sonner@^1.7.4` is installed; `toast.*(text, { id })` replaces an existing toast with
  the same id instead of stacking a duplicate. This is the anti-storm lever.
* The shared primitives in `components/ui/message.ts` and `utils/notification.ts` do **not** currently
  forward an `id`, and `components/ui/**` is under the project's **shared-UI lock** (must not be modified
  without approval). The design therefore talks to `sonner` directly from a new util — the same pattern
  both existing wrappers already use.

## 4. Audit — history replay risk (**the trap this design must avoid**)

`api/db/services/conversation_service.py:245-284` persists the reference: `conv.reference[-1] = reference`
(line 284), after `reference["chunks"] = chunks_format(reference)` (line 251) — which, as shown above,
keeps `retrieval_health` in the stored object.

Consequence: when a conversation is reloaded, the server hands the frontend messages whose `reference`
still contains `retrieval_health` from the *original* turn. A naive "notify whenever a reference has a
degradation reason" implementation would therefore **re-toast every historical degradation on every page
load** — an unbounded duplicate-notice bug, and exactly the storm class the user prohibited.

Therefore: **the notice fires only from live-response handlers, never from history hydration.** The
hydrate path (`useChatStreamStore.hydrateFromServer`) and any conversation-fetch effect must not call the
dispatcher. This is a hard requirement in §9's test plan.

Second replay source inside the live path: `hooks/logic-hooks.ts:684-734` runs in a `useEffect` on the
`answer` object, so the handler can execute more than once for one answer. A per-answer guard is required,
not optional.

## 5. Audit — security surface

The DTO is additive and already on the wire; it contains only three enumerated, non-sensitive values:
an enum status, an enum completeness and an enum reason code. It carries **no** key, endpoint, stack trace
or provider JSON. The leak risk is therefore entirely in *what we choose to render*, so the red lines are
enforceable by construction (§8).

Residual: the existing 413/504 and `api-error.ts` paths are untouched by this work and already summarize
and cap messages.

---

## 6. Design — C1–C6 mapping (the whole decision table)

Inputs: `overall`, `degradation_reason`, `evidence_completeness`, all read from
`reference.retrieval_health`. Everything else is ignored.

| # | condition | UI behaviour | tone | i18n key |
| --- | --- | --- | --- | --- |
| C1 | `overall === 'full'` | **silent** — no toast, no badge, nothing | — | — |
| C2 | absent / malformed `retrieval_health` (old backend, non-dict reference) | **silent**, fail-safe | — | — |
| C3 | `degraded` + `reason === 'EMBEDDING_QUOTA_EXHAUSTED'` + `evidence_completeness ∈ {partial, full}` | one friendly, lightweight notice | `warning` | `semanticLimited` |
| C4 | `degraded` + `reason === 'EMBEDDING_QUOTA_EXHAUSTED'` + `evidence_completeness === 'insufficient'` | generic degraded notice (see note) | `warning` | `degradedGeneric` |
| C5 | `degraded` + any other / null reason | one generic degradation notice | `warning` | `degradedGeneric` |
| C6 | `failed` | one explicit retrieval-failure notice | `error` | `retrievalFailed` |
| — | any unrecognised `overall` | **silent** (never invent a state) | — | — |

**Why C3's wording is provably true, not marketing.** The proposed C3 string asserts a text-search
fallback. That claim is derivable from the two fields we have, using the contract's own aggregation rules
(`rag/retrieval/health.py:177-186`, `EVIDENCE_LEGS = ("lexical","dense")`):

1. `overall === 'failed'` ⟺ **all** active evidence legs are `FAILED`; `overall === 'degraded'` ⟹ not all
   of them failed ⟹ at least one evidence leg survived.
2. `reason === 'EMBEDDING_QUOTA_EXHAUSTED'` identifies the **dense** (embedding) leg as the failure
   (`reason_from_exception(exc, "dense")` is the only producer of that code).
3. The evidence legs are lexical and dense; dense failed, so the surviving evidence leg is **lexical**.

One honest caveat drove the C4 split: a `SKIPPED` lexical leg (circuit breaker) is *not* `FAILED`, so step 1
alone does not prove lexical produced hits. `evidence_completeness === 'insufficient'` is precisely the
signal for "little or no evidence came back", so C4 downgrades that corner to the generic wording instead
of overclaiming a fallback. This is why the mapping uses a third field rather than the two named in the
brief — the extra field is already present, so no backend change is needed.

Proposed strings (the only user-facing text; both files, nothing else):

| key | `zh.ts` | `en.ts` (sentence case per `web/CLAUDE.md`) |
| --- | --- | --- |
| `semanticLimited` | 语义检索暂时受限，已自动切换为文本检索模式。 | Semantic search is limited right now; the answer fell back to text search. |
| `degradedGeneric` | 检索服务已降级，本次回答可能不完整。 | Retrieval was degraded, so this answer may be incomplete. |
| `retrievalFailed` | 检索失败，未能取得知识库内容，本次回答可能不准确。 | Retrieval failed, so no knowledge base content was used and this answer may be inaccurate. |

## 7. Design — dedup architecture (the "1 toast only" assertion)

One new module owns the whole decision; call sites only hand it a reference.

```
reference.retrieval_health ──► noticeForRetrievalHealth(health)      // pure, C1–C6, testable
                                        │ null for full/missing/unknown
                                        ▼
                               notifyRetrievalHealth(reference, answerKey)   // the ONLY toast caller
                                        │
                     ┌──────────────────┼───────────────────────┐
                     ▼                  ▼                       ▼
        per-answer guard        category cooldown        sonner `id`
        (same answer never      (concurrent/failing      (identical notice
         notifies twice)         requests can't stack)    replaces, not stacks)
```

* **per-answer guard** — a short-lived set keyed by the answer identity + category. Required because
  `logic-hooks.ts` handlers run from a `useEffect` and the stream flushes repeatedly.
* **category cooldown** — at most one notice per category per ~10 s window, so five concurrent failures
  cannot produce five toasts.
* **sonner `id`** — a stable id per category (`retrieval-notice:<category>`); an identical notice
  supersedes its predecessor rather than adding a second card.
* The dedup state is module-level and deliberately **not** persisted: a new answer after a page reload is
  allowed to inform the user again, but a reloaded *historical* reference never notifies (it never reaches
  the dispatcher at all — §4).

## 8. Design — security red lines, enforced by construction

| red line | how it is structurally impossible |
| --- | --- |
| API key / endpoint / credential | never read by the notice module; the DTO contains no such field |
| stack trace, provider error JSON, raw exception text | the module never receives an exception or a message string — only the health object |
| raw enum leakage | `degradation_reason` and `overall` are used **only as lookup keys**; neither is ever rendered or interpolated |
| unknown/new enum values | unmatched values map to *silent*, never to "show the raw value" |
| payload dumping | nothing new logs the DTO; no `console.*` added in production paths |
| over-broad rendering | the notice renders one of three fixed i18n strings; there is no string-concatenation path |

The test suite asserts these by feeding hostile shapes (a DTO with an injected key-like string, an
unknown reason, an `Error`-shaped value) and asserting the rendered text equals the i18n constant exactly
and contains no fragment of the input.

---

## 9. Concrete code scope (for confirmation)

### New files (2)

| file | purpose | approx |
| --- | --- | --- |
| `web/src/utils/retrieval-health-notice.ts` | C1–C6 mapper (pure) + dedup dispatcher + sonner call | ~110 lines |
| `web/src/utils/__tests__/retrieval-health-notice.test.ts` | C1–C6 table, dedup, replay, hostile-input, no-leak assertions | ~180 lines |

### Modified files (5)

| file | change | why |
| --- | --- | --- |
| `web/src/interfaces/database/chat.ts` | add `IRetrievalHealth` + optional `retrieval_health?: IRetrievalHealth` on `IReference` (line ~147) | **shared type, additive & optional** — needs your explicit OK per the project's shared-schema rule |
| `web/src/pages/next-chats/chat-stream/run-stream.ts` | dispatch once at the terminal frame (`chunk.final`, ~line 107) using `merged.reference` | primary chat surface; exactly one dispatch per answer |
| `web/src/hooks/logic-hooks.ts` | dispatch in `addNewestAnswer` (684) and `addNewestOneAnswer` (705) | legacy SSE chat: multi chat box, shared-chat page, agent chat |
| `web/src/pages/next-search/hooks.ts` | dispatch in the terminal-frame effect (472-482) | search surface |
| `web/src/locales/zh.ts`, `web/src/locales/en.ts` | 3 keys each, under a new group | project rule: only these two locale files |

### Deliberately NOT touched

`src/components/ui/**` (locked), `utils/notification.ts` and `utils/message.ts` (no signature change
needed), `utils/api-error.ts` + `next-request.ts` (their 413/504 and model-error behaviour is unrelated and
stays exactly as is), any backend file, `docker/docker-compose.yml`, the credential, and all retrieval code.
The route-isolation and exception-handling logic is untouched — the frontend never sees a raw exception
from this path, and nothing is re-thrown or surfaced.

### Open decisions needing your call

1. **`IReference` additive field** — confirm the shared-type edit (§9 row 1), or I keep the type local to
   the new module and cast at the call sites (uglier, but zero shared-type churn).
2. **C4 wording split** — keep my evidence-completeness refinement (§6 note), or always use the friendly
   text for every `EMBEDDING_QUOTA_EXHAUSTED` (simpler; slightly overclaims in the circuit-breaker corner).
3. **Surface** — toast (recommended; matches "弹出 1 次提示" and reuses the existing, already-audited
   `sonner` stack), or an inline notice under the answer (no toast at all, but needs a new presentational
   component and a render slot in `next-message-item`).
4. **Cooldown length** — default 10 s per category. Say the word if you want it larger/tiny.

## 10. Acceptance plan (C1–C6, to run after the rebuild)

Dedup and security are only provable against a real browser, so acceptance drives Chrome over CDP against
the running stack (the project's documented approach) with the response body intercepted to inject the four
DTO shapes — real quota exhaustion is **not** manufactured, consistent with every earlier round.

| # | injected DTO | assertion |
| --- | --- | --- |
| C1 | `overall=full` | zero toasts, zero notices, in DOM and in the sonner container |
| C2 | no `retrieval_health` | zero toasts |
| C3 | `degraded` + `EMBEDDING_QUOTA_EXHAUSTED` + `partial` | exactly 1 toast, text equals the `semanticLimited` string |
| C4 | `degraded` + `EMBEDDING_QUOTA_EXHAUSTED` + `insufficient` | exactly 1 toast, generic text |
| C5 | `degraded` + `STORE_UNAVAILABLE` | exactly 1 toast, generic text |
| C6 | `failed` | exactly 1 toast, failure text |
| D1 | five sub-routes degraded in one response | **exactly 1** toast (structural, asserted) |
| D2 | reload a conversation whose stored reference was degraded | **zero** toasts (replay guard) |
| D3 | five concurrent degraded answers | at most 1 toast per category (cooldown + `id`) |
| S1 | hostile DTO (key-like string, unknown reason, Error shape) | no fragment of the input appears in the DOM or toast text |
| S2 | any notice | rendered text equals an i18n constant exactly; no enum value rendered |

Also re-run: the frontend unit suite (`npm run test`) and the repo gates from the previous window to prove
no regression (`GENERATOR_ANCHOR_GATE`, `RUNTIME_SYMBOL_BINDING_GATE`, `HEALTHY_PATH_CONTRACT_GATE`) — the
backend is unchanged, so those are expected to remain PASS and are cheap to confirm.

## 11. Rebuild / deploy consequence (needs separate authorization)

The web bundle is baked into the image (`WEB_DIST_MODE`). A UI change therefore **cannot** be applied to the
running container without a rebuild:

`deploy/p0_build/Dockerfile` currently COPYs only the Python delta. Two options to present at that stage:
(a) add a frontend build stage so the derived image carries a rebuilt `web/dist`; or
(b) do a normal `docker compose build` for the release path (the standing phase-Dockerfile caveat).
Either way it produces a **new immutable tag**; `latest`, the rollback tag and all three earlier candidate
images stay untouched, and a failed acceptance rolls back to `p0b-leg-6543f5a3`.

## 12. Explicitly out of scope for P0-6

Answer-policy enforcement stays DISABLED (`decide_answer_action`/`required_notice` still have no call site —
this work is UI disclosure of an already-collected signal, not refusal behaviour). The agent/canvas
retrieval tool (`agent/tools/retrieval.py:309`) projects only `chunks`/`doc_aggs` and drops the DTO — that
surface is **not** covered by C1–C6 and is not touched. P0-7 (operator sink) remains unwired and separate.

---

**Status: awaiting confirmation of §9 (scope, incl. the shared-type edit) and the four open decisions in §9
before any code generation or rebuild.**
