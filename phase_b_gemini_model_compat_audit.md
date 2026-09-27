# Gemini Model Compatibility Audit (read-only) — Root Cause of the HTTP 404

Read-only throughout: no DB or KB config change, no re-embedding, no container recreate, no candidate
deployment, and **no exploratory embedding call** (`embed_calls_made: 0`). The only network call was the
SDK's model listing, which this audit was authorised to use.

## 1. Root cause: the 404 was a probe model-id error, not a credential problem

| fact | value |
| --- | --- |
| KB embedding model id (`kb.embd_id`) | `f79e37e5ab7611f18ecb3887d563fb04` |
| **exact `model_name` in the model config** | **`gemini-embedding-001`** |
| what the deployed class actually uses | `GeminiEmbed.model_name = "gemini-embedding-001"` — no stripping needed, **no `models/` prefix added** |
| class default | `gemini-embedding-001` |
| provider factory / base_url | `Gemini` / `null` (SDK default endpoint) |
| credential present | yes, fingerprint `3c29c2a7b87c` |
| provider listing (v1beta, read-only, 61 models sampled) | `models/gemini-embedding-001`, `models/gemini-embedding-2`, `models/gemini-embedding-2-preview` |
| is the configured id listed? | **yes** (`target_present_in_listing: true`) |

`gemini-embedding-1.0` — the id used in the failed probes — **does not appear in the provider listing at all**.
That fully explains the earlier result: both keys returned `404 NOT_FOUND … models/gemini-embedding-1.0 is not
found for API version v1beta`. The keys were never the problem; **the requested model id did not exist**.

**Correction to my own earlier statement.** After that 404 I noted the live failure mode might have moved from
429 quota to 404 model-not-found. This audit disproves it: the deployed configuration uses
`gemini-embedding-001`, which is valid and available, so the live dense-leg failure mode remains **quota
(429)**. The 404 was introduced by my probe, which took the id from a quota-metric *display string* rather than
from the configuration. That is precisely the failure mode you warned about when you asked me not to guess
endpoint or model naming.

## 2. Where `gemini-embedding-1.0` came from

- Git history shows `gemini-embedding-001` as the long-standing identifier in this codebase (commits
  `596428ffe`, `94a607336`, `a6da1a05e`, `8047857de`, `4a33455a2`, and the class default itself).
- `gemini-embedding-1.0` appears in this repository only as a **reference/test string** (e.g. inside
  `a785e1842`) and in this phase's own audit documents and captured logs — **never as a configured model id or
  a default**. The earlier `429` body that named `model: gemini-embedding-1.0` is therefore a provider-side
  *metric label*, not proof of what the client sent.
- Practical consequence for the record: the earlier live 429 evidence remains valid as a quota observation,
  but its model label should not be reused as an API model id. The configuration is the only authority.

## 3. Vector-space consistency judgement

| question | judgement |
| --- | --- |
| Is `gemini-embedding-001` the same model that produced the existing 3072-dim index? | **Yes, as far as configuration is concerned.** The model config bound to this KB has been `gemini-embedding-001`; the index was populated by the deployment through this config; the id is available unchanged at the provider. |
| Classification of using `KEY_1` (fingerprint `3c29c2a7b87c`) — **which matches the deployed credential fingerprint exactly** — with `gemini-embedding-001` | **`CREDENTIAL_ROTATION`** — same provider, same model id, same vector space. No re-index implication. |
| Classification of `gemini-embedding-2` / `gemini-embedding-2-preview` (also listed, also embedding-capable) | **`EMBEDDING_MODEL_MIGRATION`** — available and possibly 3072-dim, but **not** the model that built the current index. Switching to either would require a full re-embedding and index evaluation. **Forbidden** without that evaluation, and explicitly not proposed here. |
| Output dimension | Not measured this round (no embedding call was made). The index is `dims: 3072` and `gemini-embedding-001` defaults to 3072 with no explicit `output_dimensionality` in the config, so the configuration is consistent; the dimension can only be *confirmed* by one authorised call. |

**Unresolved and deliberately not guessed:** whether `KEY_1` and `KEY_2` have remaining quota, and whether they
share a quota project. The previous 404 answered neither question, and the listing call carries no quota
information. Both remain `NOT VERIFIED`.

## 4. Status after this audit

```
HTTP 404 ROOT CAUSE:            PROBE MODEL-ID ERROR (gemini-embedding-1.0 does not exist; config is
                                gemini-embedding-001, which the provider lists as available)
DEPLOYED CONFIG MODEL ID:       gemini-embedding-001 (valid, unchanged, no prefix handling needed)
KEY_1 (= deployed credential):  NOT_DETERMINED for quota; identity confirmed by fingerprint match
KEY_2:                          NOT_DETERMINED for quota; distinct credential (fingerprint 062bcd934443)
VECTOR-SPACE RISK:              CREDENTIAL_ROTATION is the applicable case; no migration is proposed
MODEL MIGRATION CANDIDATES:     models/gemini-embedding-2, models/gemini-embedding-2-preview — FORBIDDEN
                                without a re-embedding and index evaluation
LIVE P0-C CAPACITY:             STILL BLOCKED, but the blocker is now understood: one authorised probe with
                                the confirmed id would settle the quota question, and only then can the
                                healthy-path negative control be attempted
```

## 5. What would resolve the remaining question (needs your authorisation)

A **single** embedding call using the confirmed id `gemini-embedding-001` with `KEY_1` (and optionally one with
`KEY_2`), through the deployed client, is no longer a blind trial — the model id now comes from the
configuration rather than a guess, and the call would return either a 3072-dim vector (`HEALTHY`) or a
structured 429 (`QUOTA_EXHAUSTED`). I did **not** run it this round, because your instruction paused quota
testing and forbade exploratory embedding calls. It is the only remaining step before a live P0-C window.

## 6. Red lines honoured

No DB/KB mutation, no credential change, no environment change, no re-embedding, no container recreate, no
candidate deployment, no model-id switch, no exploratory embedding call, no P1 entry. The credential was used
only for the read-only model listing, and appears only as a fingerprint.
