# Retrieval Release — 20261002-retrieval-phase2 (Phase 0 + 1.1 + 2)

The approved candidate was promoted and production was switched to it. Every post-deploy check
passed; **no rollback was required.**

---

## PRE_DEPLOYMENT

Captured before anything was changed.

| field | value |
|---|---|
| production container id | `e114ffbdf14ab2ee50f280afa736d4c8360ecb9b6ced54babeee3250d423364a` |
| name | `wenruo-rag-cpu` |
| image id | `sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123` |
| image (config) | `my-wenruorag:latest` |
| status / running | `running` / `true` |
| StartedAt | `2026-10-01T23:11:27.6460965Z` |
| RestartCount | `0` |
| RestartPolicy | `unless-stopped` |
| ports | 80, 443, 9380, 9381, 9382, 9383, 9384 |
| network | `wenruo-rag_ragflow` |
| compose | project `wenruo-rag`, service `wenruo-rag-cpu`, config `docker/docker-compose.yml`, working dir `docker/` |

Pre-deploy health, for comparison: `GET /api/v1/language` → **HTTP 200**
`{"code":0,"data":{"language":"python"},"message":"success"}`

**Tag inventory before the switch** (baseline = `18711d10f035`):

| tag | image |
|---|---|
| `my-wenruorag:latest` | `18711d10f035` ← baseline / deployed |
| `my-wenruorag:release-20260930-fullbuild` | `18711d10f035` |
| `my-wenruorag:fullbuild-6892b3c33` | `18711d10f035` |
| `my-wenruorag:rollback-pre-fullbuild-20260930` | `7922b415a3c1` |
| `my-wenruorag:rollback-pre-usage-20260930` | `a0d29a9f8ec3` |
| `my-wenruorag:rollback-pre-doclist-20260930` | `44a3e3535984` |
| `my-wenruorag:phase-integration-candidate` | `c748d24e2e69` ← approved candidate |

The compose file selects the api image as `image: ${RAGFLOW_IMAGE:-my-wenruorag:latest}`, and
`docker/.env:135` held `RAGFLOW_IMAGE=my-wenruorag:latest`.

---

## RELEASE_TAG

Two **additive** tags were created (no existing tag was moved or deleted):

```
my-wenruorag:release-20261002-retrieval-phase2  -> sha256:c748d24e2e69a309c94b50c9740336bfe55dc10608792943f253025c377aa710
my-wenruorag:rollback-pre-phase2-20261002       -> sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123
```

The second is a deliberate extra anchor for this promotion, following the repository's existing
`rollback-pre-*` convention, so the baseline is unambiguous at rollback time.

`RAGFLOW_IMAGE` in `docker/.env` was repointed to the release tag so the promotion is durable — a
later `docker compose up` cannot silently revert to `latest`:

```diff
- RAGFLOW_IMAGE=my-wenruorag:latest
+ RAGFLOW_IMAGE=my-wenruorag:release-20261002-retrieval-phase2
```

**This is the only repository file changed by the deployment** (`git status: M docker/.env`). No
code, test, Dockerfile or compose file was touched. Reverting the release is that one line plus the
recreate below.

`my-wenruorag:latest` was **deliberately left pointing at the baseline**. No instruction asked for it
to move, and leaving it there keeps a known-good tag on the rollback anchor; the release tag is the
explicit pointer production uses.

---

## PRODUCTION_IMAGE

Production was recreated on the release tag with the api service only:

```
docker compose up -d --no-deps --force-recreate wenruo-rag-cpu
  Container wenruo-rag-cpu Recreated
  Container wenruo-rag-cpu Started
```

| field | before | after |
|---|---|---|
| container id | `e114ffbdf14a…` | **`96db07b46012b5a35dda91a093887a32337353164b9dd4eff1e92e8eff38f328`** |
| image id | `sha256:18711d10…` | **`sha256:c748d24e2e69a309c94b50c9740336bfe55dc10608792943f253025c377aa710`** |
| image (config) | `my-wenruorag:latest` | `my-wenruorag:release-20261002-retrieval-phase2` |
| running | true | **true** |
| RestartCount | 0 | **0** |
| StartedAt | `2026-10-01T23:11:27Z` | `2026-10-02T03:31:00.820441753Z` |

Only the api service moved. The four dependencies were **not** touched — `es01`, `mysql`, `redis`,
`minio` all still show `Up 4 hours (healthy)` with their original container ids (`--no-deps`).

---

## RUNTIME_FINGERPRINT

Read from inside the **running production container** after the switch; every value matches the
approved candidate:

| path | sha256 (first 16) |
|---|---|
| `rag/res/synonym.json` | `4bd49e89e08d8108` |
| `rag/retrieval/domain_facts.py` | `52c1fe7da30d2e8a` |
| `rag/retrieval/route_expansion.py` | `47f2073e8e975e1f` |
| `rag/retrieval/context_reservation.py` | `b7317a0872f6eb73` |
| `rag/retrieval/pipeline.py` | `acf8c7f7b888f1f7` |
| `rag/retrieval/rerank.py` | `4f288ed6155b0ca1` |

Loaded module paths, all under the deployed tree:

```
route_expansion   = /ragflow/rag/retrieval/route_expansion.py
domain_facts      = /ragflow/rag/retrieval/domain_facts.py
context_reservation = /ragflow/rag/retrieval/context_reservation.py
```

| probe | result |
|---|---|
| `reserve_for_question` in `rerank_chunks` bytecode | **True** |
| synonym entries | **7** |
| `lookup(设计使用寿命)` | `['设计使用年限']` |
| `lookup(设计寿命)` | `['设计使用年限']` |
| `lookup(寿命)` | `[]` *(by policy)* |

Fingerprint **matches**; no mismatch, so the rollback trigger did not fire.

---

## FROZEN_QA_POSTDEPLOY

Executed against the deployed release's runtime, 3 runs per question, the assistant's own parameters,
the real index and models. `life_cl` = passages carrying `不少于30`; `struct_cl` = passages carrying
`结构图纸`.

| QA | life_cl (3 runs) | struct_cl (3 runs) | dup | docs | tokens | latency (median) |
|---|---|---|---|---|---|---|
| QA-001 | 0,0,0 | 0,0,0 | 0 | 4 | 8758–8833 | 4.38 s |
| QA-002 | 1,1,1 | 0,0,0 | 0 | 3 | 6495 | 1.16 s |
| QA-003 | 0,0,0 | 0,0,0 | 0 | 6 | 8872 | 0.95 s |
| **QA-004** | **3,3,3** | **3,3,3** | 0 | 6 | 7318 | 2.75 s |
| QA-005 | 0,0,0 | 0,0,0 | 0 | 1 | 7271 | 1.82 s |

**QA-001/002/003/005: no regression.** Every count, document count and token count is identical to
the pre-deploy baseline (QA-001's baseline itself varied 8758/8833 across runs). These four questions
have `fact_types = 0` — the axis reader declines them, so the reservation never runs.

`duplicate chunks = 0` in all 15 frozen-QA runs.

---

## QA004_POSTDEPLOY

**QA-004 meets the requirement 3/3: design life AND structure evidence in every run.**

* **context:** `life_cl = 3,3,3` and `struct_cl = 3,3,3` — both required evidence classes present in
  the final context in all three runs.
* **answer:** `design_life_years = True` and the answer text states the structure requirement too.
  Captured excerpt:

  > …关于海缆附件（也就是终端和各种接头）的设计寿命和结构要求，其实是有明确说法的… **先说设计使用年限这块儿：**
  > 标准里写得挺清楚——无论是110kV还是220kV的海底电缆系统，接头的设计使用年限要求是**不少于30年**，
  > 终端的设计使用年限同样是**不少于30年**… **再说结构方面的要求：** 结构这块儿门道就多了…

* Compared with the pre-deploy baseline on the identical question: `life_cl 0,0,0 → 3,3,3` while
  structure evidence stayed present (`4,4,4 → 3,3,3`). This is the failing case the whole Phase 0 →
  1.1 → 2 chain was built for, and it is fixed **in production**.

---

## V5_POSTDEPLOY

`标准对终端和接头的结构以及设计使用年限是怎样规定的？`

| | pre-deploy baseline | post-deploy |
|---|---|---|
| `struct_cl` | **0,0,0** | **1,1,1** |
| `life_cl` | 6,6,6 | 6,6,6 |
| tokens | 6622 | 6858 |
| duplicates | 0 | 0 |

**3/3 runs carry structure evidence** — the requirement is met. The answer states the design life
with citations ("终端设计使用年限：不少于30年…") and covers the structure requirement.

---

## DATASET_SMOKE

| check | result |
|---|---|
| benchmark KB resolves | **True** — `9463d93eb97511f1938f2592e9bc6fe4`, **6 documents / 315 chunks**, embedding `f79e37e5ab7611f18ecb3887d563fb04` |
| document listing | 6 documents returned by `DocumentService.get_by_kb_id` |
| `GET /api/v1/datasets` | **HTTP 401** — route mounted and enforcing auth (not 404) |
| Elasticsearch index | unchanged; the whole-image diff proved 0 changes outside the 6 target files, and the index lives outside the image entirely |

Real dataset data reads correctly on the deployed release. No dataset anomaly, so the rollback
trigger did not fire.

---

## USAGE_SMOKE

| check | result |
|---|---|
| usage routes mounted | `/tenants/<id>/usage/my`, `/usage/summary`, `/usage/members`, `/usage/daily`, `/tenants/<id>/usage-budget` present in the deployed release |
| `GET /api/v1/tenants/a9e28731…/usage/summary` | **HTTP 401** — mounted, auth enforced |
| `GET /api/v1/tenants/a9e28731…/usage-budget` | **HTTP 401** — mounted, auth enforced |
| usage data intact (read-only) | `workspace_usage` 9 rows · `workspace_budget` 1 row · `workspace_usage_ledger` 1426 rows |

The usage subsystem is present and its data is intact; the endpoints answer rather than 404. No usage
anomaly, so the rollback trigger did not fire.

(Authenticated responses could not be exercised: this tenant has **no API token** in `api_token`, and
creating one would be a production data write, which this deployment did not perform. The 401s are
therefore the strongest non-invasive signal available, and the deeper checks above were run through
the deployed runtime.)

---

## FRONTEND_SMOKE

| check | result |
|---|---|
| `GET /` | **HTTP 200**, 3543 bytes |
| whole `/ragflow/web` tree hash, deployed container | `d87b8077b764bfc6cb9debcc560263fb65a711b838fbfd425ac84435b0742bc5` |
| whole `/ragflow/web` tree hash, baseline image | `d87b8077b764bfc6cb9debcc560263fb65a711b838fbfd425ac84435b0742bc5` |

**Identical.** The frontend is unchanged, proven both ways: the pre-build whole-image diff showed
0 changes across all 1013 `web/` files, and the live tree hash agrees byte-for-byte. No frontend
anomaly, so the rollback trigger did not fire.

---

## ROLLBACK_ANCHOR

The baseline is intact and reachable by **four** tags — nothing was deleted or overwritten:

```
my-wenruorag:latest                        -> 18711d10f035
my-wenruorag:release-20260930-fullbuild    -> 18711d10f035
my-wenruorag:fullbuild-6892b3c33           -> 18711d10f035
my-wenruorag:rollback-pre-phase2-20261002  -> 18711d10f035
```

`docker image inspect sha256:18711d10…` confirms the image is still present.

The approved candidate was **kept** as well:

```
my-wenruorag:phase-integration-candidate      -> c748d24e2e69
my-wenruorag:release-20261002-retrieval-phase2 -> c748d24e2e69
```

**No prune was run** (0 dangling images before and after).

Recorded rollback procedure, **not executed** because no trigger fired:

```powershell
# 1. revert the pointer
#    docker/.env:  RAGFLOW_IMAGE=my-wenruorag:latest
# 2. recreate only the api service
cd docker; docker compose up -d --no-deps --force-recreate wenruo-rag-cpu
# 3. verify
docker inspect wenruo-rag-cpu --format '{{.Image}}'   # expect sha256:18711d10…
```

---

## PRODUCTION_HEALTH

| field | value |
|---|---|
| container | `96db07b46012b5a35dda91a093887a32337353164b9dd4eff1e92e8eff38f328` |
| running / status | **true** / `running` |
| RestartCount | **0** |
| StartedAt | `2026-10-02T03:31:00.820441753Z` |
| image | `sha256:c748d24e2e69…` via `my-wenruorag:release-20261002-retrieval-phase2` |
| `GET /api/v1/language` | **HTTP 200** `{"code":0,"data":{"language":"python"},"message":"success"}` |
| `GET /` (frontend) | **HTTP 200**, 3543 bytes |
| dependencies | `es01`, `mysql`, `redis`, `minio` — all `Up 4 hours (healthy)`, untouched |

All eight rollback triggers were checked and **none fired**:

| trigger | outcome |
|---|---|
| QA-004 regression | **no** — life 3/3 with structure retained |
| frozen QA regression | **no** — QA-001/002/003/005 identical |
| Dataset / Usage / frontend anomaly | **no** — all three smokes clean |
| runtime fingerprint mismatch | **no** — all six hashes match the candidate |

Deployment side effects: `RAGFLOW_IMAGE` repointed in `docker/.env` (the only repository file
changed, left uncommitted); the measurement script was removed from `/tmp` inside the container; the
two throwaway measurement containers from the previous phase were already removed. **No code was
modified, nothing was rebuilt, `latest` was not retagged, and no prune was run.**
