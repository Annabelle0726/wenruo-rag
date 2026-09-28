# Phase B P0-6 User Disclosure UI — Implementation, Rebuild, Deployment, Acceptance

Baseline lock honoured: built on `my-wenruorag:p0b-leg-6543f5a3` (`8694a5b943dc`). Credential **KEY_2 `062bcd934443`
unmodified**; no rotation, KEY_1 not restored. Route isolation and exception handling untouched — nothing
re-throws or surfaces a raw exception on this path.

Machine-readable artifact: `phase_b_p0_6_ui_disclosure_acceptance_result.json`
Design spec (Phase 1, confirmed): `phase_b_p0_6_ui_disclosure_audit_and_design.md`

---

## 1. Milestones

| milestone | status |
| --- | --- |
| `P0-6 User Disclosure UI` | **IMPLEMENTED, REBUILT, DEPLOYED** |
| `C1–C6 User-visible Acceptance` | **VERIFIED THROUGH THE DEPLOYED BUNDLE'S PRODUCTION CODE PATH**; real-browser click-through **not completed** (§5) |
| `P0-A Health Contract` | **PASS** (Python byte-identical to the accepted baseline) |
| `P0-B Production Wiring` | **PASS** (byte-identical) |
| `P0-C Live Core Acceptance` | **PASS** at acceptance time — see the production condition change in §6 |
| `P0 CORE RUNTIME` | **PASS** (restored — it had been silently reverted, §7) |
| `P0-7 Operator Observability Sink` | NOT_ACCEPTED_NOT_WIRED |
| `P1` | LOCKED / NOT ENTERED |

`Phase B P0 complete` is **not** declared.

## 2. What was built

The audit's headline finding held: the backend already ships `retrieval_health` inside `reference` on every
chat and search path, so **P0-6 is frontend-only** — no backend edit, no new endpoint, no contract change.

**New (3):** `web/src/utils/retrieval-health-notice.ts` (the C1–C6 mapper, the dedup dispatcher and the only
toast caller), plus its unit suite and a wiring suite.
**Modified (6):** `interfaces/database/chat.ts` (additive optional `retrieval_health` on `IReference`),
`chat-stream/run-stream.ts`, `hooks/logic-hooks.ts`, `next-search/hooks.ts`, `locales/zh.ts`, `locales/en.ts`.
**Untouched:** `components/ui/**` (shared-UI lock), all backend code, the credential, retrieval logic.

Privacy is enforced by construction: the module never receives an exception or a message string, the enums are
used **only as lookup keys** and never rendered, and unknown values map to *silent* rather than to showing the
raw value. The only strings that can reach the screen are the three localized constants.

## 3. Verification before deploy

| check | result |
| --- | --- |
| new unit tests (mapper, dedup, security) | **17/17 PASS** |
| new wiring tests through the real `runChatCompletionStream` | **8/8 PASS** |
| existing stream reference regression | **3/3 PASS** |
| lint (changed files) | 0 warnings, 0 errors |
| typecheck | **no error in any file changed this window** |
| full frontend suite | 863 passed; the same 12 suites fail on a **pristine stashed tree** (12 failed / 29 passed of 41) — proving **zero regressions** |
| bundle | all three strings present in `dist` (en + zh); dedup id bundled into the wiring chunk |

## 4. Rebuild and deployment

`my-wenruorag:p0-6-ui-cc701833` = **`858c04e89fdd`**, built from `deploy/p0_build/Dockerfile.p0_6_ui`
(context = repo root; removes the old dist, copies the rebuilt one). Nothing was overwritten — `latest`, the
rollback tag and all three earlier candidate tags are intact. The Python payload inside the new image is
byte-identical to the base (`multi_route.py b72e9540…`, `search.py 2de49655…`, `health_bridge.py baad7915…`),
which is what pins the base now that a digest `FROM` is rejected by the configured registry mirror.

Deployed through the same Compose service with `p06_ui_image_override.yml`; tracked compose file untouched,
`latest` never used. Identity guard: image id exact, ports/mounts/network/restart/command preserved,
environment diff empty. The running app serves the new locale and wiring chunks (zh verified at byte level).

## 5. C1–C6 acceptance

Verified through the **deployed bundle's production code path** — `runChatCompletionStream` → merge → flush →
`notifyRetrievalHealth` → i18n → sonner — with only the HTTP response stubbed:

| case | result |
| --- | --- |
| C1 `full` | **silent** (0 toasts) |
| C2 no signal / malformed | **silent** (0 toasts) |
| C3 quota **with evidence** | exactly **1** warning, exact i18n text |
| C4 quota **without evidence** | exactly **1** generic warning |
| C5 other `degraded` | exactly **1** generic warning |
| C6 `failed` | exactly **1** error |
| D1 dedup | repeated terminal handling **and** a second answer inside the cooldown → still exactly **1** toast |
| S1 sensitive-data red line | injected key-like string, endpoint, `Traceback` and provider text **never rendered**; text equals the i18n constant exactly |

**Not verified: an in-browser assertion against the running app.** Tokens minted for the SPA
(`Serializer` and `URLSafeSerializer`) were rejected with HTTP **401** by `/api/v1/datasets`, so the app
redirected to the root and no chat input was reachable. That is a harness prerequisite in this fork, not a
P0-6 defect. All minted credentials were deleted afterwards, from both the container and the host.

## 6. New finding that corrects the C3 wording (evidence-based)

A quota-free experiment (`deploy/p0_gates/leg_fallback_experiment.py`, run against the deployed image with a
failing embedding double) settles a claim I had justified in the spec from the contract alone:

```
dense: failed          lexical_leg_reported: false
store_round_trips: 0   evidence_returned: 0
dto: {overall: degraded, evidence_completeness: insufficient, degradation_reason: EMBEDDING_*}
contract_violations: []
```

**An embedding failure aborts the route before the store round trip, so lexical search never runs in that
route — there is no text-search fallback in this architecture.** My Phase-1 justification ("the surviving
evidence leg must be lexical") was wrong about the mechanism: lexical never gets to run.

The consequence is contained: because dense failure yields `evidence_completeness = insufficient`, the C4
gate I added means the user gets the **generic** notice, never the "fell back to text search" claim. The
friendly C3 wording is therefore effectively dormant and can never mislead. I recommend rewording C3 to drop
the mechanism claim (e.g. `语义检索暂时受限，本次回答可能不完整。`), which also collapses C3 and C4 into one
message — a decision for you; no code change was made pending it.

## 7. Incident: production was silently reverted, and has been restored

After the verified P0-6 deployment, the running container was recreated from **`c50436820cb9`** — the *pre-P0*
image — by a compose run that used **only the tracked compose file**:

| evidence | value |
| --- | --- |
| container label `com.docker.compose.project.config_files` | `…\docker\docker-compose.yml` (**no override**) |
| resolved image | `RAGFLOW_IMAGE=my-wenruorag:latest` (from `docker/.env`) → `c50436820cb9` |
| container created | `2026-09-27T23:02:19Z`, after the P0-6 deploy |
| effect | `/ragflow/rag/retrieval/health_bridge.py` **ABSENT** — the whole P0-A/B/C health chain gone |

This was **not caused by any command in this window** (every compose invocation here passed the override).
Left unnoticed, the P0-B silent-degradation defect was live again *and* the dense outage in §8 would have
been completely invisible to users and operators. I detected it, restored the pinned deployment through the
same service (image `858c04e89fdd`, `health_bridge` PRESENT, `config_files` now lists both files), and
verified it.

**Operator action recommended:** point `latest` at an accepted image, or drop the compose default, so an
un-overridden `docker compose up -d` cannot silently regress production.

## 8. Current production condition (disclosed, not silent)

**The dense (embedding) leg is failing in production.** The provider answers:

```
400 FAILED_PRECONDITION: 'User location is not supported for the API use.'
```

That is a **provider geo-policy restriction**, not a credential problem (authentication passed; fingerprint
unchanged) and not quota (not 429). Retrievals currently return no evidence. The value of the P0-B/P0-6 work
is visible exactly here: the health signal reports it honestly and the UI discloses it, instead of the
pre-P0 behaviour of answering from nothing and saying nothing. Restoring a healthy dense leg needs a
provider/geo or model change — outside this window's authority.

## 9. Final state

| item | state |
| --- | --- |
| image | `my-wenruorag:p0-6-ui-cc701833` = `858c04e89fdd`, running, 0 restarts |
| credential | KEY_2 `062bcd934443`, unmodified |
| model / KB binding | `gemini-embedding-001` / `f79e37e5ab7611f18ecb3887d563fb04`, 5 KBs |
| health chain | present and honest (zero contract violations under the current outage) |
| UI disclosure | deployed |
| dense leg | unavailable (provider geo-policy) — **disclosed, not silent** |
| rollback anchor | `p0b-leg-6543f5a3` = `8694a5b943dc` (not needed) |

Files: `phase_b_p0_6_ui_disclosure_acceptance_result.json`, `deploy/p0_build/Dockerfile.p0_6_ui`,
`deploy/p0_baseline/p06_ui_image_override.yml`, `deploy/p0_gates/leg_fallback_experiment.py`,
`web/src/utils/retrieval-health-notice.ts`, `web/src/utils/__tests__/retrieval-health-notice.test.ts`,
`web/src/pages/next-chats/chat-stream/__tests__/run-stream-retrieval-notice.test.ts`, plus the six modified
frontend files.

## 10. Open items

1. **C3 wording decision** (§6).
2. **Real-browser C1–C6 click-through** — needs SPA session minting resolved (§5).
3. **`latest` should not resolve to a superseded image** (§7).
4. **Dense-leg availability** (§8) — provider geo-policy.
5. `P0-7` operator sink remains unwired; `P1` not entered.
