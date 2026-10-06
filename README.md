<div align="center">
<img src="./web/src/assets/icon/brand-lockup.png" width="320" alt="Xindao | Wenruo RAG">
<h1>Wenruo RAG</h1>
<p>Retrieval and question answering over cable standards, technical specifications, BOMs and quality records for engineering procurement.</p>
<p><a href="./README.md">English</a> · <a href="./README_zh.md">简体中文</a> · <a href="./LICENSE">Apache-2.0</a></p>
</div>

## Choose the correct startup path

This is the customer delivery branch of Wenruo RAG, customized from RAGFlow and using the Python backend. The customer entry point is `delivery/manage.py`, with `delivery/compose.yaml`. The old `docker/docker-compose.yml` and `tools/scripts/start_deployment.py` are absent from this branch; do not reuse their startup commands.

| Scenario | Command from the source root | Browser entry |
| --- | --- | --- |
| Initialized customer or acceptance environment | `python delivery/manage.py start` | Port selected during initialization; default `http://localhost:9222/login` |
| First deployment on a new machine | Run init below, then start | Default 9222; select 19222 at initialization if occupied |
| Local frontend development | Start an available backend, configure its proxy, then `npm run dev -- --port 5173` | `http://localhost:5173` |

19222 is the port used by the existing isolated acceptance environment, not a universal default. Switching branches or cloning another directory does not migrate data or automatically isolate a database.

## Customer deployment: three separate deliverables

- **Source:** Git repository or source.zip, containing application code and deployment scripts.
- **Images:** images.tar and images.json, containing the application and pinned middleware images.
- **Business data:** business-data.zip, containing selected PDFs, parsed chunks, vectors, document metadata, assistant configuration and existing Wiki content. This is not a full private database dump.

Neither git clone nor docker load restores parsed documents. The business package is a separate delivery artifact and is not in Git. Send only the reviewed release directory, not its parent, private backups or delivery/private.

### Requirements

Install Docker with Compose (Docker Desktop/WSL2 recommended on Windows) and host Python 3.10+ for the standard-library deployment script. Importing prebuilt images does not require Node.js, uv or host backend dependencies. A practical baseline is 4 CPU cores, 16 GB RAM and 50 GB free disk; reserve additional space for image import and builds.

The customer stack exposes one Web port. MySQL, Elasticsearch, MinIO and Redis/Valkey are not published to the host. Offline deployment requires all pinned dependency images; building only the application image is insufficient.

### First deployment (Windows PowerShell)

This example uses C:\wenruo\release. Compare file hashes with SHA256SUMS.txt before proceeding. The extraction destinations must be new directories dedicated to this deployment.

```powershell
cd C:\wenruo\release
Get-FileHash source.zip,images.tar,business-data.zip -Algorithm SHA256
Expand-Archive -LiteralPath source.zip -DestinationPath C:\wenruo\source
Expand-Archive -LiteralPath business-data.zip -DestinationPath C:\wenruo\business-data
docker load -i images.tar
cd C:\wenruo\source
python delivery/manage.py init --project wenruo-delivery-customer01 --image wenruo:customer-release --revision 57cea96304b9fb840aa1f6291016354e74ab4f13 --package C:/wenruo/business-data
python delivery/manage.py start
```

The revision matches the accepted 2026-10-05 image. For later releases, use the matching image and revision from their delivery report. Choose a unique project name beginning with wenruo-delivery-. If 9222 is occupied, append --port 19222 to the first init command; do not stop another project's services.

Run init once. It verifies the package, pinned images, port and existing resources, then creates local configuration. start launches services, waits for backend readiness, restores business data and verifies the result. A container reporting Started is not completion. The default readiness timeout is 600 seconds; check initialization logs if the browser initially reports 502.

### Account, data and models

The only initial account is admin@wenruo.local, with superuser and workspace Owner permissions. Its password is generated on the customer machine at initialization and saved in delivery/private/admin-password.txt. Database passwords, session secrets and login RSA keys are also generated locally. Do not upload or copy delivery/private, or deliver a developer machine's password.

The accepted 2026-10-05 business package contains **3 knowledge bases, 18 PDFs, 797 chunks with document vectors, 18 document metadata records, 3 official assistants and 579 Wiki pages**. The 16,135 Wiki index records are not 16,135 pages. Refer to the matching DELIVERY-REPORT.txt for exact counts.

Private users, chat history, API tokens and model keys are excluded. The administrator must configure the customer's own model provider, endpoint and key. Preserved model names and bindings do not mean models are ready to call. Query embeddings must be compatible with the existing 3072-dimensional vector space; matching dimensions alone does not make a different model compatible.

Existing Wiki content is readable and its pipeline/templates are preserved. Future generation still requires administrator pipeline binding and model configuration; deployment does not overwrite formal document parser bindings. Successful startup without model credentials is not a passed question-answering test.

## Daily startup, logs and stopping

From the same initialized source directory:

```powershell
python delivery/manage.py start
```

Repeated start verifies the restore receipt without recreating accounts or regenerating passwords. To inspect or stop this project, define this PowerShell helper:

```powershell
$project=(Get-Content delivery/private/identity.json -Raw | ConvertFrom-Json).project
function dc {
  docker compose --project-name $project --env-file delivery/private/runtime.env -f delivery/compose.yaml --profile cpu @args
}
dc ps
dc logs --tail 100 wenruo-rag-cpu
# Stop services, preserving data:
dc stop
# Remove containers/network, preserving named volumes:
dc down
```

Resume with manage.py start. Do not troubleshoot by running down -v, deleting volumes or regenerating private configuration: this can destroy data or make credentials incompatible with the existing database. Do not manually edit runtime.env; the management script rejects configuration mismatches.

## Full image builds and upgrades

Restarting a container does not update code baked into its image. This branch uses the complete Dockerfile build. Avoid overwriting individual files in old containers or using latest as proof of a version.

Building from source requires Node.js 22, Docker and network access for build dependencies. Compile the frontend first, starting from the source root:

```powershell
cd web
npm ci
$env:NODE_OPTIONS='--max-old-space-size=4096'
$env:VITE_BUILD_SOURCEMAP='false'
$env:VITE_MINIFY='esbuild'
npm run build
cd ..
$revision=(git rev-parse HEAD).Trim()
docker build --build-arg WEB_DIST_MODE=prebuilt --build-arg SOURCE_COMMIT=$revision -t wenruo:customer-updated .
```

source.zip has no .git directory. For ZIP source, assign $revision directly to the release revision in the matching report. prebuilt includes the host's web/dist; rebuild it after frontend changes instead of shipping stale assets.

Upgrade an initialized environment:

```powershell
python delivery/manage.py set-image --image wenruo:customer-updated
python delivery/manage.py start
```

set-image explicitly changes the image/version while preserving credentials, resource identity and restore receipts. Use init for a first deployment. A new formal delivery needs renewed acceptance checks and matching image, source, business-data and checksum packages. docker save exports images, not runtime data volumes.

## Local source development

The customer Compose stack publishes only the Web port, not 9380/9381. Vite's Python proxy currently targets host 127.0.0.1:9380 (/api and /v1) and 9381 (admin API). Simply running npm dev against the customer stack will not provide a working backend connection.

Use an isolated development environment, configure the Vite proxy to reach its API, then run:

```powershell
cd web
npm ci
npm run dev -- --port 5173
```

For a Docker backend, use a dedicated development configuration to expose its API or point the proxy at its Web entry. Do not edit customer private/runtime.env. Keep development databases, queues and project names separate from customer resources.

Host Python debugging requires Python 3.13, uv, full dependencies and independently configured MySQL/ES/MinIO/Redis services. Configure host addresses, ports and credentials in conf/service_conf.yaml; container service names are not automatically host addresses. Stop the corresponding container worker to prevent two worker sets consuming the same queue, then run:

```powershell
# Install Python dependencies:
uv sync --python 3.13
# Terminal 1: API
$env:PYTHONPATH="."
$env:PYTHONUTF8="1"
uv run python api/wenruo_server.py
# Terminal 2: background worker (run in another terminal)
$env:PYTHONPATH="."
$env:PYTHONUTF8="1"
uv run python rag/svr/task_executor.py
```

Run the frontend in a third terminal with a matching proxy. Restart Python services as required after changes; full backend hot reload is not guaranteed. This is a development workflow, not customer installation.

## Troubleshooting and acceptance

| Symptom | First check |
| --- | --- |
| docker/docker-compose.yml not found | This branch uses delivery/manage.py and delivery/compose.yaml |
| Port already allocated | docker ps; select a free port on first init |
| 502 / ERR_EMPTY_RESPONSE | Project status and application logs; wait for API initialization and check database health |
| Configuration/password mismatch rejected | Preserve original private state and volumes; trace their origin instead of resetting credentials |
| Missing model configuration | Configure customer models/keys; check endpoint, quota and embedding compatibility |
| Wiki readable but generation unavailable | Model setup, pipeline binding, templates and preparation state |

Use a private browser session to verify that unauthenticated access leads to login. After login, check the sole administrator, three knowledge bases/assistants, PDFs, chunks, metadata and Wiki. Run retrieval and question-answering checks separately after model configuration. HTTP 200, Started containers or a visible UI do not replace restore verification.

## Documentation and contribution

- [Delivery workflow and data boundaries](./delivery/README.md)
- [Administrator and developer documentation](./docs/)
- [Document understanding and OCR](./deepdoc/README.md)
- [License](./LICENSE)

Keep changes focused and validate the relevant behavior. Never commit private configuration, passwords, model keys, business documents or customer data. Run README commands from the source root. These PowerShell examples use single-line commands for reliable copying.
