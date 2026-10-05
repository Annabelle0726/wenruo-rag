<div align="center">
<img src="./web/src/assets/icon/brand-lockup.png" width="320" alt="芯导软件 | 文若 RAG logo">
<h1>芯导软件 | 文若 RAG</h1>
<p><b>面向线缆工业的智能检索增强生成（RAG）系统</b></p>
<p>面向线缆标准、产品规格、BOM 与质检记录的智能检索与问答系统。</p>
</div>

<p align="center">
  <a href="./README.md"><img alt="README in English" src="https://img.shields.io/badge/English-DFE0E5"></a>
  <a href="./README_zh.md"><img alt="简体中文版自述文件" src="https://img.shields.io/badge/简体中文-DBEDFA"></a>
  <a href="./LICENSE"><img height="21" src="https://img.shields.io/badge/License-Apache--2.0-ffffff?labelColor=d4eaf7&color=2e6cc4" alt="license"></a>
</p>

<details open>
<summary><b>📕 目录</b></summary>

- 💡 [文若 RAG 是什么？](#-文若-rag-是什么)
- 🎮 [快速开始](#-快速开始)
- 📌 [近期更新](#-近期更新)
- 🌟 [主要功能](#-主要功能)
- 🔎 [系统架构](#-系统架构)
- 🎬 [自主托管](#-自主托管)
- 🔧 [系统配置](#-系统配置)
- 🔧 [源码编译 Docker 镜像](#-源码编译-docker-镜像)
- 🔨 [以源代码启动服务](#-以源代码启动服务)
- 📚 [技术文档](#-技术文档)
- 🙌 [贡献指南](#-贡献指南)

</details>

## 💡 文若 RAG 是什么？

文若 RAG 是面向线缆工业的检索增强生成（RAG）引擎：一套自主托管的智能检索与问答系统，把线缆领域的资料沉淀为**可溯源、有引用**的知识库。

它摄入线缆企业日常真正依赖的文档——国家标准与国际标准、产品规格书与数据表、BOM 物料清单、检测报告、质检记录、工艺文件、扫描图纸与网页——并基于这些内容回答问题，给出可追溯的引用，而不是无法验证的泛泛而谈。

平台保留了上游引擎中经过验证的核心链路（深度文档理解与 OCR、基于模板的文本切片、关键词/向量混合召回与融合重排序、Agent 工作流、OpenAI 兼容 API），并封装为线缆工业的工作流：按文件单独配置解析方式的数据集、切片级人工检查、自动关键词与问题提取、知识图谱，以及可调用内部系统的 Agent。

## 🎮 快速开始

文若 RAG 采用自主托管方式，请按目标选择路径：

- **Docker 部署或试用** —— 见 [自主托管](#-自主托管)。
- **本地源码开发（本仓库标准流程）** —— 见 [以源代码启动服务](#-以源代码启动服务)。

## 📌 近期更新

- 2026-06-15 支持飞书、Discord、Telegram、Line 等多种聊天渠道。
- 2026-04-24 支持 DeepSeek v4。
- 2025-12-26 支持 AI 代理的"记忆"功能。
- 2025-11-19 支持 Gemini 3 Pro。
- 2025-11-12 支持从 Confluence、S3、Notion、Discord、Google Drive 进行数据同步。
- 2025-10-23 支持 MinerU 和 Docling 作为文档解析方法。
- 2025-10-15 支持可编排的数据管道。
- 2025-08-08 支持 OpenAI 最新的 GPT-5 系列模型。
- 2025-08-01 支持 agentic workflow 和 MCP。
- 2025-05-23 Agent 新增 Python/JS 代码执行器组件。
- 2025-03-19 PDF 和 DOCX 中的图支持用多模态大模型解析并生成描述。

## 🌟 主要功能

### 🍭 **"Quality in, quality out"**

- 基于[深度文档理解](./deepdoc/README.md)，能够从各类复杂格式的非结构化数据中提取真知灼见。
- 真正在无限上下文（token）的场景下快速完成大海捞针测试。

### 🍱 **基于模板的文本切片**

- 不仅仅是智能，更重要的是可控可解释。
- 多种文本模板可供选择。

### 🌱 **有理有据、最大程度降低幻觉（hallucination）**

- 文本切片过程可视化，支持手动调整。
- 有理有据：答案提供关键引用的快照并支持追根溯源。

### 🍔 **兼容各类异构数据源**

- 支持丰富的文件类型，包括 Word 文档（含旧版 `.doc` 格式的 PDF 无缝转换预览）、PPT、Excel 表格、txt 文件、图片、PDF、影印件、复印件、结构化数据、网页等。

### 🛀 **全程无忧、自动化的 RAG 工作流**

- 全面优化的 RAG 工作流可以支持从个人应用乃至超大型企业的各类生态系统。
- 大语言模型 LLM 以及向量模型均支持配置。
- 基于多路召回、融合重排序。
- 提供易用的 API，可以轻松集成到各类企业系统。

## 🔎 系统架构

文若 RAG 以一个轻量栈的形式运行在统一的 nginx 入口之后：

- **Web UI** —— 构建进镜像的前端产物，由 nginx 在 `80` 端口提供服务。
- **API 服务**（`api/wenruo_server.py`）—— 应用 API 监听 `9380`，管理 API 监听 `9381`。
- **任务执行器**（`rag/svr/task_executor.py`）—— 负责文档解析、OCR、切片与索引的后台进程。
- **文档引擎** —— 默认 Elasticsearch，也可切换为 Infinity 或 OpenSearch，用于全文与向量存储。
- **元数据、对象与队列** —— MySQL 存元数据，MinIO 存原始文件，Redis 负责队列与锁。

管理员、开发者与参考文档见 [docs/](./docs)。

## 🎬 自主托管

### 📝 前提条件

- CPU >= 4 核
- RAM >= 16 GB
- Disk >= 50 GB
- Docker >= 24.0.0 且 Docker Compose >= v2.26.1
- Python >= 3.13（仅本地源码启动方式需要）
- [gVisor](https://gvisor.dev/docs/user_guide/install/): 仅当你打算使用代码执行器（沙箱）功能时才需要安装。

> [!TIP]
> 在 Windows 上，Docker Desktop 把整套服务跑在 WSL2 虚拟机里。请在构建镜像或运行文档引擎前给虚拟机留足内存，
> 例如在 `%USERPROFILE%\.wslconfig` 中配置 `memory=10GB`、`processors=8`、`swap=8GB`，然后执行 `wsl --shutdown`
> 使其生效。虚拟内存过小会让容器构建陷在 swap 抖动中缓慢爬行，而不是快速失败。

### 🚀 启动服务器

1. Linux 主机需确保 `vm.max_map_count` 不小于 262144（Windows/macOS 的 Docker Desktop 已在其虚拟机内设置好）：

   > 如需确认 `vm.max_map_count` 的大小：
   >
   > ```bash
   > sysctl vm.max_map_count
   > ```
   >
   > 如果 `vm.max_map_count` 的值小于 262144，可以进行重置：
   >
   > ```bash
   > # 这里我们设为 262144:
   > sudo sysctl -w vm.max_map_count=262144
   > ```
   >
   > 你的改动会在下次系统重启时被重置。如果希望做永久改动，还需要在 **/etc/sysctl.conf** 文件里把 `vm.max_map_count` 的值再相应更新一遍：
   >
   > ```bash
   > vm.max_map_count=262144
   > ```

2. 克隆本仓库：

   ```bash
   git clone <YOUR_REPOSITORY_URL> wenruo-rag
   cd wenruo-rag
   ```

3. 构建并启动应用容器：

   ```bash
   cd docker

   # 构建镜像（更快的前端预构建方式见「源码编译 Docker 镜像」）：
   docker compose build wenruo-rag-cpu

   # 启动应用容器：
   docker compose up -d wenruo-rag-cpu
   ```

   > 应用容器名为 `wenruo-rag-cpu`，使用的镜像由 [.env](./docker/.env) 中的 `RAGFLOW_IMAGE` 指定，默认为
   > `my-wenruorag:latest`。它依赖的容器（`wenruo-rag-mysql-1`、`wenruo-rag-es01-1`、`wenruo-rag-minio-1`、
   > `wenruo-rag-redis-1`）必须先处于运行状态；冷启动整栈请改用：
   >
   > ```bash
   > docker compose up -d
   > ```

4. 服务器启动成功后确认服务器状态：

   ```bash
   docker logs -f wenruo-rag-cpu
   ```

   _出现以下输出说明服务器启动成功：_

   ```bash
                         Wenruo RAG Engine                   

   Wenruo RAG version: v0.27.1-<git-describe>
   project base: /wenruo-rag
   Wenruo RAG server is ready after 131.1s initialization.
   Running on http://0.0.0.0:9380 (CTRL + C to quit)
   ```

   > 版本号后缀是你所构建代码的 `git describe` 结果。首次启动耗时更久，因为在 API 开始监听之前需要完成数据表、
   > 索引与超级用户的初始化。
   >
   > 如果你在没有看到上述提示信息之前就尝试登录，浏览器可能会提示 `network abnormal` 或 `网络异常`，因为此时
   > API 尚未完成初始化。
   >

5. 在浏览器中输入服务器对应的 IP 地址并登录：

   > 默认配置下只需输入 `http://IP_OF_YOUR_MACHINE` 即可：未改动过配置则无需输入端口（默认 HTTP 服务端口 `80`）。
   >

6. 在 [service_conf.yaml.template](./docker/service_conf.yaml.template) 文件的 `user_default_llm` 栏配置 LLM factory，并在 `API_KEY` 栏填写与你所选大模型相对应的 API key。

   > 文若 RAG 发布的是 slim 版本，不包含 embedding 模型，因此在创建知识库之前还需配置 embedding 模型服务。
   > 相关配置说明见 [docs/](./docs)。
   >

   _好戏开始，接着奏乐接着舞！_

## 🔧 系统配置

系统配置涉及以下三份文件：

- [.env](./docker/.env)：存放一些基本的系统环境变量，比如 `COMPOSE_PROJECT_NAME`、`RAGFLOW_IMAGE`、`SVR_HTTP_PORT`、`MYSQL_PASSWORD`、`MINIO_PASSWORD` 等。
- [service_conf.yaml.template](./docker/service_conf.yaml.template)：配置各类后台服务。
- [docker-compose.yml](./docker/docker-compose.yml): 系统依赖该文件完成启动。

请务必确保 [.env](./docker/.env) 文件中的变量设置与 [service_conf.yaml.template](./docker/service_conf.yaml.template) 文件中的配置保持一致！

如果不能访问镜像站点 hub.docker.com 或者模型站点 huggingface.co，请按照 [.env](./docker/.env) 注释修改 `RAGFLOW_IMAGE` 和 `HF_ENDPOINT`。

> [./docker/README](./docker/README.md) 解释了 [service_conf.yaml.template](./docker/service_conf.yaml.template) 用到的环境变量设置和服务配置。

如需更新默认的 HTTP 服务端口(80), 可以在 [docker-compose.yml](./docker/docker-compose.yml) 文件中将配置 `80:80` 改为 `<YOUR_SERVING_PORT>:80`。

> 所有系统配置都需要通过重启应用容器生效：
>
> ```bash
> cd docker
> docker compose up -d wenruo-rag-cpu
> ```

### 把文档引擎从 Elasticsearch 切换成为 Infinity

文若 RAG 默认使用 Elasticsearch 存储文本和向量数据。如果要切换为 Infinity，可以按照下面步骤进行：

1. 停止所有容器运行:

   ```bash
   docker compose -f docker/docker-compose.yml down -v
   ```
   Note: `-v` 将会删除 docker 容器的 volumes，已有的数据会被清空。

2. 设置 **docker/.env** 目录中的 `DOC_ENGINE` 为 `infinity`.

3. 启动容器:

   ```bash
   docker compose -f docker/docker-compose.yml up -d
   ```

> [!WARNING]
> Infinity 目前并未正式支持在 Linux/arm64 架构下的机器上运行。

## 🔧 源码编译 Docker 镜像

应用镜像由本仓库根目录的 [Dockerfile](./Dockerfile) 构建，并以 [docker/.env](./docker/.env) 中的 `RAGFLOW_IMAGE`
（默认 `my-wenruorag:latest`）打标签。

**最快的构建方式 —— 前端预构建。** 先在宿主机上生成 `web/dist`，再让镜像直接使用它，避免在容器内跑 Vite 构建：

```bash
# 1. 在宿主机上构建前端（容器构建会从构建上下文中读取 web/dist）：
cd web
npm run build
cd ..

# 2. 使用预构建前端构建镜像：
cd docker
docker compose build --build-arg WEB_DIST_MODE=prebuilt wenruo-rag-cpu
```

> 在 Docker 虚拟机内存较小的机器上建议走这条路：本仓库在容器内执行 Vite 构建时非常吃内存。
> `WEB_BUILD_HEAP_MB`（默认 `4096`）用于限制容器内构建的 V8 堆上限，必须低于 Docker 虚拟机能够用真实内存支撑的量。

**容器内完整构建**（前端在镜像内编译）：

```bash
cd docker
docker compose build wenruo-rag-cpu
```

> 两种方式都需要一个内含模型与 native 依赖库的依赖镜像；它构建自本仓库，任何时候都可以在无外网的情况下重新生成：
>
> ```bash
> cd wenruo_deps
> docker build -f Dockerfile -t infiniflow/wenruo_deps:latest .
> ```

## 🔨 以源代码启动服务

本仓库在 Windows + PowerShell 环境下开发和运行，下述流程为本仓库标准的本地启动方式，请保持 Docker
依赖服务在后台常驻运行。

> [!TIP]
> **旧版 Office 预览 (.doc)：**
> Docker 镜像中已预装无界面版 LibreOffice，用于将旧版 `.doc` 文档转换为 PDF 进行在线预览。
> 如果你在本地以源码方式启动开发，且需要测试 `.doc` 文件的本地预览功能，请在宿主机安装 LibreOffice 并配置 `SOFFICE_BIN` 环境变量指向 `soffice` 可执行文件。

> [!IMPORTANT]
> 首次克隆仓库后，请在仓库根目录执行一次 `git config --local --unset core.hooksPath`、`uv tool install lefthook` 和 `lefthook install`，以启用本地 Git hooks。

### 首次环境准备

1. 安装 `uv`。如已经安装，可跳过本步骤：

   ```powershell
   pip install uv
   ```

2. 安装 Python 依赖并下载 native 依赖库：

   ```powershell
   uv sync --python 3.13
   uv run python wenruo_deps/download_deps.py
   ```

3. 安装前端依赖：

   ```powershell
   cd web
   npm install
   ```

### 启动服务

1. 确认 Docker 依赖容器已启动：执行 `docker ps` 应能看到 `wenruo-rag-mysql-1`、`wenruo-rag-es01-1`、
   `wenruo-rag-redis-1` 和 `wenruo-rag-minio-1`。如果尚未启动，请先执行以下命令（下次可直接跳过本步骤）：

   ```powershell
   docker compose -f docker/docker-compose-base.yml up -d
   ```

2. 终端 1 —— Task Executor 任务后台，负责文档解析与索引：

   ```powershell
   $env:PYTHONPATH="."
   $env:HF_ENDPOINT="https://hf-mirror.com"
   $env:PYTHONUTF8="1"
   uv run python rag/svr/task_executor.py
   ```

3. 终端 2 —— Web API 服务，监听 9380 端口：

   ```powershell
   $env:PYTHONPATH="."
   $env:HF_ENDPOINT="https://hf-mirror.com"
   $env:PYTHONUTF8="1"
   uv run python api/ragflow_server.py
   ```

4. 终端 3 —— 前端 UI，访问地址 <http://localhost:9222>，并代理后端 API：

   ```powershell
   cd web
   npm run dev
   ```
   ![前端 UI 界面](./probe-register-light.png)

   | 前端（开发） | API 代理目标 | 用途 |
   |--------------|--------------|------|
   | `http://localhost:9222` | `http://127.0.0.1:9380` | `/api`、`/v1` —— 由 `api/wenruo_server.py` 提供的应用 API |
   | `http://localhost:9222` | `http://127.0.0.1:9381` | `/api/v1/admin` —— 同一进程提供的管理 API |

5. 浏览器访问 <http://localhost:9222> 即可使用 文若 RAG：

   首次请求前请等待控制台出现 [自主托管](#-自主托管) 中所示的启动横幅（或 `logs/ragflow_server.log` 中的等价日志）：
   Web API 只有在数据库与文档引擎就绪后才会监听 9380 端口。

   `$env:PYTHONUTF8="1"` 用于避免中文日志触发控制台编码报错（乱码），
   `$env:HF_ENDPOINT="https://hf-mirror.com"` 用于把模型下载指向 HuggingFace 镜像站。

### 停止服务

在每个终端按 `Ctrl+C` 即可。Docker 依赖服务会继续运行，如需一并停止请执行
`docker compose -f docker/docker-compose-base.yml down`。

在 Linux 或 macOS 上，把 `$env:X="..."` 换成 `export X=...` 即可；这两个平台上
`bash docker/launch_backend_service.sh` 可以在一个终端内同时启动两个后端进程。

## 📚 技术文档

- [docs/](./docs) —— 本仓库自带的管理员、开发者、使用指南与参考文档。
- [docker/README.md](./docker/README.md) —— `service_conf.yaml.template` 使用的环境变量与服务配置说明。
- [deepdoc/README.md](./deepdoc/README.md) —— 深度文档理解与 OCR 链路。
- [internal/development.md](./internal/development.md) —— native 与 Go 构建说明。
- [AGENTS.md](./AGENTS.md) —— 本仓库的改动约定与验证要求。

## 🙌 贡献指南

本仓库是私有二次开发分支。请保持改动小而聚焦，用范围最小的相关命令进行验证（见 [AGENTS.md](./AGENTS.md)），
并优先删除被取代的代码，而不是保留兼容层。前端相关改动请同时遵循 [web/CLAUDE.md](./web/CLAUDE.md)。
