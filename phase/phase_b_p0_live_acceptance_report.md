# Phase B P0 — Live Execution Window (Steps 1–7): **CORE RUNTIME FAIL — ROLLED BACK**

The window was executed end to end. Production is back on the verified pre-P0 image and is serving
retrieval again. The candidate was **not** accepted, one production defect was found that the frozen
harness structurally could not see, and the rollback branch defined by the runbook was taken.

Machine-readable artifact: `phase_b_p0_live_acceptance_result.json`

---

## Decision

| item | status |
| --- | --- |
| `P0-A Health Contract` | **PASS** (unchanged; the contract modules themselves regress nothing) |
| `P0-B Production Wiring` | **FAIL** — the candidate's wiring does not execute: unbound reporter names at the real call site |
| `P0-C Live Core Acceptance` | **FAIL** — the live negative control raised `NameError`; injections correctly suppressed |
| `P0 CORE RUNTIME` | **NOT ESTABLISHED / FAIL** |
| `P0-6 User Disclosure UI` | **DEFERRED_NOT_IMPLEMENTED** |
| `C1–C6 User-visible Acceptance` | **NOT RUN / NOT IMPLEMENTED** |
| `P0-7 Operator Observability Sink` | **NOT_ACCEPTED_NOT_WIRED** |
| `P1` | **LOCKED / NOT ENTERED** |

For a successful core deployment the correct milestone wording is `P0 CORE RUNTIME: PASS`. **It is not
used here, because the readiness gate failed.** `Phase B P0 complete` is **not** declared: P0-6 and P0-7
remain outstanding, and the core runtime now additionally carries an open defect.

---

## Steps as executed

### Step 0 — preflight: PASS
Production ran `c50436820cb9`; rollback tag resolved to `c50436820cb9`; candidate tag to `99d0ee210004`;
KB binding `gemini-embedding-001` / `embd_id f79e37e5ab7611f18ecb3887d563fb04`; installed credential
fingerprinted `3c29c2a7b87c`; compose file and service resolved. No divergence from the verified premises.

### Step 1 — credential rotation, `api_key` only: PASS
The write path was resolved to its physical column: `kb.embd_id → tenant_model.id → tenant_model.instance_id
→ tenant_model_instance.api_key`. Blast radius was proved minimal before writing — the Gemini provider holds
**only** `gemini-embedding-001`, so the instance credential is not shared with any other model.

| | |
| --- | --- |
| row written | `tenant_model_instance.id = f7825d47ab7611f18d8d3887d563fb04` |
| columns written | `api_key` **only** |
| fingerprint before → after | `3c29c2a7b87c` → `062bcd934443` |
| key bytes round-trip | identical |
| all other columns (`id, create_time, update_time, instance_name, provider_id, status, extra`) | verified identical |
| `kb.embd_id`, model row, other 3 instances, `tenant_llm` | untouched |

### Step 2 — re-resolve + exactly one deployed-client probe: PASS
Resolved through the application's **own** resolver inside the container (`resolve_model_config`), not from
the environment: model `gemini-embedding-001`, factory `Gemini`, credential `062bcd934443`. One
`GeminiEmbed.encode_queries(<str>)` call returned **3072 dimensions, all finite**.

### Step 3 — recreate pinned to the candidate: executed
`docker compose -f docker/docker-compose.yml -f deploy/p0_baseline/p0b_image_override.yml up -d
--force-recreate --no-deps wenruo-rag-cpu`. The tracked compose file was **not** modified; the override pins
`my-wenruorag:p0b-891572a71`; neither the compose default image nor `latest` was used.

### Step 4 — runtime identity guard: PASS
Running image id `sha256:99d0ee210004d3ebcc5ed333261b1971aa96ce2208e9fa477c134626fc619b82`. Ports, all three
bind mounts, network, restart policy, command, ulimits preserved, and the environment diff was **empty**.
Deployed candidate files were hash-verified against the verified candidate artifacts.

### Step 5 — live negative control (readiness gate): **FAIL**
This is the application readiness gate, because this deployment has no Docker healthcheck. A real retrieval
through the deployed pipeline against KB `Cable_Tech_Docs`, with the real rotated credential:

```
NameError: name 'report_route_failure' is not defined
  multi_route.py:323  report_route_success()      <- NameError
  multi_route.py:327  report_route_failure(exc)   <- NameError escapes _guard
  multi_route.py:330  asyncio.gather(...)         <- raises
  pipeline.py:320     await _retrieve(...)        <- unguarded, propagates to the caller
```

Container log corroborates it: `[Multi-route] route '…' failed: name 'report_route_success' is not defined`.
No chunks, no `retrieval_health`, no `overall = full`. Answer-policy enforcement remained **disabled** and the
credential/model resolved correctly — the failure is not the credential.

### Step 6 — five frozen P0-C injections: **NOT RUN (correctly suppressed)**
The sequence is explicit: injections run only if the negative control passes. It failed, so no injection was
run, no synthetic 429 was manufactured, and the rollback branch was taken instead.

### Step 7 — rollback and terminal state
Recreated through the same Compose service onto `my-wenruorag:rollback-pre-p0-20260927`
(`sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0`), runtime identity re-verified
(ports, mounts, network, restart policy, command, environment all preserved), and production functionality
confirmed by a live retrieval: **7 chunks, 2 document aggregates, no exception**. No in-place fix was attempted.

---

## Root cause (found, not fixed — fixing is not authorized in this window)

`../rag/retrieval/multi_route.py` calls `report_route_success()` (line 323) and `report_route_failure(exc)`
(line 327). Both names are defined in `rag/retrieval/health_bridge.py` and imported into
`rag/retrieval/pipeline.py` — but **never imported into `multi_route.py`**. Verified in-container:
`hasattr(multi_route, 'report_route_success') → False`.

The control flow makes it maximally destructive: the *success* path raises, the module's own
`except Exception` catches it, the handler then calls the second unbound name, and that `NameError` escapes
`_guard` into `asyncio.gather`, whose result is awaited at an unguarded line. **Every question that reaches
the route loop fails outright** — a total retrieval outage, strictly worse than the silent-degradation defect
the change was built to close. It would have shipped as a user-visible outage.

**Why the two existing gates could not catch it.** The frozen P0-C harness loads `health.py` /
`health_producers.py` from the repository and drives a *simulated* pipeline with test doubles at every
boundary; it never imports or executes the deployed `multi_route.py`, so an unbound name at the real call site
was invisible to it — it would have reported 5/5 injections PASS against code that cannot run. The
semantic-diff gate proved the introduced calls were additive reporter calls only
(`only_reporter_calls_introduced: true`, function sets and signatures unchanged), but a semantic diff over
*call sites* does not check that the *symbols* are bound in the module that calls them. Both gates were
necessary and neither was sufficient; only a live execution of the deployed entry point exposes this class of
defect — which is exactly what Step 5 is for, and why the negative control is ordered first.

---

## Production state at the end of the window

| item | state |
| --- | --- |
| running image | `my-wenruorag:rollback-pre-p0-20260927` = `c50436820cb9` |
| container | running, 0 restarts, ES healthy, data sync ready |
| ports / mounts / network / env | identical to pre-window |
| model binding | `gemini-embedding-001`, `kb.embd_id f79e37e5ab7611f18ecb3887d563fb04`, unchanged |
| installed credential | **KEY_2 `062bcd934443`** (retained) |
| retrieval | serving (live check: 7 chunks, no exception) |
| mysql / elasticsearch / redis / minio | untouched, still up |
| candidate image | retained for diagnosis, not deployed |

**Credential rollback was treated as independent from code rollback.** Evidence does not implicate the
credential: the failure is an unbound name, and the rolled-back production image served a real retrieval with
KEY_2. KEY_2 is therefore retained; the exhausted KEY_1 was **not** reinstalled. Because production works on
KEY_2, this window also leaves the quota blocker closed rather than reopened.

Not touched: tracked compose file, `kb.embd_id` and all 5 KB bindings, model row and other model configs,
index and mapping (no re-embedding, no index write), prompts, reranker parameters, retrieval tuning,
answer-policy enforcement (still disabled), the four backing services, and the front end.

Files created this window: `phase_b_p0_live_acceptance_result.json`, this report,
`deploy/p0_baseline/p0b_image_override.yml`, `deploy/p0_baseline/p0b_rollback_override.yml`.

---

## What the next window needs

1. **Authorize the code fix** in `../rag/retrieval/multi_route.py` — import the two bridge reporters (or drop the
   calls and report the legs elsewhere). This is a one-line class of fix, but it is a code change and needed
   explicit authorization, so it was not made.
2. **Add a binding gate**: import every deployed retrieval module and assert that every introduced reporter
   symbol actually resolves in the module that calls it. The semantic diff checked calls; nothing checked
   bindings.
3. **Make the live smoke a gate, not a step**: execute the deployed `retrieve_multi_route` against one real KB
   question *before* acceptance, so a runtime-unbound name can never pass on static evidence again.
4. **Then re-run Steps 1–7** with the negative control first and the five frozen injections only after it
   passes. Step 1 is already correct and should be skipped rather than repeated — the credential is healthy
   and installed.

Status: core deployment FAIL and rolled back; production stable; P0-6, C1–C6 and P0-7 remain outstanding; P1
not entered.
