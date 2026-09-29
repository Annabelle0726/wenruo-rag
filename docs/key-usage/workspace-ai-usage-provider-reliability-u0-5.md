# Workspace AI Usage & Provider Reliability — U0.5 Readiness Closure

验证日期：本轮 checkout `138a1a79a67864e1361f3e2cbb70315b97770ffb`（branch `feat/user-role`）。
范围：Readiness Closure ONLY。**本轮没有实现 U1 产品代码、UI、API、DB migration，也没有修复任何 U0 已证明缺陷。**

前置阅读：`docs/key-usage/workspace-ai-usage-provider-reliability-u0.md`、`AGENTS.md`、`docs/key-usage/ROADMAP.md`。

## 0. 证据限制与红线遵守

**本轮没有连接生产 SQL/Redis、没有读取线上配置行或日志、没有调用任何 provider、没有读取任何 API key 明文。**
所有结论来自 checkout 源码、ORM 声明、既有测试源码与本轮实际执行的测试输出。

| 红线                                                   | 本轮状态 | 证据                                                                                     |
|--------------------------------------------------------|----------|------------------------------------------------------------------------------------------|
| API_KEY_PLAINTEXT_READS_DURING_U0_5 = 0                | 0        | 本轮 SELECT 只发生在 SQLite 测试库与源码阅读；未加载任何 credential ORM 行，未投影 secret 列 |
| NO DB mutation                                         | 遵守     | 三个测试文件使用 `temporary_path` SQLite（`db.bind_ctx` + `create_tables`），未连接生产库    |
| NO Redis mutation                                      | 遵守     | **未设置 `TEST_REDIS_URL`**，2 个 Redis-gated 用例按设计 skip（见 §2）                        |
| NO Production mutation                                 | 遵守     | 未连接生产环境；未部署、未 retag、未改配置                                                   |
| NO U0 bug fix                                          | 遵守     | §6 Backlog 全部保持未修复；工作树中既有的 `rag/*` 修改**不是本轮的**，未被触碰                 |
| Identity isolation：user_id ≠ tenant_id ≠ workspace_id   | 冻结     | §5 明确三个身份域的解析与校验规则；`tenant_id=current_user.id` 类写法在 U1 中禁止             |

生产形状核对（schema/index/volume）**本轮未执行且未获授权**，见 §7 与 §10 的 `PRODUCTION_SHAPE_VALIDATION: NOT_AUTHORISED`。

## 1. Metric Scope Freeze — U1 V1 只映射到既有权威事实

来源事实（全部为已有表，U1 V1 **不新增任何列、不做 migration**）：

- [WorkspaceUsage](C:/Projects/RAG/wenruo-rag/api/db/db_models.py:1723) `workspace_usage`：`id=SHA256(tenant:user:period)`、`tenant_id`、`user_id`、`period`、`calls`、`prompt_tokens`、`completion_tokens`、`tokens`、`cost_micros`。
- [WorkspaceUsageLedger](C:/Projects/RAG/wenruo-rag/api/db/db_models.py:1747) `workspace_usage_ledger`：一次 attempt 一行，`id`=reservation UUID、`tenant_id`、`user_id`、`call_kind`、`model_name`、`period_day`、`period_month`、`timezone`、`reserved_tokens`、`reserved_cost_micros`、`prompt_tokens`、`completion_tokens`、`tokens`、`cost_micros`、`status`、`settled_at`。
- [WorkspaceBudget](C:/Projects/RAG/wenruo-rag/api/db/db_models.py:1699) `workspace_budget`：七个 limit + `timezone`（规则，不是用量）。
- [UserTenant](C:/Projects/RAG/wenruo-rag/api/db/db_models.py) membership/role：`role`、`status`。

### 1.1 允许的 V1 metrics（逐项映射）

| U1 V1 metric                             | 权威来源                                        | 推导规则                                                                                       | 标签/边界（必须照此呈现）                                                                 |
|------------------------------------------|-------------------------------------------------|------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| `attempted_calls` (workspace/member/day/month) | `workspace_usage.calls`（当期行）；对账源 `COUNT(ledger)` | 受计量 dispatch attempt 数；day 行与 month 行**分开**，不得相加                                  | 不是“用户请求数”；预算拒绝前无 ledger 行，故拒绝不计入分母                                  |
| `settled_tokens`                         | `SUM(ledger.tokens) WHERE status='settled'`      | 已结算 token 总数                                                                              | 标签为“settled tokens”；embedding wrapper 可能自行估算，**不等于**全路径 provider-reported      |
| `outstanding_reserved_tokens`            | `SUM(ledger.reserved_tokens) WHERE status IN ('reserved','unsettled')` | 仍在飞行 + 已结束但未报告 usage 的占用                                        | 不是“正在运行”；含进程崩溃留下的孤立预留与按设计立即关闭的额外轮次                            |
| `estimated_cost_micros`                  | `SUM(ledger.cost_micros) WHERE status='settled' AND cost_micros>0` | 整数 micro-USD                                                    | 展示术语只能是 **Estimated model cost**（§4）                                                |
| `outstanding_reserved_cost_micros`       | `SUM(ledger.reserved_cost_micros) WHERE status IN ('reserved','unsettled') AND reserved_cost_micros>0` | 占用上限 | `reserved_cost_micros>0` 是“该次 dispatch 时有定价”的**唯一**历史证据                        |
| `cost_coverage`                          | 由上面两行的行级派生                             | `complete` / `partial` / `unavailable`（§4.3）                                                  | 缺价一律 unknown，**不得渲染为已知 $0**                                                      |
| `member_breakdown`                       | `GROUP BY ledger.user_id`（+ `workspace_usage.user_id`） | 按历史 `user_id` 精确聚合，成员被移除后历史保留                                        | 显示名只允许 LEFT JOIN 维表；禁止 INNER JOIN（会丢历史）                                     |
| `daily_series` / `monthly_series`        | `GROUP BY ledger.period_day` / `period_month`（+ 该行 `ledger.timezone`） | 使用**行上保存的** period，不做时区重算                                | day 与 month 永不求和；历史同名日期保留其原 timezone 解释                                     |
| `workspace_total`                        | `GROUP BY ledger.tenant_id`                      | 同一 predicate 的 workspace 聚合                                                               | 必须满足 §5 的对账门                                                                        |
| `recorded_model_breakdown`               | `GROUP BY ledger.model_name`（含 `''` 桶）        | 裸模型名分组；`''` 归入显式 `unrecorded` 桶（`charge_provider_call` 产生的额外轮次无模型归因）    | 标签为“recorded model name”，**不等于**具体 provider 配置模型                                |
| `quota_status`                           | `workspace_budget` 七个 limit + `usage_snapshot` | limit 0 = “未启用该维度”，不是“剩余 0”                                                          | 必须同时显示 OWNER/ADMIN 豁免事实；不得声称 workspace 级硬总额帽                              |

`quota_status` 的读取路径冻结：使用 [`usage_snapshot`](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:159) + `WorkspaceBudget.get_or_none`，
**不得复用** [`configure_budget`](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:117)：后者为加锁执行
`Tenant.update(name=Tenant.name)`（[:120](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:120)），
是写操作，U1 的只读端点不得引入。

### 1.2 明确排除（V1 绝不出现）

- **historical provider attribution**：ledger/usage 无任何 provider/instance 列，当前配置反查裸名有歧义且随改名/删除漂移。
- **API-key/instance attribution**：无 instance ID、无 key version；同一物理 key 可手工填入多个 instance，schema 无唯一约束。
- **workload attribution**：`call_kind` 只是 `model_type`（chat/embedding…），额外轮次为空；无 task/request/parent-dispatch 关联。
- **reconstructed historical data**：不做任何 backfill、不做模型名反推、不按时间窗口猜。
- **provider-reported vs 本地估算的 provenance 区分**：ledger 未保存来源标记，V1 不得声称可区分。
- **价格版本/可复算依据**：ledger 保存数值结果但未保存当时单价，V1 不得声称可完整复算。
- **provider 账户剩余额度**：无权威 adapter，不得由本地用量推算。
- **OCR bypass 的覆盖率主张**：远程 OCR 绕过装饰器，V1 不得声称成本覆盖完整。

**Unknown stays unknown 冻结规则**：任何不在 §1.1 映射表中的维度，U1 返回显式 unknown（`null` / `"unknown"`），
**不允许**以 `0`、`""` 或空数组代替。默认零值列（`tokens`、`cost_micros`）在本表中只作为“未结算”的字段语义出现，
读侧必须按 §3 用 `reserved_*` 取有效占用，否则会系统性低报。

## 2. Test Environment Restoration & Execution

### 2.1 环境认定（repository-supported）

仓库自带的 uv 管理 venv 即为受支持测试环境，而非临时拼装的宿主依赖：

- `.venv/pyvenv.cfg`：`uv = 0.12.5`，`home = ...uv\python\cpython-3.13-windows-x86_64-none`，`include-system-site-packages = false`。
- 依赖由 `pyproject.toml` + `uv.lock` 冻结；仓库文档规定的手工等价命令为
  `uv sync --python 3.13 --frozen`（[launch_ragflow_from_source.md:51](C:/Projects/RAG/wenruo-rag/docs/develop/launch_ragflow_from_source.md:51)）
  与 `uv sync --python 3.13 --group test --frozen`（同文件:58），测试组另见 [test/README.md:13](C:/Projects/RAG/wenruo-rag/test/README.md:13)。
- 关键包已在 `.venv` 内解析完成：`pytest 9.1.1`、`pytest-asyncio 1.4.0`、`peewee 3.19.0`、`valkey 6.0.2`、`redis 8.1.0`。
  **未执行任何 `pip install` / `uv pip install`，未改动应用依赖。**
- 证据修正：`AGENTS.md` Pending 段曾记录“repo `.venv` 未带 `pytest-asyncio`”。本轮实测该环境已解析 `pytest-asyncio 1.4.0`，
  `asyncio_mode = "auto"` / `asyncio_default_fixture_loop_scope`（[pyproject.toml:260](C:/Projects/RAG/wenruo-rag/pyproject.toml:260)）被正常接受，
  collection 无 INTERNALERROR。该历史记录对当前 checkout 已不适用。

### 2.2 精确执行命令与结果

```powershell
# workdir: C:\Projects\RAG\wenruo-rag
C:\Projects\RAG\wenruo-rag\.venv\Scripts\python.exe -m pytest `
  test/unit_test/api/db/services/test_workspace_budget_settlement.py `
  test/unit_test/api/db/services/test_workspace_security.py `
  test/unit_test/api/db/services/test_detached_task_initiator.py `
  -p no:cacheprovider -q --no-header -rs
```

| 文件                                                      | collected | passed | failed | skipped | 用时   |
|-----------------------------------------------------------|-----------|--------|--------|---------|--------|
| `test_workspace_budget_settlement.py`                     | 30        | 30     | 0      | 0       | 19.3s  |
| `test_workspace_security.py`                              | 15        | 13     | 0      | 2       | 15.5s  |
| `test_detached_task_initiator.py`                         | 5         | 5      | 0      | 0       | 16.4s  |
| **合计（单次合并运行）**                                   | **50**    | **48** | **0**  | **2**   | 31.4s  |

真实输出尾行：`48 passed, 2 skipped in 31.44s`。**没有任何 collection error；本轮 U0 记录的
`0 collected / 3 collection errors`（缺 `peewee`、`valkey`）已不成立。**

### 2.3 skip 的准确原因（不掩饰）

```
SKIPPED [1] test_workspace_security.py:128: TEST_REDIS_URL must identify an isolated test Redis
SKIPPED [1] test_workspace_security.py:146: TEST_REDIS_URL must identify an isolated test Redis
```

`redis_budget` fixture（[:108](C:/Projects/RAG/wenruo-rag/test/unit_test/api/db/services/test_workspace_security.py:108)）要求
环境变量 `TEST_REDIS_URL` 指向一个**隔离的**测试 Redis。本轮红线禁止任何 Redis mutation，而这 2 个用例会
`ZADD`/`PEXPIRE` 真实键（尽管带 `security-test:<uuid>:` 前缀并在 teardown 清理），因此**未设置该变量，故意让其 skip**，
而不是指向共享实例。后果：滚动分钟门（rolling-minute Lua）与其并发语义在**本轮未被实机验证**，
只能引用既有 `AdmittingRedis` / SQLite 层测试与 `AGENTS.md` 的历史线上记录。
U1 V1 的 read model 不读取 Redis，因此该 gap 不阻塞 U1；但**不应**被读成“滚动分钟已在本轮验收”。

### 2.4 既有测试对 U0 缺口的覆盖（与 §3/§4 的关系）

三个文件**没有**覆盖：OCR 绕过预算、无 token split 时的零成本结算、provider/instance 历史归因、
provider-reported 与本地估算的 provenance 区分。其中“无 split → cost=0”的机制在源码中被本轮再次确认（§4.2），
而三个测试文件均无用例断言该形状——这是 U1 呈现成本时必须自行带上的诚实性负担。

## 3. Accounting & Terminology Freeze

### 3.1 reserved / settled / unsettled 决策表（冻结）

来源：`workspace_usage_ledger`；写入点为 [`reserve_call`:187](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:187)、
[`settle_dispatch`:264](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:264)、
[`release_dispatch`:317](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:317)，
以及 dispatch 关闭点 [`_close_dispatch`:222](C:/Projects/RAG/wenruo-rag/common/model_budget.py:222)。

| status      | 由谁写入 / 何时                                   | 语义                                                                            | 读侧有效 tokens                        | 读侧有效 cost                                    | 计为一次 call | 可迁移                                              | 是否证明 provider 结局 |
|-------------|--------------------------------------------------|---------------------------------------------------------------------------------|----------------------------------------|--------------------------------------------------|---------------|-----------------------------------------------------|------------------------|
| `reserved`  | `reserve_call`，dispatch **之前**                  | 上限被占用；可能仍在飞行，也可能是进程崩溃留下的**孤立**预留                        | `reserved_tokens`                      | `reserved_cost_micros`                           | 是            | → `settled`，或 → `unsettled`                         | **否**                 |
| `settled`   | `settle_dispatch`                                 | provider 报告了 usage；预留下调至实际，超出则向上补记                              | `tokens`（split 不可信时 `prompt/completion` 为 0） | `cost_micros`；`cost_micros=0` 且 `tokens>0` ⇒ 成本**未成立** | 是            | 终态（重复 settle = `duplicate` no-op）                | 证明“报告了用量”，**不证明成功或失败** |
| `unsettled` | `release_dispatch`                                | 结束但未报告 usage（超时/取消/流中断），或该调用点**从不报告**；预留全额保留、不再可结算 | `reserved_tokens`                      | `reserved_cost_micros`                           | 是            | 终态（之后 settle 亦为 `duplicate`）                   | **UNKNOWN**            |

冻结的补充规则（U1 必须照此实现，不得自行解释）：

1. **读模型必须用有效值公式**：`effective_tokens = CASE WHEN status='settled' THEN tokens ELSE reserved_tokens END`。
   只读 `tokens` 会把 reserved/unsettled 行当作 `0`，系统性低报（U0 §3 的结论，本轮源码再确认）。
2. **`workspace_usage.tokens` / `cost_micros` 是“预算占用”，不是已结算实际值**。它们在 reserve 时加上限、在 settle 时减去未使用部分，
   因此始终 ≥ 真实花费且包含在飞部分。U1 呈现“已结算”时必须来自 ledger，不得直接把它当 settled 数字。
3. **`unsettled` 有两个不同成因**，U1 V1 不得只描述为“用量尚未知”：
   (a) dispatch 未报告 usage（超时/取消/流中断，或 `describe`([:268](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:268)) /
   `describe_with_prompt`([:282](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:282)) /
   `transcription`([:298](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:298)) /
   `stream_transcription`([:312](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:312)) /
   `tts`([:376](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:376)) 这些调用点读到了 `used_tokens` 却**从不**调用
   `record_dispatch_usage` —— 全文件仅 4 个上报点：[:128](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:128)（chat）、
   [:218](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:218)/[:247](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:247)/[:264](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:264)（embedding/rerank））；
   (b) **按设计**立即关闭的额外轮次：[`charge_provider_call`:148](C:/Projects/RAG/wenruo-rag/common/model_budget.py:148) 为 LiteLLM retry / tool round
   以 `reserve_call(tenant, actor)` 建行后立刻 `release_dispatch`，其 token 已包含在外层 dispatch 的最终用量里。
   因此 `unsettled` 行数 ≠ “有未知用量的调用数”。V1 至少要把 `call_kind='' AND model_name=''` 的行标为 `unrecorded` 桶。
4. **`status` 是会计状态，永远不是 provider healthy/unhealthy**。不得从 settled/unsettled 反推上游可用性。
5. **一天一行、一次 attempt 一行**：同一业务请求重试会创建新的 UUID reservation，不是跨请求 exactly-once；`calls` 计的是 attempt。
6. **结算幂等只对同一 reservation**：`settle_dispatch` 对非 `reserved` 行返回 `{"status": ..., "duplicate": True}` 且不写计数器。
7. **counter 行被删时 settle 跳过该行**（[`settle_dispatch`:294](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:294)），
   既有测试 `test_settlement_of_a_deleted_counter_is_survivable` 明确接受此行为 ⇒ **counter 与 ledger 可以分叉**。
   ledger 是逐 attempt 的事实与对账源，counter 是 enforcement 读取源；**没有查到自动对账/重建任务**。
   U1 必须**暴露**该分叉（对账门，§5），不得掩盖。
8. **时间列语义**：日/月聚合只用 `period_day` / `period_month`（保留行上 `timezone`）；`settled_at` 是结算墙钟时间，
   不得用于日/月边界。修改 workspace timezone **不重算历史**。
9. **已移除成员的历史保留**：行仍在，按 `user_id` 继续参与 workspace 聚合。
10. **失败/取消不退 calls**：provider 失败但已预留的 attempt 不退；`token/cost` 维度 limit=0 表示不启用该维度限制。

### 3.2 术语冻结

**唯一批准的展示术语：`Estimated model cost`**（中文界面可用“预估模型费用”，英文术语保持 `Estimated model cost`）。
派生标签允许：`settled estimated model cost`、`outstanding reserved estimated-cost occupancy`。
单位：存储 `micro_usd`，展示为 USD；必须与 `cost_unit=micro_usd` 的既有契约一致。

**禁止出现的术语**：`Actual provider bill`、`Invoice`、`Actual charge`、`Actual API cost`、
`Total infrastructure cost`、`Local compute share`、`Provider quota remaining`（V1 无权威 adapter）、
以及任何无限定语的 `Cost` 被读成账单含义。

## 4. Cost Honesty Freeze（R5）

### 4.1 定价来源与已知精度缺口（源码再确认）

- 定价来自 `TenantModel.extra` 的 `price_input_per_million` / `price_output_per_million`，经 `_model_pricing` 放入 `model_config.pricing`，
  由 [`pricing_of`:98](C:/Projects/RAG/wenruo-rag/common/model_budget.py:98) 读取；USD/million 在数值上等于 micro-USD/token。
- 计算：`round(prompt*price_in + completion*price_out)`（[`estimate_cost_micros`:113](C:/Projects/RAG/wenruo-rag/common/model_budget.py:113)）。
  无汇率、无阶梯价、无缓存折扣、无税费、无 provider 账单对账。
- **已证明的零成本路径**：[`_report_usage`:108](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:108) 在
  `prompt + completion != total_tokens` 时把 split 置零（[:122-124](C:/Projects/RAG/wenruo-rag/api/db/services/llm_service.py:122)），
  随后 [`_close_dispatch`:232](C:/Projects/RAG/wenruo-rag/common/model_budget.py:232) 用这两个零值乘单价 ⇒ **非零 tokens 被结算为 `cost_micros=0`**。
  三个既有测试文件均未断言该形状。

### 4.2 行级覆盖判定（V1 冻结规则，全部可由既有列推出）

| 条件                                | 判定           | 渲染                                        |
|-------------------------------------|----------------|---------------------------------------------|
| `status='settled'` 且 `cost_micros > 0` | `established`  | 显示金额（Estimated model cost）             |
| `status='settled'` 且 `tokens > 0` 且 `cost_micros = 0` | `unavailable` | **`—` / `Partial` / “Not available”，绝不 `$0.00`** |
| `tokens = 0` 且 `cost_micros = 0`      | `zero_usage`   | 不产生金额；不计入分母                        |
| `status IN ('reserved','unsettled')` 且 `reserved_cost_micros > 0` | `established`（占用） | 显示 outstanding reserved 占用    |
| `status IN ('reserved','unsettled')` 且 `reserved_cost_micros = 0` | `unavailable`（占用） | unknown，不写成 0                  |

### 4.3 workspace / member 级 `cost_coverage`

- `complete`：作用域内所有计入 attempt 均为 `established` 或 `zero_usage`，**且至少存在一条计入 attempt**。
- `partial`：至少一条 `established` 且至少一条 `unavailable`。
- `unavailable`：存在计入 attempt 但**无一条** `established`；或作用域内没有任何计入 attempt（**不得**声称 complete）。
- 私有/自建端点：显示 `External API estimated cost: N/A`，**绝不 `$0.00`**（无 provider 账单对账即无“实际为 0”的证据）。

### 4.4 U1 payload 必须自带的诚实性说明

由于 ledger **没有** `priced` 标志、**没有** 单价版本，`cost_micros=0` 无法区分“无定价”“split 被丢弃”“本地估算”
“Builtin/私有端点”。因此 U1 的每个成本视图必须随附：覆盖度（`complete`/`partial`/`unavailable`）、
“Estimated model cost 由模型配置的每百万 token 单价推算，非 provider 账单”这一句，以及零 split 缺口的说明。
不得出现 `Bill` / `Invoice` / `Actual charge` 字样。

## 5. Authorization Matrix Freeze（R4）

### 5.1 三个身份域（identity isolation，强制）

本仓库中 **workspace 就是 tenant**（`tenant_id` 即 workspace 键，没有独立 `workspace_id` 列）。因此必须冻结的是
“值不被跨域替换”，而不是名称：

| 域                                    | 来源                                                              | 用途                                   | 禁止                                                    |
|---------------------------------------|-------------------------------------------------------------------|----------------------------------------|---------------------------------------------------------|
| `authenticated_user_id`（member 域）   | `login_required` 的 `current_user.id`；（detached 路径）`workspace_budget_service.enter_detached_job` 安装的 `execution_user` | `ledger.user_id` 过滤、角色判定         | 不得当作 workspace/tenant；不得用 tracing `user_id` 代替 |
| `workspace_id`（tenant 域）            | 显式请求的 workspace id，经 `UserService.resolve_config_tenant_id(user_id, owner_tenant_id)` 校验（[:266](C:/Projects/RAG/wenruo-rag/api/db/services/user_service.py:266)） | `ledger.tenant_id` 过滤                | 不得由 `current_user.id` 推断；不得在未校验成员身份时使用  |
| `resource_workspace_id`（资源域）      | 资源自身的拥有 workspace                                          | 决定读取哪个 workspace                 | 资源域与调用者个人 workspace 不得混用                     |

**注意**：`resolve_active_tenant_id`（[:227](C:/Projects/RAG/wenruo-rag/api/db/services/user_service.py:227)）在无显式选择时
会回退到 `user_id` 自身（owner 的个人 workspace 约定）。因此 **`user_id == tenant_id` 的数值相等本身不构成任何授权证据**；
U1 必须靠 membership 行建立 workspace，而不是靠 id 形态或相等比较。
已证明的域错误（`chat_api.py:1198`、`file_service.py:717`、`openai_api.py:240`）保持未修复（§6），
U1 不得复制其模式，也不得顺手修复它们。

### 5.2 端点级查询隔离规则（冻结）

统一前置：`login_required` → 取 `current_user.id` → 用请求中显式 workspace 走
`resolve_config_tenant_id(current_user.id, requested_workspace_id)`（失败抛 `WorkspaceAccessDenied`）→
`UserTenantService.get_role(current_user.id, workspace_id)` 取角色，且**每次请求重新校验 live membership（`status='1'`）**，
不得只信缓存或客户端参数。UI 隐藏从不构成授权边界。

| 视图 / 能力                       | NORMAL 成员                                            | OWNER / ADMIN                                          |
|-----------------------------------|--------------------------------------------------------|--------------------------------------------------------|
| `my_usage`（自己的用量）           | **允许**，条件 `tenant_id == 已解析 workspace AND user_id == current_user.id` | 允许（自身行）                                          |
| 自己的日/月 series                 | 允许                                                    | 允许                                                    |
| 自己的 estimated model cost / 覆盖 | 允许                                                    | 允许                                                    |
| `quota_status`（limit + 自己用量 + 豁免事实） | 允许（本人维度）                                | 允许（含 workspace 维度）                                |
| `workspace_summary`（workspace 聚合） | **拒绝**（会暴露其他成员用量）                        | 允许，且**仅限当前已解析 workspace**                     |
| `member_breakdown`                | **拒绝**                                                | 允许；含 OWNER/ADMIN 自身与已移除成员的历史行             |
| `recorded_model_breakdown`        | **拒绝**                                                | 允许                                                    |
| 按任意 `user_id` 查询              | **拒绝**（除 `== current_user.id`）                     | 允许，但仅限当前 workspace                                |
| 跨 workspace / 全局聚合            | **拒绝**                                                | **拒绝**（无 global 参数、无 “all workspaces” 模式）       |
| 原始 ledger 行导出                 | **拒绝**                                                | **拒绝**（只经 read model 聚合视图）                      |
| provider 配置 / credential        | **拒绝**                                                | **拒绝**（配置访问是另一条权限，不在 U1）                  |
| WorkspaceAudit 变更记录            | **拒绝**                                                | 允许读取（仅本 workspace）                                |
| 已移除成员（无 live 行）           | 一律**拒绝**，返回 code=108                             | 同上；其历史行仍计入 workspace 聚合，`user_id` 保留         |

显示名解析：成员显示名**只允许 LEFT JOIN** 一个可变维表；`INNER JOIN` 会静默丢掉已删除用户的历史行，禁止。

### 5.3 只读性与错误契约（冻结）

- U1 的 GET 端点**不得**执行 `Tenant.update(name=Tenant.name)` 自锁写操作（对比
  [`configure_budget`:120](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:120)）；只允许纯 SELECT。
- 内部拒绝统一走 `WorkspaceAccessDenied` → [`server_error_response`:156](C:/Projects/RAG/wenruo-rag/api/utils/api_utils.py:156) →
  [`get_error_permission_result`:395](C:/Projects/RAG/wenruo-rag/api/utils/api_utils.py:395) → **HTTP 200 + `code=108`**
  （`RetCode.PERMISSION_ERROR = 108`，[constants.py:54](C:/Projects/RAG/wenruo-rag/common/constants.py:54)）。
  不得用 HTTP 403/429 表示内部拒绝，不得泄漏 provider 错误体或密钥。
- 现有 `GET/PUT /tenants/<tenant_id>/usage-budget`（[tenant_api.py:358](C:/Projects/RAG/wenruo-rag/api/apps/restful_apis/tenant_api.py:358)）
  的契约、权限边界与审计行为**保持不变**；它的权限检查位于 service 内（[workspace_budget_service.py:121](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:121)），
  不得改写成“无权限控制”或“新增权限控制”。
- 角色语义不因 U1 改变：OWNER/ADMIN 的限额豁免、其用量仍被记录这两点都必须在 UI 上显式呈现。

### 5.4 对账门（Reconciliation Gate）

对**完全相同的 scope 与语义**（workspace + period + status predicate + 同一代码路径）必须成立：

1. `sum(member_breakdown) == workspace_total`；
2. `COUNT(ledger attempts WHERE tenant,user,period) == workspace_usage.calls`（同 member 同期），
   分叉时必须作为数据质量问题**显式返回**，不得静默取其一；
3. day 与 month 分别对账，**不得相加**。

## 6. Backlog（U0 发现保持封存，本轮未修复）

以下条目**本轮全部保持未修复**，不新建修复分支、不改代码、不做 backfill、不补历史归因：

| ID (proposed)   | U0 发现                                                             | 归属批次 |
|-----------------|---------------------------------------------------------------------|----------|
| U4-01           | 特殊任务 enqueue 丢失已认证 caller（`dataset_api_service.queue_raptor_o_graphrag_tasks` 等），task 未保存 initiator | U4 |
| U4-02           | 远程 OCR parse 绕过 `@budgeted`（`rag/flow/parser/parser.py:412` 等）   | U4 |
| U4-03           | vision/ASR/TTS 结算缺口：读到 `used_tokens` 但未 `record_dispatch_usage`，长期停留 `unsettled` | U4 |
| U4-04           | chat 无可信 split 时按零成本结算（`llm_service._report_usage` → `_close_dispatch`） | U4 |
| U4-05           | task row 是 detached 归因的唯一载体；mid-job 撤权不重查                  | U4 |
| U4-06           | 已证明身份域错误：`chat_api.py:1198`、`file_service.py:717`、`openai_api.py:240` | U4 |
| U4-07           | `per-doc RAPTOR helper` 仅定义无调用：UNKNOWN 活跃性，不得当活跃事故      | U4（观测） |
| U4-08           | anonymous webhook / background sync 的付费服务身份未决策                | U4（决策） |
| U5-01           | 无统一持久 provider/instance 健康事实；`last_success/last_failure` 无列   | U5 |
| U5-02           | P0 `reason_from_exception` 把 dense 的 429/rate 归为 `EMBEDDING_QUOTA_EXHAUSTED`，不能作为“上游余额耗尽”的严格证据 | U5（不修改 P0-7） |
| U3-01           | 现有 cost enforcement 不是 workspace 严格金额硬帽（per-member、管理者豁免、超预留补记不再检查 cap） | U3 |
| U3-02           | 无自动 counter/ledger 对账与重建任务                                      | U3 |

`BACKLOG.md`（仓库根）本轮**未修改**；上述条目即为本报告封存的 U0 Backlog 登记，
`sealed` 的含义是“已知、已记录、本轮不修”。

## 7. Production Shape Validation — 未获授权

`PRODUCTION_SHAPE_VALIDATION: NOT_AUTHORISED`。

- 本轮执行任务清单**不包含**生产形状核对；红线为 NO DB/Redis/Production mutation，且未提供任何已授权的只读连接。
- U0 遗留 Open Decision #2（“生产只读验证使用哪个已授权连接/环境”）**仍未回答**。
- 因此以下 U0.5 目标仍然未知，且不得用历史部署结论填补：线上 `workspace_usage` / `workspace_usage_ledger` 的实际表/索引漂移、
  ledger 行数量级与保留现状、`period_day`/`period_month`/`model_name` 无索引对 U1 聚合查询的真实代价、
  线上“有价/无价/无效价”模型清单。

**该未知对本轮结论的影响**：U0 已把“无 secret 的生产形状核对”列为 U1 的准入条件
（U0 §9 U1 行：`需要source tests可运行和无secret生产shape核对`）。其中 source tests 本轮已达成，
生产形状核对未获授权 ⇒ **U1_IMPLEMENTATION_READY 仍为 NO**，唯一残留阻塞即此项（另见 §10）。

只读核对所需的最小授权（不含任何 key）：仅取 schema/索引清单、`status` 分布、`period_*` 时间范围、
ledger 行数/表大小、以及模型 pricing 的**白名单字段**（是否有 `price_input_per_million`/`price_output_per_million` 及其值），
**不选 `api_key` 或任何 secret 列**，不 hydrate credential ORM 对象。

## 8. Proposed U1 File Scope（分类，不修改）

### READ（实现 U1 时必须阅读，U1 不改动）

- `api/db/db_models.py` — `WorkspaceUsage` / `WorkspaceUsageLedger` / `WorkspaceBudget` / `WorkspaceAudit` / `UserTenant` 定义。
- `api/db/services/workspace_budget_service.py` — 语义权威来源（reserve/settle/release/usage_snapshot）。
- `api/db/services/user_service.py` — `resolve_config_tenant_id`、`resolve_active_tenant_id`。
- `api/db/services/workspace_member_service.py` — 成员/角色/移除语义。
- `common/workspace_context.py`、`common/exceptions.py`、`common/constants.py` — 身份与错误契约。
- `api/utils/api_utils.py` — `server_error_response` / `get_error_json` 系列返回契约。
- `api/apps/restful_apis/tenant_api.py` — 既有 usage-budget 路由先例（只读参照）。
- `test/unit_test/api/db/services/test_workspace_budget_settlement.py`、`test_workspace_security.py`、`test_detached_task_initiator.py` — 源测试。

### NEW（U1 V1 新建）

- `api/db/services/workspace_usage_read_service.py` — read model：纯 SELECT 聚合、列白名单投影、无写操作、
  无 credential 载入；承载 §1 指标、§3 决策表、§4 覆盖判定、§5 隔离与对账。
- `api/apps/restful_apis/workspace_usage_api.py` — GET 端点（`my_usage` / `workspace_summary` / `member_breakdown` /
  `daily_series` / `monthly_series` / `quota_status` / `recorded_model_breakdown`）。
  该目录下的 `.py` 由 [api/apps/__init__.py:415](C:/Projects/RAG/wenruo-rag/api/apps/__init__.py:415) 的 glob 自动发现并
  注册到 `/api/<API_VERSION>`（[:447](C:/Projects/RAG/wenruo-rag/api/apps/__init__.py:447)），**无需修改 `api/apps/__init__.py`**。
- `test/unit_test/api/db/services/test_workspace_usage_read_model.py` — 新增源测试：scope 隔离、
  NORMAL vs OWNER/ADMIN、有效值公式、`unsettled` 双成因、coverage 判定、对账门、user/workspace 域互换必须被拒。
- `docs/key-usage/workspace-ai-usage-provider-reliability-u1.md` — U1 记录（U1 阶段创建）。

### MODIFY（U1 阶段允许改动的全部文件）

- `docs/key-usage/ROADMAP.md` — 仅状态记账。
- `AGENTS.md` — 里程碑/证据/决策。
- （无其他。）**明确不做**：不新增列、不新增表、不写 migration、不改 `api/apps/__init__.py`、不改既有路由。

### DO_NOT_TOUCH

- `api/db/db_models.py` — U1 V1 无 schema 变更；migration 规则为 append-only，不得改动既有 `alter_db_*`。
- `common/model_budget.py` — dispatch 边界与 reserve/settle 语义已冻结；改动属 U4。
- `api/db/services/workspace_budget_service.py` — enforcement；U1 只读，不改。
- `api/db/services/llm_service.py` — 结算调用点（describe/transcription/tts 缺口属 U4）。
- `rag/flow/parser/parser.py` — OCR 绕过（U4）。
- `rag/svr/task_executor.py`、`rag/svr/task_executor_refactor/**`、`api/db/services/task_service.py`、
  `api/db/services/document_service.py`、`api/db/services/dataset_api_service.py` — detached 归因缺口（U4）。
- `api/apps/restful_apis/chat_api.py`、`api/db/services/file_service.py`、`api/apps/restful_apis/openai_api.py` — 已证明身份域错误（U4）。
- `api/db/joint_services/tenant_model_service.py` — credential/pricing 解析；U1 不得为补历史归因读取它。
- `web/**` — 全部 UI（U2/U3/U6）。
- `rag/retrieval/**`、`rag/nlp/**`、`common/metadata_es_filter.py`、`deepdoc/**` — 检索/P1 工作，与 Usage & Operations 无关。
- **本轮工作树中既有的未提交改动**（不属于本轮，不得提交、还原或基于其建设）：
  `rag/nlp/search.py`、`rag/retrieval/rerank.py`、`rag/utils/es_conn.py`、
  `test/unit_test/rag/nlp/test_gaussdb_retrieval.py`、`test/unit_test/rag/test_search_fusion_weight.py`、`deploy/**`。

## 9. U0.5 结论矩阵

```text
U1_V1_SCOPE_ACCEPTABLE: YES
U1_SOURCE_TEST_ENVIRONMENT: READY
PRODUCTION_SHAPE_VALIDATION: NOT_AUTHORISED
R1_SCOPE_TRUTHFULNESS: PASS
R2_TEST_ENVIRONMENT: PASS
R3_ACCOUNTING_SEMANTICS: PASS
R4_AUTHORIZATION: PASS
R5_COST_HONESTY: PASS
R6_PRODUCTION_SHAPE: NOT_AUTHORISED
API_KEY_PLAINTEXT_READS_DURING_U0_5: 0
PRODUCTION_MUTATED: NO
DATABASE_MUTATED: NO
REDIS_MUTATED: NO
U1_IMPLEMENTED: NO
U1_IMPLEMENTATION_READY: NO
```

`U1_IMPLEMENTATION_READY: NO` 的理由是**单一且具体**的：生产安全形状核对未获授权（§7）。
scope 冻结、源测试环境、会计语义、授权矩阵、成本术语五项均已冻结，不是“建议先新增字段”，
也不是“聚合就够了”；U1 V1 是 query-only、零 migration 的最小读取模型。

## 10. 停止点

- 本轮未实现 U1 代码/UI/API/migration；未修任何 U0 缺陷；未连接生产；未读写 Redis；未读取任何 API key 明文。
- 本轮仓库改动仅限文档与验收记录：本报告、`docs/key-usage/workspace-ai-usage-provider-reliability-u0-5.md`、
  `docs/key-usage/workspace-ai-usage-provider-reliability-u0.md`（U0 报告本轮一并入库）、
  `docs/key-usage/ROADMAP.md`（本轮一并入库）、`AGENTS.md`（里程碑 + Pending 决策条目）。
  提交为 parent `138a1a79a67864e1361f3e2cbb70315b97770ffb` 之上的单次 commit，
  标题：`docs(key-usage): U0.5 readiness closure - frozen U1 V1 scope, accounting and authorization, source tests executed`。
- **未提交、未还原、未触碰**的既有工作树改动（不属于本轮，也不属 U0.5 范围）：
  `rag/nlp/search.py`、`rag/retrieval/rerank.py`、`rag/utils/es_conn.py`、
  `test/unit_test/rag/nlp/test_gaussdb_retrieval.py`、`test/unit_test/rag/test_search_fusion_weight.py`，
  以及未跟踪的 `deploy/**` 审计产物。把它们并入本次 readiness commit 会把无关的 retrieval/fusion 工作与部署产物混入 U0.5 记录，
  因此明确留待各自批次处理。
- **STOP**：不开始 U1 代码执行，等待明确授权。
