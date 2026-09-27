# P0-7 Operator Observability — Design Audit (no implementation) + Provider Fact Record + Milestone Matrix

Read-only round: no code written for P0-7, no retrieval parameter changed, no embedding model change, no
provider workaround, no P1 entry. Baseline: `my-wenruorag:latest` = **`858c04e89fdd`** (retagged this round);
rollback anchor `rollback-pre-p0-20260927` = `c50436820cb9`. Credential KEY_2 `062bcd934443` unmodified.

---

## 1. Provider location restriction — fact record

### 1.1 What was observed (verbatim)

```
400 FAILED_PRECONDITION
{'error': {'code': 400, 'message': 'User location is not supported for the API use.',
           'status': 'FAILED_PRECONDITION'}}
```

Observed through the **deployed** client (`GeminiEmbed.encode_queries`) against model `gemini-embedding-001`
with the installed credential (fingerprint `062bcd934443`).

### 1.2 Classification

| question | answer |
| --- | --- |
| classification | **PROVIDER_LOCATION_RESTRICTION / EXTERNAL_PROVIDER_AVAILABILITY** |
| is it Quota exhaustion? | **No** — quota is `429 RESOURCE_EXHAUSTED`; this is `400 FAILED_PRECONDITION`. Different code, different status, different remedy. |
| is it an invalid credential? | **No** — the request was authenticated and then refused on policy. An invalid key yields `401/403 API key not valid`. |
| is it a P0 Health-Contract defect? | **No** — the contract classified it correctly and honestly: `overall=degraded`, `degradation_reason=EMBEDDING_UNAVAILABLE`, `evidence_completeness=insufficient`, `validate() == []` (no silent degradation). |
| root cause | **Not asserted.** Without independent evidence I do **not** claim the server's egress IP is the cause. What is evidenced is only the provider's own refusal and its message. Anything beyond that is a hypothesis (egress region, provider policy change, account/project region) and would need separate investigation. |

### 1.3 Why it is recorded as a *positive* P0-6 acceptance case

This is the first **real, external, non-injected** dense-leg failure since the disclosure work landed, and it
exercised the whole chain end to end without anyone manufacturing it:

```
provider refusal
  -> embedding exception at its own boundary        (Dealer.get_vector)
  -> dense leg reported FAILED with a reason        (health_bridge)
  -> aggregation -> DTO {degraded, insufficient, EMBEDDING_UNAVAILABLE}
  -> contract validate() == []                      (no silent degradation)
  -> UI disclosure: one degraded notice             (P0-6)
```

Two properties are demonstrated by this single event:

1. **Producer truth held under a real failure.** No leg was invented, no reason was guessed, and the honest
   `EMBEDDING_UNAVAILABLE` was produced even though a naive marker-based classifier might have tried to force
   a quota-shaped answer.
2. **The disclosure fired for the right reason.** Under the accepted wording rules this state produces the
   single honest degraded notice — and, importantly, the **unified copy introduced this round claims no
   fallback mechanism**, which matters precisely because the experiment in §1.4 shows there is no fallback.

### 1.4 What the metrics currently cannot tell an operator (motivates P0-7)

The grounding experiment (`deploy/p0_gates/leg_fallback_experiment.py`, zero external quota) shows that when the
dense leg fails, **`store_round_trips = 0`**: the route aborts before the store round trip, so lexical search
never runs and **zero evidence** is returned. Consequence for operators:

* a dense-provider outage is a **total retrieval outage**, not a graceful degradation, and
* the reason code `EMBEDDING_UNAVAILABLE` is a **catch-all** that currently swallows the location-restriction
  class together with transport failures and 5xx — so today an operator cannot distinguish "capacity spent"
  from "provider refuses this region" from "network blip" without reading raw logs.

That gap is the core motivation for §2.

---

## 2. P0-7 Operator Observability — Design Audit

### 2.1 Which existing sink should receive the structured event?

Verified state of the deployment:

| sink | present today? | evidence |
| --- | --- | --- |
| **Python logging → rotating file** | **YES** | `common/log_utils.py:40` `RotatingFileHandler(log_path, maxBytes=10MB, backupCount=5)`; files at `/ragflow/logs/{ragflow_server,admin_service,data_sync_*.log}`, bind-mounted to `docker/ragflow-logs` on the host |
| **Langfuse (LLM tracing)** | **integrated but UNCONFIGURED** | `langfuse` imported in `dialog_service.py`, `TenantLangfuseService`, `trace_context`/`langfuse_session_id` threaded through model bundles — but `SELECT COUNT(*) FROM tenant_langfuse` = **0**, so no tenant has it enabled → effectively dead in this deployment |
| **Metrics (`/metrics`, Prometheus, OTel)** | **ABSENT** | no `prometheus_client` / `opentelemetry` in first-party code (only vendored inside `litellm` in site-packages); `/metrics` → **404** on 9381 and connection-closed on 9383/9384; nothing in the Go `admin/` tree |

**Recommendation: log-first, one structured JSON line per retrieval, through the existing logger.**

Rationale: it needs **no new infrastructure**, the volume is trivially small (exactly one line per retrieval),
the sink is already persisted and rotated, and it is the only sink that is actually live in this deployment.
Emit the *same* payload to Langfuse **only** when a tenant has configured it (a capability check, not a code
path), so enabling tracing later costs nothing.

Do **not** add a metrics client to the request path before a metrics sink exists. If metrics are wanted, that
is a separate decision with its own boundary (an OTel collector or a `prometheus_client` endpoint on the admin
server), because a counter with no scraper is dead weight and a counter with unbounded labels is a memory leak.

**The seam already exists and is unused.** `HealthSession.emit_event()` already builds exactly the right payload
and appends it to `session.events`, which nothing consumes:

```json
{"event": "retrieval_health", "question_id": …, "plan_version": …,
 "overall": "…", "evidence_completeness": "…", "degradation_reason": …,
 "degraded_legs": [...], "leg_status": {...}, "contract_violations": [...]}
```

### 2.2 Aggregation, exactly-one-event, and alert-storm prevention

**Exactly one event per retrieval — guarantee structurally, not by convention.**

Today `build()` emits, and `build()` is reached from `attach_retrieval_health` on **all three** pipeline return
paths (early `no question`, early `empty window`, normal return). The design rule: **emit only from
`attach_retrieval_health`**, with an `_emitted` flag on the session so any future second `build()` call cannot
double-emit. Then add an emission counter and a test asserting `events == 1` for every pipeline return path,
including the two early returns. This is what makes "one retrieval → one event" a property rather than a hope —
and it is the same discipline that made "5 sub-routes → 1 health object" true in P0-C.

**Aggregation dimensions (cardinality-bounded).**

| dimension | values | use |
| --- | --- | --- |
| `overall` | 3 | primary counter label |
| `degradation_reason` | 11 (currently) | second counter label — this is the actionable axis |
| `evidence_completeness` | 3 | counter label (detects "answering from nothing") |
| `degraded_legs` | subset of 5 | **log field only, never a metric label** (powerset = 32 and it multiplies every other label) |
| `question_id`, `plan_version`, `session_id` | unbounded / semi-bounded | **correlation fields only, never metric labels** — an unbounded label turns a counter into a memory leak |

Recommended derived view (the one an operator actually reads): *rate of retrievals by `overall`, split by
`degradation_reason`* — this single series answers "is retrieval healthy, and if not, why".

**Alert-storm prevention.** The event is already one per retrieval, so storm risk comes from alerting *per
event*. Rules:

1. Never alert on a single event. Alert only on a **windowed ratio**: e.g. `degraded_or_failed / total > 20%`
   sustained for 5 minutes, evaluated on the aggregate (not per request).
2. **Group by `degradation_reason`** so five sub-routes, or a hundred concurrent requests, collapse into one
   firing alert per reason.
3. **Inhibit**: when `overall=failed` ratio is firing, suppress the `degraded` alert for the same reason (the
   severe one carries the information).
4. **One page per incident**: an alert that has already fired must not re-page while unresolved; use a single
   long-lived alert keyed on `reason`, not a per-occurrence notification.
5. Never alert on `EMBEDDING_QUOTA_EXHAUSTED` more than once per reset window — a spent daily allowance is a
   known state with a known remedy, not a page.

### 2.3 Classification of Quota / Unavailable / Timeout / Location Restriction

Current mapping (`reason_from_exception`, marker-based, leg-aware):

| provider condition | current classification | adequate? |
| --- | --- | --- |
| quota / 429 / `RESOURCE_EXHAUSTED` | `EMBEDDING_QUOTA_EXHAUSTED` | **yes** — distinct and actionable |
| timeout / deadline | `EMBEDDING_TIMEOUT` | **yes** — distinct (transient) |
| **location restriction (400 `FAILED_PRECONDITION`)** | `EMBEDDING_UNAVAILABLE` | **no — indistinguishable from a generic failure** |
| transport / 5xx / anything else | `EMBEDDING_UNAVAILABLE` | catch-all |

**Design recommendation: separate the location-restriction class by adding a distinct reason code**
(proposed `EMBEDDING_LOCATION_RESTRICTED`), or equivalently an additive `provider_failure_class` field. The
argument is not aesthetic — the **remedies differ**, and a catch-all defeats the purpose of a reason code:

| class | remedy | retry helps? |
| --- | --- | --- |
| `EMBEDDING_QUOTA_EXHAUSTED` | capacity: raise/rotate quota, wait for reset | yes, after reset |
| `EMBEDDING_LOCATION_RESTRICTED` | **infrastructure/policy**: egress region or provider change | **no** — retrying is pointless |
| `EMBEDDING_TIMEOUT` | transient latency: retry/backoff | yes |
| `EMBEDDING_UNAVAILABLE` | investigate: transport, 5xx, unknown | maybe |

**Scope note:** this is a change to the health **contract** (`ReasonCode`), i.e. P0-A territory, and it must
carry its own acceptance gate (the new code must keep `validate()`'s rules and must not weaken the
no-silent-degradation invariant). It is therefore **flagged as a P0-7 implementation item requiring an explicit
decision**, not something this audit changes.

### 2.4 What needs a Counter, what needs an Alert

**Counters** (derived from the single event stream; all bounded-cardinality):

| counter | labels | why |
| --- | --- | --- |
| `retrieval_total` | `overall` | denominator for every ratio |
| `retrieval_degraded_total` | `degradation_reason` | the actionable axis |
| `retrieval_evidence_total` | `evidence_completeness` | detects "answered from nothing" |
| `retrieval_contract_violations_total` | — | **must always be 0**; the integrity counter |
| `retrieval_health_events_total` | — | detects double-emission (should equal `retrieval_total`) |

**Alerts** (in priority order; each groups by reason and pages once):

| id | condition | severity | rationale |
| --- | --- | --- | --- |
| A1 | `retrieval_contract_violations_total > 0` | **page immediately** | the health signal is lying about itself — this is the trust alarm, and it is the one thing the whole P0 effort exists to prevent |
| A2 | `overall=failed` ratio > threshold, 5 min | page | users are getting no answer |
| A3 | `EMBEDDING_LOCATION_RESTRICTED` sustained | page | provider policy/region — needs operator action, retrying is useless |
| A4 | `evidence_completeness=insufficient` sustained | page | answers are being produced without evidence |
| A5 | `EMBEDDING_QUOTA_EXHAUSTED` sustained past a reset window | ticket, not page | capacity, known remedy |
| A6 | `EMBEDDING_TIMEOUT` rate elevated | ticket | transient; watch for a trend |
| A7 | `retrieval_health_events_total != retrieval_total` | ticket | instrumentation defect (e.g. a double emit) |

Explicitly **not** alerts: any single degraded event; any single `EMBEDDING_UNAVAILABLE`; a `degraded` ratio
below the windowed threshold.

### 2.5 Guaranteeing telemetry never carries secrets or user content

**Emit a whitelist, never a dict.** The sink must copy **only** these keys, dropping anything else:

```
event, plan_version, overall, evidence_completeness, degradation_reason,
degraded_legs, leg_status, contract_violations, question_id
```

Design rules, each enforceable by test:

1. **No exception object, no message string, no provider body.** Nothing in the payload may be a `str(exc)` or
   a response body — the reason code is the *only* representation of a failure that crosses the boundary.
2. **No credential-shaped content.** Defence in depth: a denylist regex over the serialized line
   (`AQ\.`, `AIza`, `api_key`, `x-goog-api-key`, `Authorization`, `Bearer`, `Traceback`,
   `RESOURCE_EXHAUSTED`, `FAILED_PRECONDITION`) that **fails closed** — drop the line and emit a safe
   `redaction_failed` event rather than shipping a possibly-leaky line.
3. **No query text, no chunk content.** The payload has no field for either; `question_id` must be an
   identifier (verify it is an id, not the prompt) and `plan_version` a static version string.
4. **No tenant/kb/user identifiers as metric labels** (unbounded cardinality *and* unnecessary exposure);
   correlation belongs in the log line only, and only if policy allows it.
5. **Test as a gate, not a promise**: feed the emitter a poisoned session (extra fields carrying a fake key, an
   endpoint URL, a traceback and provider JSON) and assert the emitted line contains **only** the whitelisted
   keys and none of the denylisted patterns. This is the operator-side mirror of the P0-6 UI gate, and it is the
   same technique that already proves the UI cannot leak.

**Pre-existing consideration to carry forward (not introduced by P0-6):** the retrieval path already logs
truncated question text (`[Multi-route] question=%r` uses `question[:80]`). That is existing behaviour outside
the health event, and P0-7 should review it explicitly rather than assume the new sink is the only surface.

---

## 3. P0 Milestone Matrix

| milestone | status | evidence / note |
| --- | --- | --- |
| **P0-A** Health Contract | **PASS** | contract + producer API byte-identical to the accepted build; `validate()` rules intact; 6/6 injection regression |
| **P0-B** Production Wiring | **PASS** | evidence-leg facts produced at their real boundaries; `HEALTHY_PATH_CONTRACT_GATE` PASS with its negative regression; 5/5 frozen injections PASS against the deployed modules |
| **P0-C** Live Core Acceptance | **PASS** | live healthy path `overall=full`, zero contract violations; injection suite PASS; 0 silent degradation |
| **P0 CORE RUNTIME** | **PASS** | deployed and re-verified after the silent-revert incident was detected and repaired |
| **P0-6** User Disclosure UI | **IMPLEMENTED + DEPLOYED**; corrected wording **built** this round, not yet deployed | C1–C6 verified through the deployed bundle's production code path (29/29 tests); unified copy removes the unobservable fallback claim |
| **C1–C6** User-visible Acceptance | **PARTIAL** | code-path verification PASS; **in-browser click-through not completed** (SPA session minting returned 401 — harness prerequisite, not a product defect) |
| **P0-7** Operator Observability Sink | **DESIGN AUDIT COMPLETE — NOT IMPLEMENTED** | this document; no sink wired, `emit_event` payload still unconsumed |
| **P1** | **LOCKED / NOT ENTERED** | by instruction |

`Phase B P0 complete` is **not** declared: P0-7 is unimplemented, C1–C6 lacks the in-browser pass, and the
dense leg is currently unavailable for an external provider reason.

### 3.1 Open decisions (each needs your call, none applied)

1. **P0-7 sink**: accept log-first (recommended), or invest in a metrics/trace sink first?
2. **New reason code** `EMBEDDING_LOCATION_RESTRICTED` (contract change, needs its own gate).
3. **Deploy the corrected UI wording** — plan in §4; production must not be interrupted without your go-ahead.
4. **In-browser C1–C6**: resolve SPA session minting, or accept code-path verification?
5. **`latest` hygiene**: done this round (retag). Recommend also removing the `build:` block's ability to
   silently produce a mixed image from the working tree (a `docker compose build` today would combine the repo
   tree's old `pipeline.py`/`multi_route.py` with the new health modules).
6. **Dense-leg availability**: provider location restriction — infrastructure/policy decision, explicitly out
   of this round's authority.

---

## 4. Planned deploy of the corrected wording (reported, not executed)

Per instruction the running container is **not** to be changed without prior reporting. The corrected bundle is
built as a **new immutable tag**; `latest` already points at the accepted running image `858c04e89fdd`, and the
corrected candidate deliberately does **not** take that tag yet.

Plan when authorized:

1. `docker compose -f docker/docker-compose.yml -f deploy/p0_baseline/p06_ui_image_override.yml up -d
   --force-recreate --no-deps wenruo-rag-cpu` (override updated to the new tag).
2. Identity guard: exact image id, ports/mounts/network/restart/command preserved, empty env diff.
3. Verify the served bundle carries the corrected strings; re-run the live health check to confirm the P0-B
   chain is untouched.
4. On any failure: recreate from `p0b-leg-6543f5a3` (`8694a5b943dc`) and stop. Rollback anchor for the current
   P0-6 image remains `858c04e89fdd`.
5. Retag `latest` to the new image **only after** the above passes, so an un-overridden compose recreate can
   never land on an unverified bundle.
