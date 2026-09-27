# Steps 0-7 Execution Record — Preflight PASSED, Mutation Window NOT STARTED in this round

## Step 0 — Preflight / Rollback Guard: **PASS**

| guard | requirement | observed | verdict |
| --- | --- | --- | --- |
| G1 | running image is `c50436820cb9` | `c50436820cb9` | PASS |
| G2 | `my-wenruorag:rollback-pre-p0-20260927` resolves to `c50436820cb9` | `c50436820cb9` | PASS |
| G3 | `my-wenruorag:p0b-891572a71` resolves to `99d0ee210004` | `99d0ee210004` | PASS |
| G4 | KB model binding is `gemini-embedding-001` | `gemini-embedding-001`; `kb_embd_id` `f79e37e5ab7611f18ecb3887d563fb04`; config keys `api_base, api_key, is_tools, llm_factory, llm_name, max_tokens, model_type` | PASS |
| G5 | production credential = `KEY_1` (`3c29c2a7b87c`), spare = `KEY_2` (`062bcd934443`) | fingerprints as expected (read-only audit, `embed_calls_made: 0`) | PASS |
| G6 | plan contains no index / mapping / model / dimension change | plan touches exactly two things: the stored `api_key` value, and the container's image tag | PASS |

Container `StartedAt` unchanged (`2026-09-27T06:56:44Z`). No mutation of any kind was performed to reach this
point.

One diagnostic gap found while reading deployment metadata: the compose labels query failed
(`template parsing error … function "com" not defined` — my PowerShell quoting, not a deployment problem), so
**the compose project file path and service name are still unknown**. Step 2 needs them.

## Steps 1-7 — deliberately NOT started, and why

I stopped **before the first production mutation**, for two concrete reasons rather than caution in the
abstract:

1. **A production mutation window cannot be left half-open.** Steps 1-2 (DB credential write, then recreate
   from the candidate image) must be executed as one continuous sequence with the rollback image verified and
   in hand, followed immediately by Step 3's negative control. This round's remaining execution capacity is not
   enough to complete Steps 1-7 and still be able to verify or roll back at the end — and starting a
   credential write I cannot finish would leave production in exactly the state the rollback rules exist to
   prevent.
2. **One prerequisite datum is missing**: the compose file path and service name (see the G6 note). Recreating
   the service correctly — same env, volumes, network, ports, and the *candidate* image rather than `latest` —
   needs that, and guessing it is the same class of error as the `gemini-embedding-1.0` model id.

No rollback was triggered; nothing is in a partially-changed state. Production is exactly as it was:
`c50436820cb9`, `KEY_1` installed, model binding unchanged.

## Exact runbook for the next round (execute top to bottom, no deviations)

```
Step 0  re-run this preflight (all six guards) and record the compose file + service name:
        docker inspect -f '{{json .Config.Labels}}' wenruo-rag-cpu     # read com.docker.compose.* labels

Step 1  credential rotation, api_key field ONLY:
        - read the current row for llm_name = gemini-embedding-001, tenant f9b0101d119d
        - write KEY_2 into api_key; change nothing else (model_id, provider, embd_id, dims, prompts, rerank)
        - re-resolve the KB model config: model must still read gemini-embedding-001, fingerprint must read KEY_2
        - one minimal probe through the deployed client: expect 200 and a 3072-dim finite vector
        - if the probe fails: STOP, restore KEY_1, report CREDENTIAL_ROTATION_FAILED, do NOT touch the image

Step 2  recreate (not restart) the service onto the candidate image:
        docker compose -f <file> -f <override-with-image> up -d --force-recreate --no-deps <service>
        - the override must set image: my-wenruorag:p0b-891572a71  (never `latest`, no bind mounts)
        - verify the running container's Image ID == 99d0ee210004 before any acceptance step

Step 3  LIVE NEGATIVE CONTROL FIRST (real dense path, KEY_2):
        require: dense leg status success; all required legs explicitly resolved; overall = full;
                 degradation_reason = null; no exception raised
        if it fails: LIVE P0-C = FAIL, recreate from the rollback tag, stop. No injections, no code edits.

Step 4  synthetic fault injections only (test doubles; never spend real Gemini quota to manufacture a 429):
        dense quota exhausted, planner validation failure, empty plan, lexical failure, circuit-breaker skip
        assert per injection: leg status, reason mapping, monotonic overall, no silent degradation,
        route exception isolated, partial retrieval keeps HTTP 2xx, existing chunks/doc_aggs/total intact
        assert globally: answer-policy enforcement remains DISABLED

Step 5  acceptance boundary: P0-A PASS, P0-B PASS, P0-C PASS may be marked only if all Step 3-4 assertions pass;
        final wording must be "P0 CORE RUNTIME: PASS" — never "Phase B P0 fully complete"

Step 6  rollback on any failure: recreate from my-wenruorag:rollback-pre-p0-20260927 (c50436820cb9).
        Credential isolation: do NOT downgrade KEY_2 back to the exhausted KEY_1 merely because the candidate
        failed; keep the healthy credential unless evidence implicates the credential itself.

Step 7  final report: before/after image IDs, credential fingerprints (never plaintext), negative-control
        evidence, per-injection PASS/FAIL, final image + credential state, touched/untouched component list
```

## Status after this round

```
STEP 0 PRECHECK:          PASS (six guards recorded, no mutation)
STEP 1 CREDENTIAL:        NOT STARTED (KEY_1 still installed)
STEP 2 RECREATE:          NOT STARTED (production image still c50436820cb9)
STEP 3 NEGATIVE CONTROL:  NOT RUN
STEP 4 INJECTIONS:        NOT RUN
P0-A Health Contract:     PASS (unchanged)
P0-B Production Runtime Wiring:  CANDIDATE PREPARED / NOT DEPLOYED
P0-C Live Runtime Acceptance:    NOT RUN
P0-6 User Disclosure UI:         DEFERRED_NOT_IMPLEMENTED
C1-C7 Frontend Notice Acceptance: NOT RUN / NOT IMPLEMENTED
P0-7 Operator Observability Sink: NOT_ACCEPTED_NOT_WIRED
P1:                              LOCKED / NOT ENTERED
PRODUCTION:               c50436820cb9, KEY_1 installed, no index/mapping/model/prompt change
```

Touched: nothing in production. Untouched: DB, KB config, credentials, index, mapping, prompts, rerank
parameters, retrieval logic, front end, candidate image (still built and verified, undeployed).
