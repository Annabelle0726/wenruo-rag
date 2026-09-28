# Phase B — P0 Deployment Readiness (read-only / static audit)

Audit date: this round. Method: read-only inspection of the working tree, the running container and the
local image store. **No retrieval behaviour was changed, no code was modified, no container file was
patched, no service was restarted, and no image was tagged or rebuilt.**

## Overall verdict

| # | item | verdict |
| --- | --- | --- |
| 1 | Four insertion points truly on the runtime path | **FAIL — BLOCKED BY REVISION DRIFT** |
| 2 | API backward-compatibility audit | **PASS (with two obligations)** |
| 3 | Exception-boundary audit | **PASS (with one hard constraint)** |
| 4 | Deployment rollback prepared | **ACTION REQUIRED — no rollback tag exists yet** |

Because not all four are PASS, the rebuild is **not ready for approval**. Item 1 needs a decision from you
(§1.3), and item 4 needs a one-command preparation step (§4).

---

## 1. Runtime-path verification

### 1.1 The entry point is genuinely on the live path — confirmed

| hop | evidence |
| --- | --- |
| production caller imports the entry point | `api/db/services/dialog_service.py:53` — `from rag.retrieval import retrieve_multi_route` |
| production caller invokes it | `api/db/services/dialog_service.py:897` — `kbinfos = await retrieve_multi_route(` |
| package re-export | `rag/retrieval/__init__.py:62` — `from rag.retrieval.pipeline import empty_kbinfos, retrieve_multi_route` |
| entry definition | deployed `rag/retrieval/pipeline.py:190` — `async def retrieve_multi_route(` |
| route fan-out | deployed `rag/retrieval/multi_route.py:327` — `hits = await asyncio.gather(*[_guard(query) for query in routes])` |
| per-route call | `multi_route.py:203 def _retrieve_route(...)`, `:222 async def _call(threshold)`, `:260 return RouteResult(...)` |
| aggregation / return | inside `retrieve_multi_route`, via nested `_retrieve` (deployed `pipeline.py:291 async def _retrieve(queries, doc_scope)`) and `empty_kbinfos()` (`pipeline.py:66`) |

So `dialog_service → retrieve_multi_route → route execution → aggregation → synthesis` is a real chain, and
the four intended insertion points (route loop, embedding boundary, plan layer, aggregation/DTO) sit on it.
The call site line number (897) also matches the container forensics report, which is consistent with
`dialog_service.py` being identical; `../api` files were **not** line-count-diffed, so treat that one hop as
consistent-but-not-fully-diffed.

### 1.2 The blocking finding: the tree is not the deployed retrieval revision

Line counts, deployed container versus working tree:

| file | deployed | working tree | match |
| --- | --- | --- | --- |
| `../rag/retrieval/multi_route.py` | 337 | 337 | yes |
| `../rag/retrieval/decomposition.py` | 396 | 396 | yes |
| `../rag/retrieval/rerank.py` | 740 | 740 | yes |
| `../rag/retrieval/pipeline.py` | **329** | **475** | **no** |
| `../rag/retrieval/health.py` | absent | 352 | new |
| `../rag/retrieval/health_producers.py` | absent | 254 | new |

Function inventory of the drifted file:

| definition | deployed `pipeline.py` | working tree `pipeline.py` |
| --- | --- | --- |
| `empty_kbinfos` | :66 | :67 |
| `core_document_followup` | :71 | :72 |
| `cross_part_fallback` | **absent** | **:205 (module level)** |
| `retrieve_multi_route` | :190 | :307 |
| `_retrieve` | **:291, nested inside the entry point** | **:408, module level** |

**Interpretation.** The drift is confined to one file, but it is not cosmetic: the tree carries an entire
retrieval-behaviour feature (`cross_part_fallback`) that the running deployment does not have, and it has
restructured `_retrieve` from a nested closure into a module-level function. A rebuild from HEAD would
therefore **ship a retrieval-behaviour change, not just health instrumentation** — which contradicts this
phase's own constraint of not changing retrieval behaviour.

### 1.3 The decision item 1 needs

- **Option A (recommended).** Apply the four insertion points to the **deployed** `pipeline.py` revision
  (`329`-line version, `retrieve_multi_route` at `:190`, nested `_retrieve`) and deploy **only** the two new
  modules plus those anchors. This keeps the deployment a pure observability change and keeps every Phase A
  measurement valid, because Phase A characterized exactly that revision. Cost: the anchors must be written
  against the deployed file, which lives only inside the image and must be extracted read-only for the diff.
- **Option B.** Adopt the tree revision as the new deployment baseline. Then the drift (`cross_part_fallback`,
  hoisted `_retrieve`, and any other tree-only change in that file) enters production knowingly, and the
  Phase A/B gates must be re-run against the new baseline before the silent-degradation defect can be called
  closed.

I am not choosing unilaterally: Option A preserves the "no retrieval behaviour change" constraint, Option B
widens the change surface. The audit's recommendation is **A**.

---

## 2. API backward-compatibility audit

### 2.1 Consumer inventory and how each one touches the result object

Reviewed 250 of 304 `kbinfos` occurrences directly plus a targeted search for every strict-shape pattern.

| consumer | access pattern | additive key safe |
| --- | --- | --- |
| `rag/prompts/generator.py:168 kb_prompt` | `chunks = kbinfos["chunks"]` — single key read | yes |
| `dialog_service.py:574 _citation_pool` | `pool = deepcopy(kbinfos)` | yes |
| `dialog_service.py:594 repair_bad_citation_formats` | `len(kbinfos["chunks"])` | yes |
| `dialog_service.py:914-937` post-processing | `kbinfos["chunks"]`, `kbinfos["doc_aggs"]`, `.get(...)`, `.extend(...)` | yes |
| `dialog_service.py:956` response | `yield {"answer": ..., "reference": kbinfos, ...}` | see 2.2 |
| `dialog_service.py:973` | `kbinfos.get("generic_fallback")` | yes — existing additive key |
| `rag/advanced_rag/harness/tools/search.py:117 _normalize` | returns the same dict, `.get("chunks")` | yes |
| `rag/advanced_rag/harness/memory.py:111` | `kbinfos.setdefault("memory", [])` | yes — existing additive key |
| `rag/advanced_rag/agentic_rag_graph.py:1174/1504` | `dict(kbinfos, chunks=...)`, `kbinfos["pre_summary"] = ...` | yes — existing additive keys |

Strict-shape search across the whole tree for `chunks, doc_aggs`, `doc_aggs, total`, `= kbinfos.keys()`,
`set(kbinfos)`, `**kbinfos`, `for a, b in kbinfos`, `len(kbinfos)`, `kbinfos.items()` returned **3 matches,
all benign**:

1. `tools/scripts/retrieval_reproducibility_probe.py:335` — `.items()` iteration in **my own** diagnostic
   tooling, not production;
2. `test/unit_test/api/db/services/test_gaussdb_dialog_sql.py:591` — a helper *signature* with positional
   arguments named `chunks, doc_aggs`;
3. `test/unit_test/api/db/services/test_dialog_service_citation_pool.py:33` — a fixture builder
   `_kbinfos(chunks, doc_aggs=None)`.

**No strict unpacking, no key-set assertion, no splatting, no dict-length assumption and no schema
validation that would reject an extra key exists in the production path.** The precedent is decisive: this
codebase already carries additive keys (`generic_fallback`, `memory`, `pre_summary`) through the same
objects, so adding `retrieval_health` follows an established pattern.

### 2.2 The two obligations that remain

1. **Client-visible surface.** `dialog_service.py:956` yields the whole `kbinfos` object as the response
   `reference` field, so `retrieval_health` will appear in API responses. Server-side code is safe; the
   **front-end and any external API consumer must be confirmed tolerant of an extra key**. Strict JSON
   clients that validate `reference` against a closed schema would break. This is a product-side check, not
   a code check.
2. **Attach point.** The field must be attached where `kbinfos` is produced (the retrieval entry), **not**
   re-attached inside `dialog_service`'s post-processing, so that `deepcopy(kbinfos)` citation paths and the
   `_citation_pool` logic keep seeing exactly one authoritative health block.

---

## 3. Exception-boundary audit

### 3.1 The existing policy, verbatim from the deployment

`../rag/retrieval/multi_route.py` (identical deployed and in-tree):

```
:306        try:
:323        except Exception as exc:  # noqa: BLE001 - one dead route must not sink the others
:324            _LOG.warning("[Multi-route] route %r failed: %s", query[:80], exc)
:325            return RouteResult(query=query, failed=True)
:327    hits = await asyncio.gather(*[_guard(query) for query in routes])
```

Conclusions:

- Route failures are **deliberately isolated**: the exception is logged as a warning and converted into a
  failed result. It never propagates out of the route loop.
- `RouteResult.failed` already exists (`multi_route.py:88`, `failed: bool = False`) — **the health producer
  should be attached where that flag is already computed**, which is exactly the direct execution point and
  requires no new control flow.
- The handler catches `Exception`, not `BaseException`, so cancellation and interpreter-level exceptions
  still propagate.
- `_guard` never raises for route failures, so `asyncio.gather` at `:327` is not a second swallowing point;
  a `BaseException` raised inside `_guard` would still tear down the gather.

### 3.2 Does `HealthSession.route_execution()` change that semantics?

It catches `Exception` only — the same class the deployment already isolates — so for the deployed policy it
is **equivalent, not a change**: originally-isolated exceptions stay isolated; `BaseException` still
propagates.

However, the audit found one genuine hazard that must be written into the deployment rules, because
`route_execution` as written **discards each route's return value and reports counts**:

- If it were used as the deployed control flow, it would replace
  `return RouteResult(query=query, failed=True)` and break the `RouteResult`/`failed` contract that
  `asyncio.gather` and the merge step consume. That would not just be an exception-policy change, it would
  be a functional regression.

**Binding rules for the wiring (preconditions, not suggestions):**

1. **Reporter-only.** Health recording happens *inside* the existing `except` handler, next to the existing
   `_LOG.warning` and `RouteResult(failed=True)`. `HealthSession.route_execution()` stays a harness helper
   and **must not** become production control flow.
2. **No new catching layer above `_guard`.** Nothing may be wrapped around `asyncio.gather` or around
   `retrieve_multi_route`, so every exception that propagates today still propagates.
3. **`except Exception` only.** Introducing `except BaseException` (or a bare `except:`) anywhere in this
   path is forbidden; instrumentation must never be able to swallow a cancellation.
4. **Verification obligation.** The live gate must include a check that an exception which propagates today
   (e.g. raised from the aggregation step after the route loop) still reaches `dialog_service` unchanged.

Under those rules item 3 is **PASS**: the instrumentation adds no exception policy.

---

## 4. Deployment rollback preparation

### 4.1 Current state — no rollback tag exists

| fact | value |
| --- | --- |
| images present | exactly one: `my-wenruorag:latest` |
| image id | `c50436820cb9` → `sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0` |
| size / age | 13.9 GB / created about 5 hours before this audit |
| running container `wenruo-rag-cpu` image | `my-wenruorag:latest`, same id `sha256:c50436820cb9…` |

There is **no preserved previous tag and no second image**, so today a rebuild that reuses the `latest` tag
would leave the rollback target reachable only by numeric image id. That is exactly the "switch back, do not
fix on the spot" requirement's weak point.

### 4.2 Required preparation (one command, deliberately not executed in this read-only round)

```
docker tag c50436820cb9 my-wenruorag:rollback-pre-p0-20260927
docker image inspect my-wenruorag:rollback-pre-p0-20260927 --format '{{.Id}}'
```

### 4.3 Rollback runbook for the P0 deployment

1. **Before building:** run the tag in 4.2 and record the id/digest in the deployment log. This is the
   *only* step that makes "切回旧 image" possible.
2. **Build under a distinct, immutable tag:** `my-wenruorag:p0b-8ae3ee3e9` (never reuse `latest` for the new
   build, so the old tag is untouched).
3. **Run the live gate** from the new tag only after the container is recreated on it: the positive
   injections (synthetic dense 429, planner failure, lexical failure) plus the **negative control** on a real
   query. Note that a restart alone cannot apply code, which is why the container must be recreated from the
   new image, not restarted.
4. **On any gate failure:** recreate the container from `my-wenruorag:rollback-pre-p0-20260927` (or by the
   recorded image id) and stop. Do not patch the failed image in place.
5. **Only after the gate passes:** consider promoting the new build to `latest` in a separate, explicit step.

### 4.4 Scheduling constraint the rollback plan must respect

The **negative control needs a working dense leg**, and the remote embedding quota is a daily allowance that
this project's own probing has already exhausted today. Running the live gate before the reset would produce
a spurious failure (a degraded dense leg), which the gate would correctly refuse. The deployment window must
therefore be scheduled after the quota resets, or the gate must be explicitly recorded as
`BLOCKED_BY_QUOTA` rather than passed.

---

## 5. Audit artefacts and limits

- Read-only: tree inspection, `docker images`, `docker inspect`, in-container `wc`/`grep`. Nothing was
  rebuilt, tagged, restarted, patched, or written to any index or configuration.
- Coverage limits stated honestly: 250 of 304 `kbinfos` occurrences were read directly (the remainder were
  the tail of the same search and were covered by the targeted strict-shape search in §2.1); `../api` files
  other than `dialog_service.py` were checked by pattern search, not line-diffed; the drift between
  deployed and in-tree `pipeline.py` was established by line counts and function inventory, not by a full
  textual diff — the full diff is step one of Option A in §1.3.
