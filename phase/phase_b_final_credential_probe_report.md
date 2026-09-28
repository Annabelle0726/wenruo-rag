# Final Credential Capacity Probe — gemini-embedding-001 (read-only, 2 requests)

Model id taken from the production configuration (not guessed). No model exploration: `gemini-embedding-2`
and `gemini-embedding-2-preview` were **not** touched. Exactly **2** provider requests were made, one per
credential, with identical parameters, through the deployed `GeminiEmbed.encode_queries(<plain string>)` call
path. No plaintext key and no plaintext vector appear anywhere in this report.

## 1. Probe specification as executed

| parameter | value |
| --- | --- |
| model | `gemini-embedding-001` (both requests) |
| probe text | identical fixed single string for both |
| call path | `GeminiEmbed.encode_queries(<str>)` — the deployment's own plain-string shape (`search.py:105`) |
| client | deployed `GeminiEmbed` → `genai.Client(api_key=...)`, SDK default endpoint |
| requests | 2 (one per credential), no retries |

## 2. Results

| field | `KEY_1` (current production credential) | `KEY_2` (spare) |
| --- | --- | --- |
| fingerprint (sha256, 12 hex) | `3c29c2a7b87c` | `062bcd934443` |
| result | **`QUOTA_EXHAUSTED`** | **`HEALTHY`** |
| provider answer | `429 RESOURCE_EXHAUSTED` — exceeded current quota | normal return |
| exception shape | the deployment's own `EmbeddingQuotaExhausted: GeminiEmbed embedding quota exhausted: 429 RESOURCE_EXHAUSTED` | none |
| dimension | not produced | **3072** |
| finite check | — | **all finite** (`all_finite: true`) |
| norm | — | `1.0` (unit vector; diagnostic only) |
| token count | — | 15 |
| vector fingerprint (sha256, 16 hex) | — | `9af31556a02e3449` |

Two observations worth keeping:

- `KEY_1` is confirmed to be the **production credential** (fingerprint `3c29c2a7b87c` matches the deployed
  config), and its failure is a genuine **quota** condition, not auth and not model resolution.
- The failure arrives already classified as `EmbeddingQuotaExhausted` by the deployed embedding layer, whose
  message contains both `quota` and `429`. The candidate's `reason_from_exception` maps exactly that shape to
  `EMBEDDING_QUOTA_EXHAUSTED`, so **acceptance rule C2's trigger condition is satisfied by real provider
  output**, not only by an injected fixture.
- `norm = 1.0` indicates the provider returns L2-normalised vectors; useful when comparing cosine behaviour,
  and consistent with a cosine-indexed store.

## 3. Standard output

```
KEY_1_STATUS:                          QUOTA_EXHAUSTED
KEY_2_STATUS:                          HEALTHY
SAME_CONFIRMED_MODEL:                  YES   (both requested gemini-embedding-001; KEY_2 succeeded on it)
DIMENSION_COMPATIBLE_WITH_3072_INDEX:  YES   (measured 3072, index is dims 3072)
P0_LIVE_GATE_CAPACITY:                 AVAILABLE, conditional on an authorised credential installation
```

## 4. Vector-space and quota-scope judgement

| question | judgement |
| --- | --- |
| Is `KEY_2` the same model as the one behind the existing index? | **Yes** — `gemini-embedding-001`, the configured model id, producing 3072 dimensions as the index expects |
| Credential rotation or model migration? | **`CREDENTIAL_ROTATION`** — same provider, same model, same vector space. **Not** a migration; no re-index implication |
| Are the two credentials' quotas independent? | **`VERIFIED` behaviourally.** At the same moment, on the same model, `KEY_1` returned 429 while `KEY_2` returned a vector. A **shared** quota is thereby excluded by observation. Residual limit, stated honestly: distinct *project identity* cannot be read from these responses, so independence is established by behaviour rather than by account metadata |
| Dimension compatibility | Measured 3072 with no explicit `output_dimensionality` requested, matching the `dims: 3072` index |

## 5. Branch rule applied (report only — no action taken)

`KEY_1 = 429` and `KEY_2 = HEALTHY` → **`SAFE_CREDENTIAL_ROTATION_CANDIDATE_AVAILABLE`**.

Per your rule I did **not** modify the DB, did **not** install `KEY_2`, and did **not** rotate anything. This is
a report, not an execution.

Note the operational asymmetry before any rotation is authorised: installing `KEY_2` at the credential
injection point **is** a configuration change to the model credential, and if it were wrong the service would
come up with a non-working embedding model. `KEY_2` is now measured healthy, which removes that risk — but the
change still needs your explicit approval, and it is not the same class of change as deploying the candidate.

**Injection point, restated:** the model configuration bound to the knowledge base (DB-backed). It is **not**
an environment variable — no `GEMINI_*`/`GOOGLE_*`/`API_KEY` variable exists in the container and no code path
reads one.

## 6. Consequence for the blocked live gate

The blocker has now changed character: it is no longer "no healthy dense leg can be demonstrated", but
"the healthy leg exists under a different credential than the one installed". The steps to a live P0-C window,
each requiring authorisation:

1. install `KEY_2` as the embedded model credential (DB-backed config) — **not done, awaiting approval**;
2. recreate from the verified candidate image `99d0ee210004` / `my-wenruorag:p0b-891572a71` — recreate, not
   restart;
3. run the **negative control first** (expect `overall = full`, notice count 0), then the synthetic injections
   (expect exactly one notice each, per C1-C7);
4. on any failure, recreate from `my-wenruorag:rollback-pre-p0-20260927` =
   `sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0` and stop.

## 7. Red lines honoured

No DB credential change, no candidate deployment, no container recreate or restart (production still runs
`c50436820cb9`; `StartedAt` unchanged), no re-embedding, no real retrieval call, no model exploration, no P1
entry. Exactly two provider requests were issued and no further call will be made without authorisation.
Credential material appears only as fingerprints.
