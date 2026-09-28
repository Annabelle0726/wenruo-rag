# Deployment Target Discovery (read-only) — Compose Metadata Audit

Read-only: no Step 1 credential change, no recreate, restart, build, patch, DB access or container mutation.
Every value below was read from the **running container's own metadata** via `docker inspect` JSON — not
inferred from file names or host directory layout. No plaintext key or secret is reproduced; environment
variables are reported as **names only**.

## 1. Container identity

| field | value |
| --- | --- |
| exact container name | `/wenruo-rag-cpu` (name `wenruo-rag-cpu`) |
| container id | `87f4c3f7508e` |
| image reference | `my-wenruorag:latest` |
| **image id (running)** | **`c50436820cb9`** — as required |
| working dir in container | `/ragflow` |
| entrypoint / cmd | `./entrypoint.sh` · `--enable-adminserver --init-model-provider-tables` |
| restart policy | `unless-stopped` |
| healthcheck | **none configured** (relevant: an unhealthy start would not be detected automatically) |

## 2. Compose orchestration parameters (measured labels)

| label | value |
| --- | --- |
| `com.docker.compose.project` | `wenruo-rag` |
| `com.docker.compose.service` | `wenruo-rag-cpu` |
| `com.docker.compose.project.working_dir` | `C:\Projects\RAG\wenruo-rag\docker` |
| `com.docker.compose.project.config_files` | `C:\Projects\RAG\wenruo-rag\docker\docker-compose.yml` |
| `com.docker.compose.container-number` | `1` |
| `com.docker.compose.config-hash` | `7b28e0d87e7c1d891dc242a5a7fe24db1a97ba646e5e815f26b3b3955fe5f9b9` |
| `com.docker.compose.image` | `sha256:6ca36f9b58232b52355ad091b29f6b472399f0c3199b825b68859a1bcafce761` |
| `com.docker.compose.version` | `5.5.1` |

Two observations that matter for the recreate:

- **The compose file is inside the repository** (`../docker/docker-compose.yml`), so it is a tracked artifact and
  its drift is reviewable in Git.
- `com.docker.compose.image` = `sha256:6ca36f9b…` is **not** a candidate image id — it is the image the compose
  *config* resolves to. Since the running container's actual image is `c50436820cb9`, the compose file's own
  image reference does **not** describe the running deployment, which is exactly why the recreate must pin the
  target image explicitly rather than rely on the compose default.

## 3. Runtime configuration and dependencies

**Environment provenance:** 141 environment variables, all supplied through the compose service (no
`env_file` label is present). Names only are reported; secrets such as `MYSQL_PASSWORD`, `ELASTIC_PASSWORD`,
`MINIO_PASSWORD`, `REDIS_PASSWORD`, `GAUSSDB_PASSWORD` are deliberately not reproduced. Notable control
variables: `DOC_ENGINE`, `DB_TYPE`, `ES_HOST`/`ES_PORT`, `TEI_MODEL`, `RAGFLOW_IMAGE`, `COMPOSE_PROJECT_NAME`,
`SHOW_CABLE_ONLY`, `PYTHONPATH`.

**Mounts (3 bind mounts, all read-write):**

| type | host source | container destination |
| --- | --- | --- |
| bind | `C:\Projects\RAG\wenruo-rag\docker\ragflow-logs` | `/ragflow/logs` |
| bind | `C:\Projects\RAG\wenruo-rag\docker\service_conf.yaml.template` | `/ragflow/conf/service_conf.yaml.template` |
| bind | `C:\Projects\RAG\wenruo-rag\docker\entrypoint.sh` | `/ragflow/entrypoint.sh` |

Note for the record: the application code itself is **not** bind-mounted — only logs, the service-conf
template and the entrypoint script. This is consistent with the earlier finding that the container runs its own
code revision and that a restart cannot apply code changes; the image is the only code delivery path.

**Network and published ports:** network `wenruo-rag_ragflow`; published host ports `443`, `80`, `9380`,
`9381`, `9382`, `9383`, `9384` (each bound on IPv4 and IPv6). A recreate must preserve this mapping set, which
a compose-driven `up --force-recreate` does by construction and a hand-rolled `docker run` would not.

## 4. Target validation for the next window

| target | resolves to | verified |
| --- | --- | --- |
| **Candidate** | `my-wenruorag:p0b-891572a71` → `99d0ee210004` | yes |
| **Rollback** | `my-wenruorag:rollback-pre-p0-20260927` → `c50436820cb9` | yes |
| compose project / service | `wenruo-rag` / `wenruo-rag-cpu` | yes |
| compose file | `C:\Projects\RAG\wenruo-rag\docker\docker-compose.yml` | yes |

**`DEPLOYMENT_TARGET: RESOLVED`** — the recreate target can be expressed precisely, without a bare
`docker run`, as a compose invocation against the measured project file and service with the image pinned to
the candidate tag.

## 5. Uninterrupted-execution readiness for Steps 1-7

| requirement | status |
| --- | --- |
| recreate target fully identified (file, project, service, ports, mounts, restart policy) | **READY** |
| immutable candidate tag + rollback tag both verified by id | **READY** |
| credential rotation target identified (DB-backed model config for `gemini-embedding-001`) | **READY** as a target; the exact table/service access path still has to be opened at execution time |
| rollback path | **READY** — recreate from the rollback tag restores the exact prior state |
| gap to note | no healthcheck is configured, so post-recreate readiness must be asserted by the live negative control plus log/port checks rather than by container health status |

**Conclusion:** the remaining Steps 1-7 now have a fully specified, non-guessed deployment target and can be
executed in one continuous window. This round performed no mutation, and no Step 1 action was taken.
