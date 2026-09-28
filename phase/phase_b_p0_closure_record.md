# Phase B P0 — Closure Record

**Declared: `Phase B P0 COMPLETE` — all lines PASS.** Confirmed by the operator this round.

## 1. Production baseline mapping (verified read-only at declaration time)

| role | tag | image id | verified |
| --- | --- | --- | --- |
| **production baseline** | `my-wenruorag:latest` → `my-wenruorag:p0-7-obs-9f3d2c79` | **`ea93cd3bb795`** | `latest` resolves to `ea93cd3bb795`; running container image id `ea93cd3bb795`; 0 restarts |
| **rollback baseline** | `my-wenruorag:rollback-pre-p0-20260927` | **`c50436820cb9`** | resolves as stated |
| retained candidates | `p0-6-ui-copy-984e7036` / `p0-6-ui-cc701833` / `p0b-leg-6543f5a3` / `p0b-fix-b72e9540` / `p0b-891572a71` | `bf990b5846f4` / `858c04e89fdd` / `8694a5b943dc` / `be80f1b49b45` / `99d0ee210004` | retained |
| diagnostic (never deployed) | `p0-6-ui-diag-40cc959e` | `7796e6ab2e26` | throwaway, not in any promotion path |

Runtime checks: health chain present; operator event emitter present (definition + call site); credential
KEY_2 `062bcd934443` unmodified throughout Phase B.

## 2. Milestone board at closure

| milestone | status | decisive evidence |
| --- | --- | --- |
| P0-A Health Contract | **PASS** | contract + producer API stable; 6/6 injection regression |
| P0-B Production Wiring | **PASS** | evidence-leg facts produced at their real boundaries; healthy-path gate + its negative regression; 5/5 frozen injections on deployed modules |
| P0-C Live Core Acceptance | **PASS** | live healthy path `overall=full`, zero contract violations; zero silent degradation |
| **P0 CORE RUNTIME** | **PASS** | deployed; re-verified after the silent-revert incident was detected and repaired |
| P0-6 User Disclosure UI | **PASS** | deployed; C1–C6 **5/5** in a real browser against the production bundle |
| C1–C6 User-visible Acceptance | **PASS (5/5)** | full silent · no-signal silent · degraded 1 exact toast · failed 1 exact toast · history hydrate silent · removed phrase absent · zero leaks |
| P0-7 Operator Observability | **PASS** | live: exactly 9 fields, one line per retrieval (1/2/3 → 1/2/3), no sensitive content |
| P1 Planner Normalisation | **UNLOCKED FOR PLANNING** | see `phase_b_p1_planner_normalisation_plan.md` |

## 3. Backlog — archived, log-only, explicitly out of the current line

| # | item | why it is not fixed |
| --- | --- | --- |
| B-1 | **Frontend API Shape Validation Debt** — `useFetchSessionList` types its payload `IConversation[]`, declares `initialData: []`, then returns `data.data` unvalidated; a non-array response (e.g. `{"code":108,"data":false}`) reaches `dialogList.find(...)` (`next-chats/chat/index.tsx:152`) and drops the page into its error boundary. Suggested fix shape: normalise at the hook boundary and surface the API message instead of crashing. | Robustness debt, not a Phase B P0 objective; not authorised for change |
| B-2 | **`EMBEDDING_LOCATION_RESTRICTED` reason code** — the provider geo-policy refusal (`400 FAILED_PRECONDITION`) currently collapses into `EMBEDDING_UNAVAILABLE`, so operators cannot distinguish "capacity spent" from "provider refuses this region" from "transport blip", although the remedies differ. | A reason-taxonomy/contract change; explicitly excluded from both the P0-7 round and Phase B closure |

Neither item is a P0 acceptance dependency. Both are recorded here rather than fixed.

## 4. Honest residuals — not buried

1. **The dense (embedding) leg is unavailable in production for an external provider reason** —
   `400 FAILED_PRECONDITION: User location is not supported for the API use`. Production therefore answers
   `degraded` / `EMBEDDING_UNAVAILABLE`. This is a provider/geo-policy matter outside P0's scope: P0's
   acceptance is about **honest reporting**, which passes with the condition present — and the condition is
   now visible to users (P0-6) and to operators (P0-7) instead of silent.
2. **Classified and withdrawn defect claim.** The "P0-6 product-path defect" reported mid-phase was a
   harness sampling-window artifact (`[data-sonner-toast]` queried after sonner's 4000 ms lifetime). The
   claim was withdrawn on evidence from a throwaway diagnostic build. Recorded so the correction is
   traceable rather than quietly dropped.
3. **Evidence gaps carried forward**, none affecting P0: the shape debt (B-1); no operator metrics sink
   exists (the log-first design in the P0-7 audit remains the accepted approach, and Langfuse is integrated
   but unconfigured — `tenant_langfuse` = 0 rows).

## 5. Artifacts of the phase

Gates: `deploy/p0_gates/{binding_gate,healthy_path_contract_gate,generator_anchor_gate,semantic_diff_suite,step6_frozen_injections,p0_7_operator_event_gate,leg_fallback_experiment}.py`
plus the frozen regression fixture `deploy/p0_gates/fixtures/multi_route.UNBOUND-reporter-regression.py`.

Images: `deploy/p0_build/Dockerfile` (P0-B Python delta), `deploy/p0_build/Dockerfile.p0_6_ui` (rebuilt web
bundle), `deploy/p0_build/Dockerfile.p0_7` (operator event). Overrides:
`deploy/p0_baseline/{p0b_image_override,p0b_rollback_override,p0b2_fix_image_override,p0b3_leg_image_override,p06_ui_image_override,p06b_ui_copy_override,p07_obs_override}.yml`.

Reports: `phase_b_p0_live_acceptance_*`, `phase_b_p0b_fix_reacceptance_*`,
`phase_b_p0b_leg_attribution_acceptance_*`, `phase_b_p0_6_*` (spec, acceptance, blocker classification,
signal-delivery attribution, diagnostic attribution), `phase_b_p0_7_operator_observability_design_audit.md`.

**Phase B P0 is closed. P1 is unlocked for planning only — no P1 implementation is authorised yet.**
