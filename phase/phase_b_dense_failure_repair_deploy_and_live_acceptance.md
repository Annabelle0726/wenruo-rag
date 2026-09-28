# Dense-failure repair: candidate build, image gates, production deploy, live incident acceptance

**Window:** Candidate Build → Image Gates → Production Deploy → Live Incident Acceptance → Promotion.
**P1-2 remained PAUSED**; no planner, cache or `plan_hash` work entered the image or this window.

---

## 1. Pre-build confirmation

| check | measured |
| --- | --- |
| production image id | `sha256:ea93cd3bb7953e518c8694d86fe7a58af381ca4593ec42656bfd4e4964b5dba5` |
| `my-wenruorag:latest` | `ea93cd3bb795` (unmoved before the build) |
| rollback anchor | `my-wenruorag:rollback-pre-p0-20260927` → `sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0` — resolves, unchanged |
| KEY_2 | provider row `ee6cb91bab7611f18f0b3887d563fb04` / instance `f7825d47ab7611f18d8d3887d563fb04`, fingerprint **`062bcd934443`** ✓ |
| KEY_1 | fingerprint `3c29c2a7b87c` present **nowhere** — not restored |
| KB binding | 5 KBs, all bound to embedding model `f79e37e5ab7611f18ecb3887d563fb04`; primary KB `014e4f2aab7911f191ac3887d563fb04` (`Cable_Tech_Docs`) |
| embedding model / index | `gemini-embedding-001`, index `ragflow_a9e28731ab7011f19b833887d563fb04`, mapping fingerprint `dffd30c12aaede88`, 22 properties, 19 dynamic templates, `scripted_sim`, 2 shards, 486 docs |
| retrieval parameters | untouched: assistant `29a6da60ba1f11f1be9555eabe501d5b`, `similarity_threshold=0.55`, `vector_similarity_weight=0.5`, `top_n=12`, `top_k=1024`, no reranker |

**P1-2 exclusion.** The repository tree carries `rag/retrieval/planner.py` (51 KB) and P1-2 versions of
`pipeline.py`, `decomposition.py`, `chunk_profile.py`, `__init__.py`. The candidate copies **exactly
two files** and the Dockerfile fails the build if `planner.py` exists, if any P1-2 symbol appears
anywhere in `rag/` or `api/`, or if the payload does not import. The suspended live-replay probe was
not copied either.

---

## 2. Candidate image and image-level provenance

```
my-wenruorag:repair-798288f8
  sha256:6e926b5d8ef641d15a4ef623002531a5490b54154e0fa93648ff3cd61fb41bd0
  FROM my-wenruorag:p0-7-obs-9f3d2c79   (= sha256:ea93cd3bb795…)
  COPY search.py      -> /ragflow/rag/nlp/search.py          sha256 798288f85d7a32d9…
  COPY multi_route.py -> /ragflow/rag/retrieval/multi_route.py sha256 9a08bf97d5ca2692…
```

Byte comparison of the whole candidate against the running production container — **only two files
differ, and nothing exists only in the candidate:**

| file | candidate | production | verdict |
| --- | --- | --- | --- |
| `rag/nlp/search.py` | `798288f85d7a32d9` | `2de4965540a2b022` | CHANGED — the repair |
| `rag/retrieval/multi_route.py` | `9a08bf97d5ca2692` | `b72e95406e252fbd` | CHANGED — the mixed merge |
| `rag/retrieval/health.py` | `ff04f8f6f07a8f01` | `ff04f8f6f07a8f01` | SAME — frozen contract hash |
| `rag/retrieval/health_bridge.py` | `baad7915bed0102b` | `baad7915bed0102b` | SAME — P0-C leg attribution |
| `rag/retrieval/health_producers.py` | `9f3d2c79d8c22373` | `9f3d2c79d8c22373` | SAME — P0-7 emitter |
| `rag/retrieval/pipeline.py` | `c9174c52926de66b` | `c9174c52926de66b` | SAME |
| `rag/retrieval/__init__.py`, `chunk_profile.py`, `decomposition.py`, `query_router.py`, `rerank.py` | — | — | SAME |
| `web/dist` (1002 files) | — | — | **byte-identical** — the P0-6 frontend is unchanged |
| `rag/retrieval/planner.py` | absent | absent | no P1-2 in either |

The repair bytes in the image equal the accepted input exactly (payload hashes `798288f85d7a32d9` /
`9a08bf97d5ca2692` match the repository files byte for byte).

### `IMAGE_GATE_STATUS` — PASS

Run inside a container created **from the candidate image**, with no bind mount of the code under
test (verified by `sha256sum` inside that container), on the isolated ES + disposable Redis:

* **61/61** repair gates — `test_degradation.py` 24, `test_embedding_execution.py` 37.
* **4/4** P0 behavioural gates inside the same image: runtime symbol binding, healthy-path contract
  (including its negative regression), P0-7 nine-field operator event, P0-C frozen injections 5/5 +
  negative control + boundary leg attribution.
* The operator's three named classification cases, exercised END TO END through the real pipeline:

| case | class | recoverable | lexical executed | result |
| --- | --- | --- | --- | --- |
| incident `EmbeddingError(retryable=False)` | `EmbeddingError` | **yes** | yes | degraded result served (22 chunks) |
| `ModelException(retryable=True)` (connector 5xx) | `ModelException` | **yes** | yes | degraded result served |
| `EmbeddingError` 401 / 403, `ModelException` 401/403/404/422, `PermissionError`, `ValueError` | — | **no** | n/a | raised, never swallowed |

One gate fixture was missing on first run (`/tmp/baseline_search.py`, the frozen pre-repair
`search.py` used as the healthy differential's baseline). It is now committed at
`deploy/repair_gates/fixtures/baseline_search.py` (`2de4965540a2b022`, identical to
`deploy/p0_build/search.py`); the gates were fixed by supplying the fixture, not by weakening them.

---

## 3. Production deploy

`deploy/repair_baseline/repair_candidate_override.yml` pins the **immutable candidate tag**, listed
last so it wins over the P0-7 override, which stays in the config-file list to keep the recorded
lineage. `up -d --no-deps wenruo-rag-cpu` from `docker/`.

**Identity guard — PASS.** Running container image id = `sha256:6e926b5d8ef6…` = the candidate.

| preserved aspect | result |
| --- | --- |
| entrypoint, cmd, exposed ports, port bindings, restart policy, network mode, log config | SAME |
| binds | same three mounts; only the list order changed (compose sorts them) |
| container env | 141 entries before, 141 after, **no additions, no removals** |
| datastores | mysql / es01 / redis / minio all still at 7 h uptime — never recreated |
| `latest` during deploy | **unmoved** at `ea93cd3bb795` |
| restarts / OOM | 0 / false |

---

## 4. Live incident acceptance — the execution chain

The provider's location restriction is live in production right now, so the incident's own condition
*is* the acceptance condition. Every fact below is observed at a real boundary (an observing wrapper
on the real store round trip and the real provider call, the real health session, the real emitter).

**Incident question: 8 routes, 8 real ES requests, 0 dense expressions.**

```
Dense failure      : 8 provider calls, all raised EmbeddingError
                     400 FAILED_PRECONDITION "User location is not supported for the API use."
                     classified recoverable
Lexical ES request : 8 requests, expression set ["MatchTextExpr"] ONLY, limit 64,
                     64 real candidate ids each, from a store total of 155
Candidates         : real ES ids, not a fixture
Degraded selection : every returned chunk carries score_provenance.mode == LEXICAL_DEGRADED,
                     vector_similarity None, vector None, dense_score None
Merge / context    : 12 passages reach the answer layer
Final health       : overall degraded, evidence_completeness partial,
                     reason EMBEDDING_UNAVAILABLE, dense failed, lexical success
```

**The false-empty is gone:** the same question used to return an empty result with no lexical request
at all; it now issues the lexical work and serves 12 passages.

**End-to-end answer path** (the deployed image's real `dialog_service.async_chat`): 10/10 checks
PASS — no exception (this is where the absent `vector: None` used to raise inside `insert_citations`),
**584** characters of answer produced, 12 chunks referenced, exactly **one** `retrieval_health` in the
payload, DTO exposing **only** `{overall, evidence_completeness, degradation_reason}` — the leg map and
per-leg reasons stay in the operator event — one P0-7 event whose legs (`dense: failed`,
`lexical: success`) and `overall`/`reason` match the user DTO, and no sensitive marker in the
response.

Three first-attempt failures were **probe defects, not product defects**, and each is worth recording
because it shows what the live data actually looks like: the streaming answer had to be concatenated
from deltas (the terminal chunk's `answer` is empty by design); the user DTO deliberately has no
`legs` field, so asserting one was asserting a leak-free property backwards; and `content_with_weight`
is the passage text a client is *supposed* to receive, and is only a leak marker in the P0-7 log.

### HTTP leg — EXECUTED, 8/8 PASS

A real HTTP call through the running server process, `POST /api/v1/chat/completions` with a session
token minted by the application's own serializer for the assistant's **owner** (tenant
`a9e28731ab7011f19b833887d563fb04`): **200**, a **670-character** answer, **12** referenced chunks,
exactly **one** `retrieval_health` in the payload with `overall=degraded` /
`EMBEDDING_UNAVAILABLE`, a user DTO exposing only `{overall, evidence_completeness,
degradation_reason}`, and no sensitive marker anywhere in the response.

The definitive P0-7 evidence is now in the **server process's own log stream** (PID 1), one line per
turn, captured here verbatim from `docker logs`:

```json
{"contract_valid": true, "event": "retrieval_health", "evidence_completeness": "partial",
 "legs": {"decomposition": "success", "dense": "failed", "followup": "not_triggered",
          "lexical": "success", "rerank": "not_triggered"},
 "overall": "degraded", "reason": "EMBEDDING_UNAVAILABLE",
 "routes_attempted": 8, "routes_succeeded": 8, "schema_version": "1.0"}
```

Nine fields, exactly one line for a turn that ran eight routes, `dense: failed` with `lexical:
success` — the operator event and the user DTO agree, and neither carries anything sensitive.

**Three earlier failures of this leg were probe defects, and it is worth recording exactly what each
was**, because the first draft of this report wrongly reported the leg as unexecutable:

1. `POST /v1/chat/completions` → 404: the path is `/api/v1/...`; `v1/...` alone is not mounted.
2. `POST /api/v1/chats/<id>/completions` → `200` with `{"code":108,"data":false,"message":"no
   authorization"}`. This route is **deprecated** and the connector authorization layer stops the
   request before the chat handler runs. It is *not* attributable to this repair (neither repaired
   file references the connector layer, and every byte on that path is identical to the previously
   deployed image), but the currently supported route works.
3. `/api/v1/chat/completions` with a token minted for `User.select().first()` → the same `108`: this
   deployment has four users in different tenants, and a token for the wrong tenant is refused even
   though the token itself is valid. Minting for the assistant's owner succeeded.

The stream framing was a fourth probe defect: each frame is `data:{"code":0,"message":"","data":{…}}`,
so the turn's payload is nested under an outer envelope and the answer arrives as deltas whose
terminal frame carries the reference and `final: true`.

---

## 5. Q/GDW live checks

Measured live on the deployed candidate. The live path uses `rerank_candidates_count=64` (the
production default) while the frozen facts were recorded in the original 30-candidate window; the
live ranks reproduce the production-probe ranks **exactly** in both windows, which is itself evidence
that the repair did not disturb the lexical ordering.

| fact | live rank | production probe (window 30) | frozen fact | status |
| --- | --- | --- | --- | --- |
| 三芯 `d1d75672f2dbc333` on the incident question | **28** | 28 | inside the original 30 | **PASS** |
| 单芯 `b5aaf72bcd33d44a` on the incident question | **38** | 38 | outside the original 30 | **PASS** (38 > 30; inside the live 64) |
| 单芯 on the control question | **28** | 28 | inside a legal window | **PASS** |
| 三芯 on the STRUCTURE question | **27** | 27 | not a frozen fact | measured only |

The window was read at the production value and **never widened or narrowed**: one lexical pass per
route, no threshold, window, top-k or reranker change of any kind.

**One outcome the operator must see plainly:** the 三芯 target **is** inside the original question's
candidate window at rank 28 and **is** inside some route's window, but it does **not** survive into
the 12 passages that reach the answer layer, and neither does the STRUCTURE target (rank 27 in
window). That is a **selection/cut outcome on a composite question competing 8 routes for 12
passages**, not a dense-failure outcome: before this repair the same question returned nothing at all,
so there is no regression to attribute, and no parameter was adjusted to move it — exactly as this
window requires. The single-core control target does survive (it is the first passage returned),
which is the control that shows the degraded path can carry a target through.

---

## 6. Verdicts

| verdict | result |
| --- | --- |
| `CANDIDATE_IMAGE` | `my-wenruorag:repair-798288f8` = `sha256:6e926b5d8ef641d15a4ef623002531a5490b54154e0fa93648ff3cd61fb41bd0`, FROM `my-wenruorag:p0-7-obs-9f3d2c79` (= `ea93cd3bb795`) |
| `IMAGE_GATE_STATUS` | **PASS** — 61/61 repair gates + 4/4 P0 behavioural gates inside the candidate image, no host bind mount of the code under test |
| `LIVE_DENSE_FAILURE_OBSERVED` | **YES** — 8 provider calls, all `EmbeddingError`, `400 FAILED_PRECONDITION`, location restriction |
| `LIVE_LEXICAL_EXECUTED_AFTER_DENSE_FAILURE` | **YES** — 8 real `MatchTextExpr` ES requests, 64 candidates each, no dense expression sent |
| `FALSE_EMPTY_ELIMINATED` | **YES** — 12 passages served and a 584-character answer produced on the question that previously returned empty |
| `QGDW_THREE_CORE_CANDIDATE_STATUS` | rank **28** in the original question's window — **in window** (frozen fact intact); also present in another route's window |
| `QGDW_THREE_CORE_FINAL_STATUS` | **not** in the final 12 passages — a selection/cut outcome on an 8-route composite question, reported, not tuned for |
| `QGDW_SINGLE_CORE_MAIN_WINDOW_STATUS` | rank **38** — outside the frozen 30 window (inside the live 64); window **not** widened |
| `QGDW_SINGLE_CONTROL_STATUS` | rank **28**, inside the window, **survived** and returned first |
| `HEALTH_DTO_HONEST` | **YES** — `degraded` / `EMBEDDING_UNAVAILABLE`, matching the observed execution; exactly one `retrieval_health` in the live HTTP payload; DTO exposes `{overall, evidence_completeness, degradation_reason}` and no internals |
| `P0_6_STATUS` | **PASS** — the live HTTP response carries exactly one notice trigger with `overall=degraded`, and `web/dist` is byte-identical (1002 files) to the accepted production frontend, so the notice path is unchanged. A browser re-run was **not** executed in this window (that is P0-6's own acceptance) |
| `P0_7_STATUS` | **PASS — live in the server process's own log**: exactly one `[RetrievalHealth]` line per turn, exact nine-field set, `routes_attempted 8 / routes_succeeded 8`, `legs.dense=failed` with `legs.lexical=success`, `overall`/`reason` matching the user DTO, no leak markers |
| `HEALTHY_PATH_REGRESSION` | **NONE** — identical result dicts against the frozen pre-repair pipeline, byte-identical ES call trace, one provider call, identical health DTO (non-vacuity asserted) |
| `RESOURCE_LEAK_STATUS` | **PASS** — 12 timeout cycles with no thread or budget leak; live: 0 restarts, no OOM, datastores untouched |
| `DEGRADED_CONTROL_FLOW_VERDICT` | **PASS** |
| `RETRIEVAL_QUALITY_VERDICT` | **NOT ESTABLISHED** — the 三芯 and STRUCTURE targets do not survive the cut; no parameter was tuned; G4 forbids comparing against a healthy baseline while a required leg is degraded |
| `G4_STATUS` | **BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY** |
| `LATEST_TAG` | `my-wenruorag:latest` → **`6e926b5d8ef6`** (promoted after live acceptance) |
| `ROLLBACK_TAG` | `my-wenruorag:rollback-pre-p0-20260927` → `c50436820cb9` — **unchanged**; previous production retained as `my-wenruorag:p0-7-obs-9f3d2c79` → `ea93cd3bb795` |
| `P1_2_STATUS` | **PAUSED** — nothing in the image, nothing in this window |
| `PRODUCTION_FINAL_STATE` | running `my-wenruorag:repair-798288f8` = `6e926b5d8ef6`, up, 0 restarts, not OOM-killed; 5 KBs and the Gemini binding unchanged (KEY_2 `062bcd934443`, KEY_1 absent); ES mapping fingerprint, 486 docs, 42 deleted and the index unchanged; assistant retrieval parameters unchanged; only natural LLM-cache TTL churn in Redis (95→96 keys, the same 5 non-expiring keys including the DB1 secret) |

**Rollback path if required:** re-run compose with the P0-7 override only (dropping
`deploy/repair_baseline/repair_candidate_override.yml`), which restores
`my-wenruorag:p0-7-obs-9f3d2c79` = `ea93cd3bb795`; the pre-P0 anchor `c50436820cb9` is untouched.

Stopping here. P1-2 is not resumed.
