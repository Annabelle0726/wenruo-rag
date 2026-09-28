# Phase B — P0-B Producer Wiring and P0-C Runtime Fault Injection

## Milestone status (stated precisely)

| item | status |
| --- | --- |
| Phase B P0-A — Retrieval Health Contract | COMPLETE |
| Phase B P0-B — Runtime Producer Integration | IMPLEMENTED IN THE REPOSITORY; NOT DEPLOYED INTO THE CONTAINER |
| Production silent-degradation defect | NOT YET CLOSED (requires the container rebuild below) |

## P0-B — how the producers are wired

Health state is produced **where execution happens**, never inferred:

- `HealthSession.route_execution(routes, call)` is the exception boundary. It runs one call per route and
  converts each failure into a leg fact at that point via `reason_from_exception`, which reads the exception
  itself (quota marker -> `EMBEDDING_QUOTA_EXHAUSTED`, timeout marker -> `EMBEDDING_TIMEOUT`, otherwise
  `EMBEDDING_UNAVAILABLE` / `STORE_UNAVAILABLE`).
- The aggregator (`HealthSession.build`) only aggregates facts it was given. It never inspects chunk counts,
  result sizes or timings to decide whether a leg ran; `note_chunk_count` is reporting-only.
- `leg_not_triggered` = the plan/branch never required the leg. `leg_skipped` = the leg was eligible but a
  policy stopped it, and it **raises unless the reason is one of the closed policy set**
  `CIRCUIT_BREAKER_OPEN | BUDGET_GUARD_TRIPPED | POLICY_VETO`. The two can never be mixed by accident.
- Evidence is conservative: `RETRIEVAL_LAYER_MAX_COMPLETENESS = partial`. The retrieval layer cannot certify
  `full` from its own execution facts; only an explicit `AuthorityVerdict` from a named validator can upgrade
  it, and the upgrade is recorded as `evidence_state.authority`.

### Deployment insertion points (container revision)

| point | location | change |
| --- | --- | --- |
| route loop / failure isolation | `../rag/retrieval/multi_route.py` per-route execution | construct a `HealthSession`, call `route_execution(routes, call)`, report the dense or lexical leg from the per-route outcome |
| embedding boundary | the query-embedding request inside the store/search layer | report the dense leg where the request is issued, using `reason_from_exception` |
| plan layer | `../rag/retrieval/decomposition.py` return and validation | report `decomposition` as success, `PLAN_VALIDATION_FAILED` or `PLAN_EMPTY` |
| aggregation and DTO | `../rag/retrieval/pipeline.py` retrieval entry return | `health.attach_health(result, session.build_with_validation(validator))` beside the existing keys |
| propagation | answer layer, metrics, trace | consume `retrieval_health` as an input constraint; emit the structured event already produced by `emit_event` |
| circuit breaker | embedding boundary | `producers.circuit_breaker_skip(...)` so a policy stop is reported as `skipped`, never `not_triggered` |

## P0-C — runtime fault injection (positive injections)

Zero external quota: every service boundary is a test double.

| injection | overall | reason | dense | evidence | narrative | constraint-bearing | passed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SYNTHETIC_429_DENSE | degraded | EMBEDDING_QUOTA_EXHAUSTED | failed | partial | answer_with_disclosure | refuse_insufficient | PASS |
| SYNTHETIC_PLANNER_FAILURE | degraded | PLAN_VALIDATION_FAILED | success | partial | answer_with_disclosure | refuse_insufficient | PASS |
| SYNTHETIC_EMPTY_PLAN | degraded | PLAN_EMPTY | success | partial | answer_with_disclosure | refuse_insufficient | PASS |
| SYNTHETIC_LEXICAL_FAILURE | degraded | STORE_UNAVAILABLE | success | partial | answer_with_disclosure | refuse_insufficient | PASS |
| POLICY_SKIP_CIRCUIT_BREAKER | degraded | CIRCUIT_BREAKER_OPEN | skipped | partial | answer_with_disclosure | refuse_insufficient | PASS |

Chain verified end to end for every injection: synthetic exception -> producer report -> aggregator -> additive
DTO (`retrieval_health`) -> synthesis policy -> disclosure or refusal -> structured metric/trace event. Assertions
include `no_contract_violation`, `dto_additive_only`, `notices_present_where_required`,
`evidence_never_self_certified_full` and that `skipped` never appears where `not_triggered` is meant.

## P0-C — negative control (critical gate)

| check | result |
| --- | --- |
| overall_is_full | PASS |
| no_unresolved_leg | PASS |
| no_contract_violation | PASS |
| no_degradation_reason | PASS |
| retrieval_layer_evidence_conservatively_partial | PASS |
| conservative_floor_is_visible_in_policy | PASS |
| validator_upgrades_to_full_and_answers | PASS |
| validator_upgrade_needs_no_notice | PASS |
| upgrade_is_attributable | PASS |
| event_emitted | PASS |

Healthy retrieval: overall `full`, legs `{"decomposition": "success", "dense": "success", "lexical": "success", "rerank": "not_triggered", "followup": "not_triggered"}`,
evidence `partial` from the retrieval layer (action `refuse_insufficient`) and
`full` after the explicit authority validator (action `answer`).

This proves the contract does not misjudge a healthy request as degraded **and** that the conservative evidence
rule holds: the retrieval layer alone reports `partial`, and only a named validator may promote it to `full`.

## Deployment path — what remains

The running container executes its own revision and shares no bind mount with this tree, so the producers are
in the repository and their runtime chain is verified here, but the production defect is closed only after:

1. rebuild the image from a commit that contains `../rag/retrieval/health.py` and `rag/retrieval/health_producers.py`
   plus the four insertion points above;
2. restart the service onto the new image (explicit authorization required, since it interrupts the running deployment);
3. re-run this same injection suite against the live container with the embedding boundary doubled, and repeat the
   negative control, before declaring the defect closed.

Steps 1-3 are NOT executed in this round: no container file was patched, no service was restarted, and no Phase A
artifact, index or configuration was touched.

## Verdict

- Injections: 5 run, 5 passed, 0 failed.
- Negative control: PASS.
- Silent degradation observed: 0.
- External quota consumed: 0.

P0-A is complete, P0-B is implemented in the repository with its deployment path specified, and P0-C is verified on
the wired chain. P0 is **not** declared closed until the container rebuild in the deployment path is executed.
