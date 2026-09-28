# Phase B — P0 Option A: Rebase Baseline, Rollback Tag and Semantic-Diff Report

**Status: candidate prepared, gate PASSED, build NOT executed.** No image was built, `latest` was not
overwritten, the container was not restarted or recreated, and no live acceptance was attempted.

## 1. Rollback tag — executed and verified

Approved command, run once:

```
docker tag c50436820cb9 my-wenruorag:rollback-pre-p0-20260927
```

| verification | value |
| --- | --- |
| tag id after tagging | `sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0` |
| required digest | `sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0` |
| exact match | **True** |
| `my-wenruorag:latest` after tagging | `sha256:c50436820cb9…90b0` (unchanged) |
| running container image | `sha256:c50436820cb9…90b0` |
| container `StartedAt` | unchanged before and after |

**Runbook record:** rollback target = `my-wenruorag:rollback-pre-p0-20260927` =
`sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0`. Recreate the container from
this tag (or by this id) on any live-gate failure, then stop — no in-place repair.

## 2. Option-A baseline — extracted read-only from the running container

| property | value |
| --- | --- |
| source | `/ragflow/rag/retrieval/pipeline.py` inside `wenruo-rag-cpu`, read with `docker exec cat` (read-only) |
| extracted copy | `../deploy/p0_baseline/pipeline.py` |
| lines | **329** (container `wc -l` reports 329 — identical) |
| sha256 of the extract | `F3A1AF567F7F3DBC84C77AA4E91A2540449083B28D69E251E9403E273386C6BB` |
| `multi_route.py` | **not extracted**: the in-tree file matches the deployed file line for line (337 lines), confirmed in the readiness audit |

## 3. Candidate and diff

| artefact | detail |
| --- | --- |
| `../deploy/p0_baseline/pipeline.p0-candidate.py` | 329 → **341** lines |
| `../deploy/p0_baseline/multi_route.p0-candidate.py` | 337 → **340** lines |
| `../deploy/p0_baseline/p0_option_a.patch` | unified diff, **6 hunks**, 69 lines |
| `../rag/retrieval/health_bridge.py` | new reporter-only bridge (no retrieval logic) |
| `../rag/retrieval/health.py`, `health_producers.py` | unchanged from the P0-A/P0-B commits |

The instrumentation is exactly the reporter-only shape you specified:

```
existing control flow ──▶ execution ──┬─▶ RouteResult           + report success
                                      └─▶ failed RouteResult    + report failure/reason
```

Concretely, in `_guard`:

```python
        try:
            result = await _retrieve_route( ... )      # arguments byte-identical to baseline
            report_route_success()                     # reporter only
            return result                              # same object the baseline returned
        except Exception as exc:  # noqa: BLE001 - unchanged
            _LOG.warning( ... )                        # unchanged
            report_route_failure(exc)                  # reporter only
            return RouteResult(query=query, failed=True)   # unchanged
```

and in `retrieve_multi_route`: `begin_retrieval_health()` after question normalisation, a reporter call plus
the additive attach on each of the three return paths, and imports. **`HealthSession.route_execution()` is
not used anywhere in the candidate** — it stays a host-side harness helper, so the `RouteResult` contract
cannot be shadowed or lost.

## 4. Semantic-Diff Gate — automated, both files PASS

Run by `../tools/scripts/p0_option_a_candidate.py`; result in `deploy/p0_baseline/p0_option_a_semantic_diff_result.json`.

| check | pipeline.py | multi_route.py |
| --- | --- | --- |
| `function_set_unchanged` | PASS | PASS |
| `all_signatures_unchanged` | PASS | PASS |
| `except_types_unchanged` | PASS | PASS |
| `try_block_count_unchanged` | PASS | PASS |
| `preserved_call_sites_unchanged` | PASS | PASS |
| `return_count_unchanged` | PASS | PASS |
| `returns_only_wrapped_not_altered` | PASS | PASS |
| `only_reporter_calls_introduced` | PASS | PASS |
| `no_module_level_statement_removed` | PASS | PASS |
| `module_level_additions_are_import_only` | PASS | PASS |
| `module_level_sequence_preserved` | PASS | PASS |

**Verdict: PASS.**

What each guarantee actually proves:

- `preserved_call_sites_unchanged` compares the full AST dump of every retrieval call site
  (`_retrieve_route`, `multi_route_retrieve`, `rerank_chunks`, `merge_route_hits`,
  `core_document_followup`, `empty_kbinfos`) **and every `RouteResult(...)` construction**. Argument
  names, positions, literals and keywords are identical, so routing, call parameters, candidate merging
  and ordering inputs are unchanged.
- `except_types_unchanged` + `try_block_count_unchanged` prove the exception policy is byte-identical:
  no handler was added, removed, widened or narrowed, and no `except BaseException` or bare `except`
  appeared. Isolated failures stay isolated; hard failures still propagate.
- `all_signatures_unchanged` proves no function signature moved, which is why the request-scoped session
  rides a `ContextVar` instead of a new parameter.
- `only_reporter_calls_introduced` proves the only new callables are the six reporter entry points.
- `returns_only_wrapped_not_altered` proves every changed return is either the baseline payload wrapped in
  exactly one `attach_retrieval_health(...)`, or the declared bind-then-return rewrite, each with a
  recorded proof (`multi_route_retrieve:result`, `_guard:result`): the temporary is assigned from an
  expression identical to the baseline return and is referenced exactly twice, so nothing can observe or
  mutate it in between.
- `module_level_*` prove the module structure is preserved apart from an import-only addition.

**Gate honesty.** The first two runs of this gate reported FAIL, and both failures were **defects in the
gate, not in the candidate**: it compared whole function bodies as if they were module-level statements
(every instrumented function looked "removed and re-added"), it did not recognise the declared
bind-then-return rewrite, and a string-prefix bug stopped the proof from firing. The gate was corrected
and re-run; the candidate code was not changed to make the gate pass.

## 5. Zero-retrieval-behaviour-change argument

1. Every retrieval call site is AST-identical (§4).
2. The exception policy is AST-identical, and route failures still produce the same
   `RouteResult(failed=True)` at the same point in the same handler.
3. The three result keys are produced by the same expressions; the candidate only wraps the returned dict
   in `attach_retrieval_health(...)`, which copies the dict and adds one key.
4. The bridge cannot influence retrieval: it never returns a control-flow value, never constructs or
   mutates `RouteResult`, and its only `try/except` encloses reporter bookkeeping. On any reporter
   failure, `attach_retrieval_health` returns the **original dict untouched**, so a reporter defect
   degrades observability, never retrieval.
5. No new module imports into the retrieval path beyond the bridge, and the bridge imports no retrieval
   behaviour (only the contract and producers).

## 6. API client compatibility (§2 of your gate)

- Server side: the additive key appears in the response `reference` object (`dialog_service.py:956`), and
  the strict-shape search found **no** key unpacking, key-set assertion, splatting or length assumption in
  production code — the only three matches were my own diagnostic tooling and two test fixtures.
- Established precedence in this codebase: `generic_fallback`, `memory` and `pre_summary` already travel
  as additive keys through the same object.
- **Remaining obligation before release, not before build:** confirm the front-end and any external API
  consumer tolerate an extra key inside `reference`. A client validating `reference` against a closed
  schema would break. This is a product-side check I cannot perform from here.
- The field is attached at the retrieval entry, so `deepcopy(kbinfos)` citation paths see exactly one
  health block.

## 7. Deployment and quota status

| item | status |
| --- | --- |
| rollback tag | **DONE** (digest verified) |
| baseline extraction | **DONE** (read-only) |
| semantic-diff gate | **PASS** |
| build | **NOT AUTHORIZED / NOT EXECUTED** |
| recreate container | **NOT AUTHORIZED / NOT EXECUTED** |
| live acceptance | **BLOCKED_BY_QUOTA** — the remote embedding allowance is exhausted, and the healthy path must be verified with a real dense leg. No PASS is claimed, and no substitute is accepted. |

## 8. Review points and limits

1. **Import placement.** The candidate inserts the bridge import immediately before
   `async def retrieve_multi_route(` rather than in the top import block, to keep the diff anchored and
   minimal. A reviewer may prefer relocating it to the module's import section; the gate accepts any
   import-only module-level addition, so that relocation is gate-neutral.
2. **Return analysis is subtree-wide**, so a nested function's changed return is also attributed to its
   parent function in the proof list. This is conservative (it checks more, not less).
3. **Edge-case mapping decisions recorded in the candidate:** an empty question reports a `PLAN_EMPTY`
   decomposition failure; an empty retrieval window reports a `selection` leg degraded with
   `THRESHOLD_EMPTY`. Both exist so that "nothing usable came back" can never be reported as a clean run
   — without them, an empty window with healthy legs would have produced `overall = degraded` with no
   reason code, i.e. a contract violation.
4. **Evidence stays conservative:** the candidate passes no authority validator, so
   `evidence_completeness` is capped at `partial` by design until the P1 validator exists. This means a
   constraint-bearing question will refuse under the deployed policy until that validator ships — a
   deliberate, visible consequence, not a defect.
5. **Coverage limit:** the diff was established against the extracted baseline and the in-tree
   `multi_route.py`; `../api` files outside `dialog_service.py` were checked by pattern search only.
