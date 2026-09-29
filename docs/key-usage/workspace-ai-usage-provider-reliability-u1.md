# Workspace AI Usage & Provider Reliability — U1 Usage Read Model

实现日期：2026-09-29。基线 commit `163ab8b1c`（U0.6 之后）。范围：**只读 usage read model**（frozen U1 V1）。

本轮实现内容、冻结语义、授权矩阵、性能护栏与验收证据如下。**没有 DB migration、没有修改 enforcement/settlement、
没有修改 ledger schema、没有修改定价配置、没有触碰 U4 缺项/Provider Health/Notifications/前端/P0-检索-P1 代码，
也没有访问生产 DB/Redis/配置。**

## 1. 交付文件

| 文件                                                        | 类型 | 说明                                                                     |
|-------------------------------------------------------------|------|--------------------------------------------------------------------------|
| `api/db/services/workspace_usage_read_service.py`            | NEW  | read model：纯 SELECT 聚合、列白名单投影、无写操作、无 credential 载入        |
| `api/apps/restful_apis/workspace_usage_api.py`               | NEW  | 7 个 GET 端点；由 `*restful_apis/*.py` glob 自动注册，无需改 `api/apps/__init__.py` |
| `test/unit_test/api/db/services/test_workspace_usage_read_model.py` | NEW | 43 个源测试（授权、会计、成本、护栏、只读性、API 层）                  |
| `docs/key-usage/workspace-ai-usage-provider-reliability-u1.md` | NEW | 本文件                                                                   |
| `docs/key-usage/ROADMAP.md`                                  | MODIFY | 追加 U1 状态行                                                         |
| `AGENTS.md`                                                  | MODIFY | U1 里程碑 + Pending 更新                                                |

已实测注册结果（真实 app bootstrap，`from api.apps import app`）：

```text
/api/v1/tenants/<tenant_id>/usage/my
/api/v1/tenants/<tenant_id>/usage/summary
/api/v1/tenants/<tenant_id>/usage/members
/api/v1/tenants/<tenant_id>/usage/daily
/api/v1/tenants/<tenant_id>/usage/monthly
/api/v1/tenants/<tenant_id>/usage/models
/api/v1/tenants/<tenant_id>/usage/quota
```

与既有 `/api/v1/tenants/<tenant_id>/usage-budget` 并存，无路由冲突。全部只接受 `GET`。

## 2. 数据来源：只有既有权威事实

| 来源                     | 用途                                                                     |
|--------------------------|--------------------------------------------------------------------------|
| `workspace_usage_ledger` | 逐 attempt 事实：calls 计数、settled/reserved/unsettled、tokens、cost、recorded model name |
| `workspace_usage`        | durable period counters：quota_status 的占用（与 enforcement 同源）与对账基准 |
| `workspace_budget`       | 限额与 timezone；**缺行 = 后端默认值**                                      |
| `user_tenant`            | live membership / role 校验                                              |
| `user`                   | 仅成员显示名（独立查询，非 join）                                          |

`quota_status` 的占用直接调用 enforcement 自己的 `workspace_budget_service.usage_snapshot`，
并用测试断言二者读数一致；**未调用 `configure_budget`**（其读路径会执行 `Tenant.update(name=Tenant.name)` 自锁写操作），
且测试断言 read model 源码中不出现该名称、并在 `Tenant.update` 被替换为抛错时仍能正常返回。

## 3. 冻结会计语义（实现即断言）

### 3.1 有效值公式

```text
effective_tokens = CASE WHEN status='settled' THEN tokens ELSE reserved_tokens END
```

`settled` 计入 settled tokens；`reserved`/`unsettled` 计入 reserved 占用。
**只读 `tokens` 会把未结算 attempt 当作 0**：在 U0.6 实测的 live 数据上，
正确值 1,615,894 而 naive `SUM(tokens)` 只有 916,565，**低估 43.3%**。测试 `test_effective_tokens_is_the_occupancy_formula_not_a_naive_token_sum`
与 `test_settled_reserved_and_unsettled_are_calculated_separately` 锁死该公式（mutation 验证见 §7）。

### 3.2 calls

`attempted_calls` = ledger 行数（一次受计量 dispatch attempt 一行）。dispatch 前的预算拒绝不写行，
因此**拒绝不在分母**。同时返回 `counter_calls` 用于对账，两者不一致时**如实上报**而不是择一。

### 3.3 行分区不变式

每一行恰好落入 established / unestablished / zero_usage 之一，三者和恒等于 `attempted_calls`；
测试显式断言该分区，因为静默漏行会让成本覆盖度说谎。

| 判定                                                          | 含义                                     |
|---------------------------------------------------------------|------------------------------------------|
| `established`                                                 | 该行的成本值有定价证据（settled 且 `cost_micros>0`，或 outstanding 且 `reserved_cost_micros>0`） |
| `unestablished`                                               | 消耗了 token 但无任何定价证据              |
| `zero_usage`                                                  | 既无 token 也无成本                       |

### 3.4 `reserved` 不等于"仍在运行"

`reserved` 行的语义是"上限被占用"，包含**进程崩溃留下的孤立预留**（U0.6 已在 live 数据上实测到 7 条、
最新一条已 2 天未变动），也包含"结束但未报告 usage"。因此：

- 计入 `outstanding_attempts` / `outstanding_reserved_tokens`，**永不当作 0**；
- payload 中**没有任何字段名**暗示 running / in-flight / active / provider usage（测试遍历 accounting 的键断言）；
- 免责说明随 payload 返回（`notes`），测试断言该说明存在。

### 3.5 日 / 月永不求和

一次预留同时 +1 day 行与 month 行。所有 day 视图只读 day 行、month 视图只读 month 行；
reconciliation 额外返回 `counter_rows`，行数异常即说明两类 period 被相加。

## 4. 成本：`Estimated model cost` 与"绝不 $0.00"

- 展示术语只有 **`Estimated model cost`**（`cost.term`），单位 `micro_usd`；`Bill` / `Invoice` / `Actual charge` / `Actual provider cost` 不出现。
- 两个成本数字**各自独立**按其自身定价证据决定是否为 `null`：

| 字段                                        | 非空条件                                    |
|---------------------------------------------|---------------------------------------------|
| `accounting.settled_estimated_cost_micros`  | 至少 1 条 settled 行有定价证据               |
| `accounting.outstanding_reserved_cost_micros` | 至少 1 条 outstanding 行有定价证据           |

  这条规则是本轮实现中最重要的诚实性修正：若只有一个全局开关，
  "有定价的 settled 行 + 无定价的预留" 会让 outstanding 成本显示成 `0`，
  等于声称"价格未知的占用成本为零"。测试 `test_outstanding_cost_is_null_when_no_reservation_carried_pricing` 锁死它。
- 覆盖度三值：`complete`（全部行有证据）/ `partial`（混合）/ `unavailable`（无任何证据，含空集合）。
  额外给出 `settled_cost_coverage` 与 `outstanding_cost_coverage` 便于前端分别渲染。
- **当前 live 栈是 0 PRICED / 75 UNPRICED**：所有 live 作用域的 `cost_coverage` 都是 `unavailable`，
  两个成本字段都是 `null`。本 read model 因此只会显示 "Not available"，**不会显示 `$0.00`**。
  测试 `test_the_live_zero_priced_shape_reports_unavailable` 用把全部成本清零的 fixture 复现该形状。

## 5. 授权（每个查询都校验）

`resolve_read_scope(actor_user_id, workspace_id, member_user_id=None, workspace_wide=False)` 是唯一入口，
**每次调用都重新校验 live membership（`status='1'`）**，然后才决定 subject：

| 调用者        | 允许                                                             | 拒绝                                                        |
|---------------|------------------------------------------------------------------|-------------------------------------------------------------|
| NORMAL 成员   | 仅自己的行（`tenant_id == 解析出的 workspace AND user_id == 自己`）；我的用量 / 我的配额 | workspace 聚合、成员明细、模型明细、日/月序列、指定他人 `user_id` |
| OWNER / ADMIN | 当前 workspace 的聚合、成员明细、模型明细、日/月序列；可指定本 workspace 的某个成员查看配额 | 跨 workspace 聚合、全局模式、原始 ledger 导出、provider/credential |

- 三个身份域保持分离：`workspace_id` 是资源 workspace 键，`actor_user_id` 是成员键，**从不互相代入**。
  测试 fixture 特意让 workspace id 不等于任何 user id，并断言
  "把 user id 当 workspace 传入会被拒（无 membership）"、以及"同一调用者用 membership 解析到真实 workspace 可以成功"。
  这条很重要：U0.6 实测 live 上唯一被计量的 `(tenant_id, user_id)` 组合 **tenant_id == user_id**，
  所以在 live 数据上"按值区分"物理不可能，隔离只能由多成员 fixture 证明。
- 已移除成员：无法读取（抛 `WorkspaceAccessDenied` → `server_error_response` → **HTTP 200 + code=108**）；
  其历史行仍计入 workspace 聚合与成员明细（`live_member=false`，`role=null`，`exempt=null`）。
- 显示名用独立查询而非 JOIN：不存在 INNER JOIN 丢历史行的路径。
- 拒绝统一走既有的 `WorkspaceAccessDenied` 通道，不使用 HTTP 403/429，不泄漏 provider 错误或密钥。

## 6. 性能护栏（无 migration）

`period_day` / `period_month` / `model_name` 在 live schema 上**无索引**（U0.6 实测），因此：

| 护栏                        | 值                                                                 |
|-----------------------------|---------------------------------------------------------------------|
| 日窗口默认 / 上限            | 31 天 / **92 天**（超出直接拒绝，不分页不静默截断）                    |
| 月窗口默认 / 上限            | 6 个月 / **24 个月**                                                 |
| 分页                        | `limit` 默认 50、上限 **200**；`offset` ≥ 0；返回 `truncated` + `total_*` |
| 无范围参数的端点             | 只有 `quota_status`，且它固定为当前 day+month 两个 period（天然有界）    |
| 无界历史扫描端点             | **不存在**：没有任何端点允许"全历史"查询                              |

日期/月份格式、`start > end`、负数、非整数、未知视图、未知查询参数一律拒绝（参数白名单在 API 层，`from_day` 这类拼写错误不会被静默忽略成另一个窗口）。

序列视图对窗口内每一天都输出 bucket（`zero_filled`），并说明"`attempted_calls=0` 表示该期间没有受计量 attempt，
不代表在 ledger 存在之前测得为零"，避免把"无数据"读成"零用量"。

**索引与保留策略不在 U1 实现范围**，作为 backlog 记录（见 §9）。

## 7. 测试与证据

```powershell
# workdir: C:\Projects\RAG\wenruo-rag
C:\Projects\RAG\wenruo-rag\.venv\Scripts\python.exe -m pytest `
  test/unit_test/api/db/services/test_workspace_usage_read_model.py `
  test/unit_test/api/db/services/test_workspace_budget_settlement.py `
  test/unit_test/api/db/services/test_workspace_security.py `
  test/unit_test/api/db/services/test_detached_task_initiator.py `
  -p no:cacheprovider -q --no-header -rs
```

结果：`collected 93` → **`91 passed, 2 skipped`，exit 0**。

| 文件                                        | collected | passed | skipped | 说明                       |
|---------------------------------------------|-----------|--------|---------|----------------------------|
| `test_workspace_usage_read_model.py`（新）   | 43        | 43     | 0       | U1 新测试                  |
| `test_workspace_budget_settlement.py`（既有）| 30        | 30     | 0       | 回归                       |
| `test_workspace_security.py`（既有）         | 15        | 13     | 2       | 回归；2 个 Redis-gated skip |
| `test_detached_task_initiator.py`（既有）    | 5         | 5      | 0       | 回归                       |

2 个 skip 的原因与 U0.5 一致（`TEST_REDIS_URL must identify an isolated test Redis`），本轮同样**未设置该变量**，
因为指向共享实例属于 Redis 写操作。U1 read model 不读取 Redis。

### 强制测试清单覆盖对照

| 要求                                     | 测试                                                          |
|------------------------------------------|---------------------------------------------------------------|
| NORMAL 仅自己                            | `test_normal_member_reads_their_own_usage`                     |
| NORMAL 不能读他人                        | `test_normal_member_cannot_read_another_member`、`test_a_normal_member_cannot_request_another_members_quota` |
| OWNER/ADMIN workspace 聚合               | `test_owner_and_admin_read_the_workspace_aggregate`            |
| 跨 workspace 拒绝                        | `test_cross_workspace_reads_are_refused`                       |
| `tenant_id != user_id` fixture           | `test_a_user_id_is_never_treated_as_a_workspace_id`（fixture 本身即 `ws-alpha` ≠ 任何 user id） |
| 多成员 fixture                           | `test_multi_member_breakdown_reports_every_member`             |
| settled/reserved/unsettled 计算          | `test_settled_reserved_and_unsettled_are_calculated_separately` |
| stale reserved 仍是 outstanding          | `test_a_stale_reservation_stays_outstanding_and_is_not_running` |
| 无定价 → unavailable 而非 `$0`            | `test_missing_pricing_is_unavailable_never_zero`、`test_outstanding_cost_is_null_when_no_reservation_carried_pricing`、`test_the_live_zero_priced_shape_reports_unavailable` |
| PRICED 路径                              | `test_priced_rows_make_the_cost_available`、`test_workspace_cost_coverage_is_partial_when_pricing_is_mixed` |
| 缺 `workspace_budget` → 默认值            | `test_a_missing_budget_row_means_backend_defaults`、`test_a_configured_budget_row_is_reported_as_configured` |
| model_name 未知/未归因                    | `test_an_unrecorded_model_name_is_an_explicit_bucket`、`test_model_breakdown_is_recorded_name_only` |
| workspace 总量与成员明细对账              | `test_workspace_total_reconciles_with_the_member_breakdown`、`test_a_counter_ledger_divergence_is_reported_not_hidden` |
| 日期范围有界                              | `test_a_day_range_is_bounded`、`test_a_month_range_is_bounded`、`test_a_malformed_or_inverted_range_is_refused`、`test_pagination_bounds_are_enforced` |

另有：只读性（`test_the_read_model_writes_nothing` 全表快照前后一致 + `WorkspaceAudit` 无新增行）、
无租户自锁（`test_the_read_path_never_takes_the_budget_write_lock`）、
配额与 enforcement 读数一致（`test_quota_occupancy_matches_the_enforcement_read_source`）、
日/月不求和（`test_day_and_month_counters_are_never_summed`）、
API 层路由与参数映射（`test_the_api_layer_exposes_exactly_the_frozen_views`、`test_the_api_layer_maps_every_parameter_to_a_view_keyword`）。

### Mutation 验证（证明测试非空转）

临时注入三个反向变更并确认被捕获，随后全部还原：

| Mutation                                                        | 结果                     |
|------------------------------------------------------------------|--------------------------|
| 成本字段无证据时返回 `0` 而不是 `None`                              | 3 个测试 FAILED（`assert 0 is None`） |
| 有效值公式退化为 `tokens`（naive 求和）                             | 2 个测试 FAILED（`assert 150 == 950`、`assert 219 == 1089`） |
| 允许 NORMAL 读 workspace 聚合                                       | 1 个测试 FAILED（`DID NOT RAISE WorkspaceAccessDenied`） |

## 8. 端点与返回形状

所有端点返回 `get_json_result(data=...)`（HTTP 200）。每个视图统一信封：

```text
view, scope{workspace_id, actor_user_id, role, workspace_wide, subject_user_id, timezone, limits_source},
period{...}, accounting{...}, cost{term, unit, coverage, settled_coverage, outstanding_coverage, notes},
notes[...], [reconciliation{...}], data{...}
```

`accounting` 固定字段：`attempted_calls`、`settled_attempts`、`reserved_attempts`、`unsettled_attempts`、
`outstanding_attempts`、`unrecognised_status_attempts`、`settled_tokens`、`outstanding_reserved_tokens`、
`effective_tokens`、`settled_estimated_cost_micros`、`outstanding_reserved_cost_micros`、
`cost_coverage`、`settled_cost_coverage`、`outstanding_cost_coverage`、
`cost_established_rows`、`cost_unestablished_rows`、`zero_usage_rows`。

`unrecognised_status_attempts` 用于暴露"出现第四种 status"这类漂移，而不是把它静默塞进 outstanding。

| 端点              | 视图                       | 关键 `data`                                                              |
|-------------------|----------------------------|--------------------------------------------------------------------------|
| `/usage/my`       | `my_usage`                 | 无（accounting + reconciliation）                                         |
| `/usage/summary`  | `workspace_summary`        | `member_count`、`recorded_model_count`、`unrecorded_model_attempts`        |
| `/usage/members`  | `member_breakdown`         | `members[{user_id,nickname,name_available,live_member,role,accounting}]`、分页  |
| `/usage/daily`    | `daily_series`             | `buckets[{period,attempted_calls,accounting}]`                            |
| `/usage/monthly`  | `monthly_series`           | 同上，月粒度                                                              |
| `/usage/models`   | `recorded_model_breakdown` | `models[{recorded_model_name,bucket,attribution,provider=null,key_instance=null,workload=null,accounting}]` |
| `/usage/quota`    | `quota_status`             | `limits`、`limits_scope`、`limits_source`、`standing`、`subject`、`workspace_occupancy` |

`quota_status` 的 `limits_source` 明确区分 `workspace_budget_row` / `backend_defaults`；
limit=0 的维度 `enforced=false` 且 `remaining=null`（**不是"剩余 0"**）；
滚动分钟 `used=null` 且注明"由 Redis 跟踪，本 read model 不读取"；
管理者额外获得 `workspace_occupancy`，并标注 `comparable_to_limits=false`（限额是 per-member 规则）。

## 9. 未做 / Backlog

- **无 migration**：未新增列、未新增表、未新增索引、未改既有 `alter_db_*`。
- **索引与保留策略（backlog，需单独授权）**：`period_day`/`period_month`/`model_name` 无索引；
  建议 `(tenant_id, period_day)` 与 `model_name` 复合索引以支撑多成员体量，并决定 ledger 保留周期。
  U0.6 已量化：1109 行 / 1.06 MiB / 单成员约 370 行/天；20 成员 ≈ 2.7G B/年，500 成员 ≈ 68 GB/年。
- **保留的 U0 缺陷**（本轮未修，仍在 backlog）：特殊任务 enqueue 丢 caller、远程 OCR 绕过预算、
  vision/ASR/TTS 结算缺口、零 split 零成本、detached mid-job 不重查、已证明的身份域错误、provider 健康事实缺失等。
- **Provider Health / Notifications / 前端 / P0-检索 / P1** 均未触碰。

## 10. 非阻塞但必须带入 U1 验收计划的条件

1. live 数据中**不存在 NORMAL 成员的计量行**，且唯一被计量组合满足 `tenant_id == user_id`。
   因此本栈上的 live smoke **无法区分**"域正确"与 `tenant_id = current_user.id` 走捷径；
   隔离由多成员 SQLite fixture 证明（本轮已做），live 验收需要新建 NORMAL 成员与第二个 workspace 的 fixture ——
   **那是数据写入，需单独授权**。
2. live 全栈 **0 PRICED**，`PRICED` 路径与 `unrecorded` 桶在 live 上无数据，只能由 fixture 覆盖（本轮已覆盖）。
3. `workspace_budget` live 0 行，`backend_defaults` 是 live 主路径（本轮已覆盖）。
4. 建议的下一步（需单独授权）：在只读连接上对 live 库运行本 read model，
   与 U0.6 独立测得的 1109 行 / 1,615,894 有效 tokens / 0 priced 交叉验证。**本轮未执行**，
   因为本轮授权为 U1 实现，未包含生产只读访问。

## 11. 停止点

U1 实现完成，测试与既有预算/安全回归全绿。**U2（Settings UI 框架）未开始，等待明确授权。**
