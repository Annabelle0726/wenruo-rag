# Phase B — Key Probe, Deployed Call Shape and Quota-Notice Chain Audit (read-only)

No production mutation this round: no DB/KB credential change, no environment change, no recreate, no
restart, no code or UI change, no re-embedding, no retrieval tuning. Credentials appear only as
`KEY_1` / `KEY_2` with irreversible 12-hex fingerprints.

## 1. Deployed call shape (read-only, from the running container)

Production dense call site:

```
/ragflow/rag/nlp/search.py:105    qv, _ = await thread_pool_exec(emb_mdl.encode_queries, txt)   # txt is a STRING
```

Deployed client (`rag/llm/embedding_model.py`, class `GeminiEmbed`):

| property | value |
| --- | --- |
| SDK | `google.genai` — `genai.Client(api_key=<key>)`, endpoint/API version **not set by this class** (SDK default `v1beta`) |
| model naming | strips a leading `models/`; class default `gemini-embedding-001`, this deployment requests `gemini-embedding-1.0` |
| `encode(self, texts: list)` | batches of 16, `client.models.embed_content(model=..., contents=batch, config=config)` |
| `encode_queries(self, text)` | **takes a plain string**, calls `embed_content(model=..., contents=[truncate(text, 2048)], config=config)`, returns `(np.ndarray, token_count)` |
| request config | `_build_embedding_config()` → `EmbedContentConfig(task_type=TaskType.RETRIEVAL_DOCUMENT, title="Embedding of single string")` |
| failure wrapper | wraps any exception in `embedding_failure("GeminiEmbed", str(e))` and logs `GeminiEmbed: query embedding request failed` |

This also explains the previous round's failure precisely: my probe passed a **list** to `encode_queries`,
which expects a **string**, so the `TypeError: 'list' object is not an instance of 'str'` was raised before
any network request. That was a probe defect, not a credential or quota signal.

## 2. Precise key probe — exactly 2 provider requests (one per key)

Same provider, same model id, same fixed probe text, same task type, same deployed client object path.

| field | `KEY_1` | `KEY_2` |
| --- | --- | --- |
| credential fingerprint (sha256, 12 hex) | `3c29c2a7b87c` | `062bcd934443` |
| call path | `GeminiEmbed.encode_queries(<str>)` | `GeminiEmbed.encode_queries(<str>)` |
| provider result | **HTTP 404 NOT_FOUND** | **HTTP 404 NOT_FOUND** |
| classification | `NOT_DETERMINED` | `NOT_DETERMINED` |

Verbatim provider message, identical for both:

```
models/gemini-embedding-1.0 is not found for API version v1beta, or is not supported for embedContent.
Call ModelService.ListModels to see the list of available models and their supported methods.
```

**How to read this.** A 404 is not an authentication failure and not a quota failure: the request was
authenticated and routed, and then **model resolution failed**. So:

- Neither key is `INVALID` — auth passed (an invalid key yields 401/403 `API key not valid`).
- Neither key is `QUOTA_EXHAUSTED` — a quota rejection is 429 `RESOURCE_EXHAUSTED` with a structured body.
- Neither key is `HEALTHY` — no embedding was produced, so dimension and norm are **not measured**.
- `NOT_DETERMINED` is therefore the only defensible label for both.

**Per your red line I stopped here.** The provider itself suggests a `ListModels` call or another model id
(e.g. the class default `gemini-embedding-001`); probing alternative ids/versions would be exactly the
exploratory call pattern you prohibited, so it is reported, not attempted.

**Model/dimension compatibility:** `NOT_APPLICABLE` — 0 of 2 keys produced a vector. Dimension (3072) and
norm are **unmeasured**, and no `SAME_MODEL_CREDENTIAL_COMPATIBILITY_OBSERVED` label applies, because that
label requires two successful vectors.

**Quota independence:** `NOT VERIFIED` — and deliberately not guessed. Neither response carries project
identity (a 404 body has no quota metrics), so shared-vs-independent quota cannot be inferred.

### An observation that matters for production

The same model id is what this deployment requests, and while the earlier live 429 proves
`gemini-embedding-1.0` resolved for the production key at that time, it does **not** resolve now on
`v1beta`. If that is still the configured id, the live dense-leg failure mode may have **changed from 429
quota to 404 model-not-found**. Consequence for the candidate: `reason_from_exception` maps this to
`EMBEDDING_UNAVAILABLE` (no quota marker present), not `EMBEDDING_QUOTA_EXHAUSTED` — correct by
construction, but worth confirming against the deployed model id before the live gate, because a 404 would
make the healthy-path negative control impossible for a reason unrelated to quota.

## 3. Read-only audit: Gemini 429 → user-visible surface

Chain: `Gemini 429 → Embedding exception → reason code → retrieval_health → API response → frontend → user`.

### 3.1 Operator observability

| layer | current production (old image) | after candidate deployment |
| --- | --- | --- |
| route failure | `_LOG.warning("[Multi-route] route %r failed: %s", query, exc)` — unstructured, no reason code | same warning **plus** a structured leg fact at the exception boundary |
| reason code | absent | `EMBEDDING_QUOTA_EXHAUSTED` for a quota exception, `EMBEDDING_UNAVAILABLE` for anything else |
| API payload | exactly `chunks`, `doc_aggs`, `total` | those three unchanged **+ additive** `retrieval_health {overall, evidence_completeness, degradation_reason}` |
| metrics / trace | none | **NOT WIRED.** The candidate builds an event object (`emit_event`) and appends it to the in-process session only; nothing logs it and no metrics/trace sink is attached yet |

So: **DTO transparency is delivered by the candidate; log-line and metrics/trace transparency is not.**
That gap is real and I am flagging it rather than implying the P0 observability goal is fully met — an
operator who greps logs or scrapes metrics sees no change after this deployment.

A repo-wide check inside the container found **no consumer** of `retrieval_health` or `degradation_reason`
in `/ragflow` (the only hit was an unrelated endpoint name, `dify_retrieval_api.py:318
retrieval_health_check`), so the field is currently produced and not read by anything.

### 3.2 Assistant answer disclosure

**NOT IMPLEMENTED, by design in this version.** The candidate does not touch `dialog_service`, and no code
path reads the health block, so the synthesised answer contains **no refusal and no degradation notice**.
The policy machinery (`decide_answer_action`, `required_notice`, the disclosure text) exists and is unit
tested, but has **zero call sites** on the deployed path — this is precisely the answer-policy decoupling
you required.

### 3.3 Frontend user notification

**`USER_VISIBLE_QUOTA_NOTICE: NOT IMPLEMENTED`.**

Evidence: a search of `web/src` for `degradation_reason`, `retrieval_health` and `evidence_completeness`
returned **no matches**, and the container-side search found no Python consumer either. Front-end consumers
of the response read `reference.chunks` and `reference.doc_aggs` only. There is no Toast, no Banner, no
Inline notice, and no code that could display a degraded-retrieval state to a user. A degraded or
quota-failed retrieval is therefore **invisible to the end user** in the current product, both before and
after this candidate.

## 4. Requested status

```
KEY_1: NOT_DETERMINED          (HTTP 404 model-not-found; auth passed, no quota answer received)
KEY_2: NOT_DETERMINED          (identical HTTP 404; auth passed, no quota answer received)
MODEL/DIMENSION COMPATIBILITY: NOT_APPLICABLE — 0/2 keys produced a vector, so dimension (expected 3072)
    and norm are unmeasured; SAME_MODEL_CREDENTIAL_COMPATIBILITY_OBSERVED does not apply
QUOTA INDEPENDENCE: NOT VERIFIED  (no project identity in the responses; not guessed)
REAL PRODUCTION CREDENTIAL INJECTION POINT: the model configuration bound to the knowledge base
    (DB-backed); NOT an environment variable — no GEMINI_*/GOOGLE_*/API_KEY variable exists in the
    container and no code path reads GEMINI_API_KEY or GOOGLE_API_KEY
P0 LIVE GATE CAPACITY: BLOCKED  (no healthy dense leg can be demonstrated; and see §2 — a model-not-found
    condition would block the healthy-path negative control independently of quota)
```

## 5. Limits of this round

- 2 provider requests total, one per key; no retries, no alternative model ids, no `ListModels` call.
- The 404 leaves three things open: whether these keys have remaining quota, whether the configured model
  id is still valid today, and whether the two keys share a quota project. All three are recorded as
  undetermined rather than inferred.
- Read-only throughout; production image and container untouched (verified before and after the probe).
