# Phase B — P0-B Candidate Build and Image-Level Semantic Gate

**Status: image built under an immutable tag, image-level gate PASSED, production untouched.**
No `latest` overwrite, no restart, no production recreate, and no live acceptance (quota exhausted →
`BLOCKED_BY_QUOTA`, no substitute PASS claimed).

## 1. Pre-build correction: answer policy decoupled from health

Hard interception item, implemented as a *gate* rather than a promise:

- `rag/retrieval/health_bridge.py` now carries `ANSWER_POLICY_ENFORCEMENT = "disabled"`,
  `answer_policy_enforced()` (always `False`) and `FORBIDDEN_POLICY_SYMBOLS`.
- `tools/scripts/p0_option_a_candidate.py` gained the check
  **`no_answer_policy_enforcement_symbols`**, which fails the build if any answer-policy symbol
  (`decide_answer_action`, `required_notice`, `AnswerAction`, `refuse_insufficient`, `refuse_failed`)
  appears in the candidate sources. Both files **PASS**.
- `PLAN_EMPTY` and `THRESHOLD_EMPTY` reasons are retained as approved.
- Import anchor position left exactly as reviewed — no widening of the diff.

Retrieval health is therefore **collected, aggregated and exposed (DTO / trace / metrics) while the
baseline answer flow is untouched**. Nothing on the retrieval path can turn `evidence_state = partial`
into a refusal, because nothing on the retrieval path calls the policy:

| file in the image | `decide_answer_action` occurrences | meaning |
| --- | --- | --- |
| `pipeline.py`, `multi_route.py`, `decomposition.py`, `rerank.py`, `query_router.py`, `chunk_profile.py`, `health_producers.py` | **0** | no call site, no reference at all |
| `health.py` | 2 | the definition plus the call inside `required_notice`, itself never called |
| `health_bridge.py` | 2 | both inside the `FORBIDDEN_POLICY_SYMBOLS` tuple used by the gate |

## 2. Build

Derived image, base pinned by digest — the same pattern the project already uses for phase builds
(`Dockerfile.p1-permissions`, whose own header notes this is a verification artifact rather than a release
path; a normal `docker compose build` is still required before release, and I carry that caveat forward).

```
FROM my-wenruorag@sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0
COPY pipeline.py            /ragflow/rag/retrieval/pipeline.py            # 341-line candidate
COPY multi_route.py         /ragflow/rag/retrieval/multi_route.py         # 340-line candidate
COPY health.py health_producers.py health_bridge.py /ragflow/rag/retrieval/
```

`docker build -t my-wenruorag:p0b-891572a71 deploy/p0_build` → exit 0.

| tag | id | note |
| --- | --- | --- |
| `my-wenruorag:p0b-891572a71` | `99d0ee210004` | new candidate, immutable tag |
| `my-wenruorag:latest` | `c50436820cb9` | **untouched** |
| `my-wenruorag:rollback-pre-p0-20260927` | `c50436820cb9` | **untouched**, rollback anchor |

## 3. Image-Level Semantic Gate (temporary container, `--rm`)

Extracted from inside the built image, not from the host tree:

| check | result |
| --- | --- |
| `pipeline.py` lines | **341** (candidate; baseline was 329) |
| `multi_route.py` lines | **340** (baseline 337) |
| `health.py` / `health_producers.py` / `health_bridge.py` | present, 352 / 254 / 162 lines |
| `cross_part_fallback` anywhere in `/ragflow/rag/retrieval/` (including `.pyc`) | **0 occurrences** → HEAD's feature is absent |
| module-level `async def _retrieve` | **absent**; nested form present exactly once → HEAD's refactor is absent |
| health anchors in `pipeline.py` | `begin_retrieval_health` ×2 (import + call), `attach_retrieval_health` ×4 (import + three returns) |
| health anchors in `multi_route.py` | `report_route_success` ×1, `report_route_failure` ×1 — reporter calls only |

**Docker context is clean.** Untouched retrieval files are hash-identical to the production container:

| file | candidate image | production container |
| --- | --- | --- |
| `decomposition.py` | `3486a928…d0bae` | `3486a928…d0bae` ✔ |
| `rerank.py` | `1152c59a…e25cc` | `1152c59a…e25cc` ✔ |
| `query_router.py` | `51bf6a62…991c1` | `51bf6a62…991c1` ✔ |
| `chunk_profile.py` | `d77ac160…f504e` | `d77ac160…f504e` ✔ |
| `pipeline.py` | `c9174c52…effae7` (candidate) | `f3a1af56…6c6bb` (deployed baseline — identical to the extracted copy, confirming the extraction was faithful) |
| `multi_route.py` | `9af6fc5e…59264` (candidate) | `0c13ccca…f1c21` (deployed) |

The two changed files are exactly the two the patch touches; nothing else moved.

## 4. API client compatibility audit

**Server side (unchanged from the readiness audit):** no strict unpacking, key-set assertion, splatting or
length assumption in production code. The additive key rides inside the response `reference` object
(`dialog_service.py:956`), with `generic_fallback`, `memory` and `pre_summary` as precedent.

**Web front-end (new evidence this round):** consumers of `reference` use dot access and tolerate extra
keys:

- `web/src/components/message-item/index.tsx:187` — `referenceChunks={reference.chunks}`
- `web/src/components/floating-chat-widget-markdown.tsx:157` — `reference.doc_aggs`
- `web/src/components/markdown-content/reference-utils.ts:83` — `reference.chunks[chunkIndex]`
- A repository-wide search for strict response validation (`zod .strict()`, `additionalProperties: false`)
  found **no** strict schema applied to the chat-completion response; the `z.object` hits are form/config
  schemas, and the single `additionalProperties: false` is a Python-component JSON-schema editor setting,
  not a response validator.

**Two caveats recorded honestly.** (1) `web/src/pages/next-chats/utils.ts:29` calls
`data.reference.reduce(...)`, i.e. some *other* endpoint returns `reference` as an array — the additive key
applies only to the dict-shaped `/chats` responses, so any client assuming homogeneity across endpoints
already had to handle both shapes. (2) External API consumers outside this repository cannot be verified
from here; a client validating `reference` against a closed schema would break. This remains a
release-time obligation, not a build-time blocker.

## 5. What is still not done

| item | status |
| --- | --- |
| Build | **DONE** — `my-wenruorag:p0b-891572a71` |
| Image-level gate | **PASS** |
| Production recreate | **NOT AUTHORIZED / NOT EXECUTED** |
| Live P0-C acceptance | **BLOCKED_BY_QUOTA** — the healthy path requires a real dense leg; no PASS claimed |
| Release path | still requires a normal `docker compose build`, per the existing phase-Dockerfile caveat |

**Recreate runbook (on authorization):** recreate the production container from
`my-wenruorag:p0b-891572a71` (not a restart — a restart cannot apply code), run the positive injections
plus the negative control live, and on any failure recreate from
`my-wenruorag:rollback-pre-p0-20260927` = `sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0`
and stop. Schedule after the daily embedding allowance resets; before then the live gate must be recorded
as `BLOCKED_BY_QUOTA`.

State guard at the end of this round: `latest` still `c50436820cb9`, production container `StartedAt`
unchanged, only the five production containers running, and the temporary gate container removed.
