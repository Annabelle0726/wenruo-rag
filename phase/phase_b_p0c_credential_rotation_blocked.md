# Phase B — P0-C Credential Rotation Attempt: BLOCKED (no deployment performed)

**Outcome: `BLOCKED_BY_QUOTA` is UNCHANGED. No container was recreated, no environment variable was
injected, and no live P0-C acceptance was run.** The probe gate did not pass, so the deployment step it
guards was correctly not executed. No substitute PASS is claimed.

## 1. Minimal probe — FAILED (did not confirm 200 / 3072)

Single `embedContent` request to `gemini-embedding-1.0` through the public endpoint, key passed in the
`x-goog-api-key` header (never in a URL, never logged):

| alias | endpoint | result |
| --- | --- | --- |
| `KEY_2` | `POST /v1beta/models/gemini-embedding-1.0:embedContent` | **HTTP 404**, empty error body |
| `KEY_1` | same | **HTTP 404**, empty error body |

A 404 with an empty body is not a quota answer (a quota rejection is 429 with a structured body naming
`embed_content_free_tier_requests`). So the probe neither confirmed 200 nor measured 3072 dimensions, and
**no claim is made about whether these keys have remaining quota.**

Two candidate explanations, which the next diagnostic can separate:

1. the request never reached Google's API as expected (host-side network/proxy artifact producing a 404),
   or
2. the keys are not valid for that endpoint/model path (Google can answer 404 rather than reveal key
   validity).

Re-running the identical request **from inside the container**, which demonstrably reaches
`generativelanguage.googleapis.com` (the earlier 429 came from there), distinguishes the two in one call.

## 2. Why environment injection could not have worked anyway

Independently of the probe, the proposed mechanism — inject `GEMINI_API_KEY` as a container environment
variable — **cannot rotate this deployment's embedding credential**:

| check | evidence |
| --- | --- |
| environment variables present in the running container | no `GEMINI_*`, no `GOOGLE_*`, no `*API_KEY`; only `EMBEDDING_BATCH_SIZE` among embedding-related names |
| does the code read an env key? | `grep -rn 'GEMINI_API_KEY\|GOOGLE_API_KEY' /ragflow/rag /ragflow/api` → **no matches** |

The deployed embedding client resolves its credential from the **model configuration bound to the
knowledge base** (DB-backed), not from the process environment. An injected env var would therefore have
had zero effect: the service would have come back up still using the exhausted credential, and the live
gate would have failed with a 429 for reasons that had nothing to do with the new key. That would have
consumed the recreate (and its rollback) for no information.

The underlying concept you describe — same-model credential rotation, no vector-space mismatch — is
correct and is not in dispute. Only the **injection point** is wrong for this architecture.

## 3. State: nothing was deployed

| item | state |
| --- | --- |
| candidate image | `my-wenruorag:p0b-891572a71` = `99d0ee210004` (built and image-gate verified earlier) — **not deployed** |
| `my-wenruorag:latest` | `c50436820cb9` — untouched |
| `my-wenruorag:rollback-pre-p0-20260927` | `c50436820cb9` — untouched |
| production container | still running the old image; `StartedAt` unchanged; not restarted, not recreated |
| live P0-C | **BLOCKED_BY_QUOTA**, no acceptance claimed |

## 4. What would actually unblock this

1. **Confirm the key first, in the right place.** Run the probe from inside a container that already
   reaches the API. If it returns 200 with 3072 dimensions, the credential is good.
2. **Rotate at the real injection point.** Update the embedding model's stored credential (the model
   configuration the knowledge base resolves), or set whichever environment variable the deployed client
   actually reads — and note that no such variable exists today, so a code change would be needed to make
   env-based rotation possible. Either way this is a credential/configuration change, **not** a retrieval
   behaviour change, and it needs no rebuild of the verified image.
3. **Then deploy as previously agreed:** recreate from `99d0ee210004`, run the negative control first
   (healthy dense leg → `overall = full`), then the synthetic injections, and on any failure recreate from
   the rollback tag and stop.

Key material was handled with the aliases `KEY_1` / `KEY_2` only; neither key appears in this report, in
any committed artefact, or in any log written by this round.
