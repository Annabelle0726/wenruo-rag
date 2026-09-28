# Historical Forensic Audit — Embedding-Failure Toasts and the Silent-Degradation Transition

Read-only throughout: no old Toast restored, no front-end or back-end code changed, no exception-propagation
change, no DB access, no container recreate. All evidence is from Git history and the working tree.

## 1. Verdict on the two statuses

| statement | verdict |
| --- | --- |
| `CURRENT retrieval_health-based user notice` | **NOT IMPLEMENTED** (confirmed) |
| `HISTORICAL embedding failure toast` | **SOURCE IDENTIFIED** — was `SOURCE UNDER AUDIT`, now located |

## 2. Hypothesis verification

### 2.1 Old path — CONFIRMED

The mechanism the user described is present in the code and is the *pre-multi-route* behaviour:

1. **Hard failure at the embedding layer.** `../rag/llm/embedding_model.py` wraps every failure:
   `raise embedding_failure("GeminiEmbed", str(_e))`. A quota 429 therefore became a raised exception, not a
   degraded result.
2. **Per-request toast in the Search page.** `web/src/pages/next-search/hooks.ts:108-110`

   ```ts
   } catch (error: any) {
     message.error(error.message);
   }
   ```

   This `.catch()` is **per request**, not global — so N concurrent search requests produce **N toasts**,
   which is exactly the "multiple toasts stacked on screen" the user observed. `web/src/pages/next-searches/hooks.ts:63,294`
   carries the same pattern (`message.error(t('message.error', { error: error.message }))`).
3. **A user-friendly mapping was subsequently added** — this is the optimisation the user requested, and it
   is commit **`a785e1842` — `fix(errors): report a model refusal as a sentence, not the provider's JSON`**:

   | file | change |
   | --- | --- |
   | `../common/model_errors.py` | **new**, 125 lines — backend model-error classification (`model_failure_response`) |
   | `../rag/llm/embedding_model.py` | +89 lines — embedding failure handling |
   | `../api/apps/restful_apis/search_api.py` | 28 lines — error frame for the answer stream |
   | `../api/utils/api_utils.py` | +13 lines |
   | `../web/src/components/model-service-unavailable/index.tsx` | **new**, 75 lines — the user-visible surface |
   | `../web/src/locales/en.ts` / `zh.ts` | +6 / +5 — the human wording |
   | `../web/src/interfaces/database/dataset.ts` | +6 — the new error_type field |

   The commit message and diff are explicit about intent: *"A model provider refusing the request answers
   with the same wording the rest of the API uses, so the answer bubble reads as a sentence rather than as
   the provider's JSON body."* The front-end helper that consumes it is
   `web/src/utils/api-error.ts:68` — `message.error(i18n.t(modelServiceErrorMessageKey(modelServiceError)))`,
   capped for a toast (`api-error.ts:29`), with the contract asserted by
   `web/src/utils/__tests__/next-request.test.ts:59` — *"The whole point: the upstream JSON must not reach a
   toast."*

### 2.2 Current path — CONFIRMED

1. **Route isolation swallows the failure.** `rag/retrieval/multi_route.py:323-325`

   ```python
   except Exception as exc:  # noqa: BLE001 - one dead route must not sink the others
       _LOG.warning("[Multi-route] route %r failed: %s", query[:80], exc)
       return RouteResult(query=query, failed=True)
   ```

2. **The caller still gets a success shape.** The retrieval entry returns a normal dict
   (`chunks`, `doc_aggs`, `total`) built from the surviving routes — with the current candidate it additionally
   carries `retrieval_health`, but the HTTP status and `code` are unchanged.
3. **The global interceptor does not toast on success.** `web/src/utils/next-request.ts:136-141` toasts only
   for `413` and `504`:

   ```ts
   if (response?.status === 413 || response?.status === 504) {
     message.error(RetcodeMessage[response?.status as ResultCode]);
   }
   ```

   A 200 response therefore never enters the toast path.
4. **The Search page's `.catch()` never runs**, because the promise resolves. Result: **zero toasts**, the
   answer is produced from partial evidence, and neither the operator nor the user is told. This is the
   silent degradation characterised in the Phase A round, and it is a direct consequence of the successful
   route-isolation hardening — the very change that stopped the crash also removed the only user-visible
   signal.

### 2.3 The precise delta

| aspect | old path | current path |
| --- | --- | --- |
| embedding 429 outcome | raised hard failure | isolated at the route boundary, `failed=True` |
| HTTP / `code` | failure frame (`_error_frame`, `code: 500`) or rejected promise | success, partial chunks |
| front-end trigger | per-request `.catch()` in the Search page → **N toasts for N requests** | interceptor toasts only on 413/504 → **no toast** |
| wording | provider JSON, later replaced by `model_errors` sentences (a785e1842) | nothing |
| user perception | noisy but explicit | silent |

**Interpretation:** the "multiple toasts" and the "user-friendly wording" work belong to the *pre-isolation*
era and were the symptom of hard failure. The isolation fix removed the symptom *and* the signal. The correct
end state is not to restore the old toasts (they were per-request, duplicated, and raw), but to drive a
single, deliberate notice from the structured `retrieval_health` the candidate now produces — which is
currently unimplemented on every layer.

## 3. Status after this audit

```
CURRENT retrieval_health-based user notice:            NOT IMPLEMENTED
HISTORICAL embedding failure toast:                    SOURCE IDENTIFIED (commit a785e1842 + per-request
                                                       .catch() in next-search/next-searches hooks +
                                                       api-error.ts friendly mapping + the new
                                                       model-service-unavailable component)
OLD-PATH HYPOTHESIS (hard failure -> toast storm):     CONFIRMED
CURRENT-PATH HYPOTHESIS (isolation -> 200 -> silence):  CONFIRMED
```

## 4. Explicitly not verified in this round

1. Whether `a785e1842` is exactly the commit implementing the user's request (its scope, message and tests
   match closely, but no issue link was found to prove one-to-one correspondence).
2. Whether the **running image** contains `a785e1842` — the deployed revision is older than HEAD in at least
   `pipeline.py`, so the presence of `../common/model_errors.py` and the `model-service-unavailable` component in
   the container was **not** checked here.
3. Which endpoint the observed toasts came from: `next-search` (search) versus the chat path
   (`use-chat-request.ts:723` `message.error(error.message)` also exists). Both are per-request and would
   produce the same multiplies.
4. The exact i18n wording of the friendly embedding-quota message; `modelServiceErrorMessageKey` maps to a
   locale key whose text was not read.

Each is a cheap read-only follow-up, and none of them changes the §2.3 delta.
