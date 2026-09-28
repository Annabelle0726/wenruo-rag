# Steps 1-7 Window — Prerequisite Resolved, Window NOT Opened

## 1. The open prerequisite is now resolved (read-only)

Step 1's write path was the one item the runbook left undefined. It is now known:

```python
def resolve_model_config(tenant_id, model_type, model_ref):
    try:
        return get_model_config_by_id(tenant_id, model_type, model_ref)
    except LookupError:
        return get_model_config_from_provider_instance(tenant_id, model_type, model_ref)
```

So the credential lives on the **model-config row whose id is the KB's `embd_id`**
(`f79e37e5ab7611f18ecb3887d563fb04`), reached through `get_model_config_by_id(tenant_id, EMBEDDING, embd_id)`
with a provider-instance fallback. Two write paths are available, in preference order:

1. the model-config service layer, updating that row's `api_key` only (preferred — it keeps the write inside
   the same validation path the application uses);
2. a direct `UPDATE` of the `api_key` column for that row id.

Either way the untouched columns are explicit: `id`, `tenant_id`, `llm_name`, `llm_factory`, `model_type`,
`api_base`, and every other field. `kb.embd_id` itself is never written.

This is the last unknown of the window. Step 2's target was already resolved, and the tags/ids for candidate
and rollback are verified.

## 2. Why I am not opening the window in this session

I am stopping **before the first mutation**, which is the safest possible stopping point, for one reason:

**I cannot carry Steps 1-7 through to a stable, verified end state in this session.** The window is a
continuous sequence — credential write, one probe, compose recreate with the image pinned, post-recreate
identity guard, live negative control, five synthetic injections, verification, report and artifact — and my
remaining execution capacity is not sufficient to finish it *and still be able to verify or roll back at the
end*.

The consequence of starting anyway is specific and bad: a **rotated credential with the candidate not
deployed**, i.e. production running the old image against a new credential, mid-window, with no completed gate.
Your own runbook does not define a rollback branch for that state — precisely because you separated credential
rollback from code rollback and told me never to auto-revert a healthy credential. So "stop mid-window" would
leave production in a configuration the runbook never sanctioned.

Your instruction anticipated this case: *"unless you hit a state that cannot be safely continued and is not
defined by the runbook"*. This is that state, reached **before** the first write rather than in the middle of
one. Nothing is half-changed and no rollback is needed.

## 3. Turnkey sequence for the window (execute top to bottom in one session)

```
Step 1  ROTATE (api_key ONLY), then verify, then probe once:
        - update the model-config row for embd_id f79e37e5ab7611f18ecb3887d563fb04: api_key = KEY_2
        - re-resolve: expect model llm_name == gemini-embedding-001, fingerprint == KEY_2 062bcd934443,
          kb.embd_id unchanged
        - ONE deployed-client probe: expect success, dimension 3072, all-finite
        - on failure: STOP; do not touch the image; judge the evidence before restoring KEY_1

Step 2  RECREATE onto the candidate, image pinned (never the compose default, never `latest`):
        docker compose -f C:\Projects\RAG\wenruo-rag\docker\docker-compose.yml \
                       -f <p0b-override.yml> up -d --force-recreate --no-deps wenruo-rag-cpu
        where <p0b-override.yml> sets ONLY:
            services:
              wenruo-rag-cpu:
                image: my-wenruorag:p0b-891572a71
        (an override file keeps the tracked compose file unmodified while pinning the immutable tag)
        - preserve the observed env, 3 bind mounts, network wenruo-rag_ragflow, ports 443/80/9380-9384,
          restart policy unless-stopped; no application-code bind mount; no in-container patch

Step 3  POST-RECREATE GUARD (there is NO healthcheck, so `running` != ready):
        - running image id == 99d0ee210004
        - mounts / network / ports match the pre-window observation
        - startup logs contain no candidate-introduced fatal error
        - then go straight to the negative control: it IS the readiness gate

Step 4  NEGATIVE CONTROL FIRST (real dense leg via KEY_2):
        dense executed and succeeded; usable evidence returned; retrieval_health present;
        every required leg explicitly resolved; overall == full; degradation_reason == null;
        zero contract violations; chunks/doc_aggs/total semantics preserved;
        answer-policy enforcement DISABLED; no refusal caused only by partial evidence
        - FAIL => do NOT run injections; go to the rollback branch

Step 5  SYNTHETIC INJECTIONS (test doubles only; never spend real quota to make a 429):
        embedding quota exhaustion, planner validation failure, empty plan, lexical/store failure,
        circuit-breaker skip
        assert per injection: exception -> producer -> aggregation -> additive DTO;
        dense 429 -> EMBEDDING_QUOTA_EXHAUSTED; skipped vs not_triggered separated;
        degraded/failed never wrongly `full`; no silent degradation; no re-raise;
        no synthetic non-2xx for a partial retrieval; no error code replacing a usable partial result;
        enforcement still DISABLED

Step 6  DECISION:
        all of Steps 3-5 pass -> keep the candidate; write exactly "P0 CORE RUNTIME: PASS"
        (never "Phase B P0 complete")
        any failure -> recreate from my-wenruorag:rollback-pre-p0-20260927 (c50436820cb9), verify the running
        image id, and KEEP KEY_2 unless the evidence implicates the credential itself; stop, no in-place fix

Step 7  REPORT + machine-readable artifact with: installed credential fingerprint, model name, kb.embd_id,
        running image tag + id, negative-control result, each injection result, contract-violation count,
        silent-degradation count, whether any rollback occurred, final production state
```

## 4. State now (unchanged by this round)

```
P0-A Health Contract:            PASS
P0-B Production Wiring:          CANDIDATE PREPARED / NOT DEPLOYED
P0-C Live Core Acceptance:       NOT RUN
P0 CORE RUNTIME:                 NOT ESTABLISHED
P0-6 User Disclosure UI:         DEFERRED / NOT IMPLEMENTED
C1-C6 User-visible Acceptance:   NOT RUN
P0-7 Operator Observability Sink: NOT ACCEPTED / NOT WIRED
P1:                              LOCKED
PRODUCTION:  image c50436820cb9 (my-wenruorag:latest), credential KEY_1 (3c29c2a7b87c),
             model gemini-embedding-001, kb.embd_id f79e37e5ab7611f18ecb3887d563fb04, no rollback
```

Touched this round: nothing in production. The only action was a read of `resolve_model_config`'s source.
No credential write, no recreate, no build, no DB mutation, no config change.
