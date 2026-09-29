# Workspace AI Usage & Provider Reliability — U2 Settings Framework & U1 API Integration

实现日期：2026-09-29。基线：U1 commit `ae4c1399f`。范围：**Settings 导航与页面骨架 + U1 用量只读 API 接入**。

本轮**只做前端**：没有 backend/DB 变更、没有 migration、没有新增后端接口、没有伪造任何数值。

## 1. 边界与红线

| 红线                                     | 本轮状态                                                                                     |
|------------------------------------------|----------------------------------------------------------------------------------------------|
| NO backend DB migration                  | 遵守：`api/` 与 `migrations` 零改动                                                          |
| NO backend API modification              | 遵守：未新增/修改任何后端路由；仅调用已存在的 `GET /api/v1/models` 与 U1 的 7 个 GET 端点       |
| NO fake data / mock metrics              | 遵守：Provider Health / Retrieval Health 为诚实空状态；通知抽屉不构造任何事件                 |
| Strict role-based view enforcement        | 遵守：NORMAL 仅 "My Usage"；Workspace Analytics / Health 仅 OWNER/ADMIN 渲染                   |
| 只接 U1 的 7 个端点做用量数据              | 遵守：用量数据全部来自 `workspace_usage_api.py` 的 7 个视图                                   |
| 成本显示规则                             | 遵守：`null` / `unavailable` → "Not available"；**绝不 `$0.00`**                              |

唯一被 `src/components/ui/` 之外的既有页面改动是**追加式**的：`setting-model/index.tsx` 与 `setting-team/index.tsx`
各插入一个只读区块；`src/components/ui/**` 未改动一行。

## 2. Settings 导航结构

`src/pages/user-setting/sidebar/index.tsx` 的导航栏（沿用既有 rail，不改布局）：

| 顺序 | 入口             | 路由                  | i18n key                    |
|------|------------------|-----------------------|-----------------------------|
| 1    | Model providers  | `/user-setting/model` | `setting.model`（既有，无需改文案） |
| 2    | Team             | `/user-setting/team`  | `setting.team`（既有）        |
| 3    | **Usage & operations** | `/user-setting/usage`（新增） | `setting.usageOperations`（新增） |
| 4    | Profile          | `/user-setting/profile` | `setting.profile`（既有）    |

- 第 4 项 **保留**：它是既有的账号入口，本轮不删除任何既有目的地；规范中的三个编号条目是控制台分区，不是"删掉 Profile"。
- 新增 `Routes.Usage = '/usage'` 与路由 `${Routes.UserSetting}${Routes.Usage}`，并在 `user-setting/index.tsx` 的
  `SectionLabelKeys` 里补上面包屑标签，使面包屑与 rail 高亮不会漂移。
- 三个新 rail 入口都带 `data-testid`，便于浏览器验收。

## 3. Model Providers：Managed API / Private Endpoint + 能力标签

新增只读组件 `setting-model/model-provider-overview.tsx`，以 `shrink-0` 追加在既有 provider rail 内（`<Sidebar />` 之后），
不改动右侧配置面板，也不改任何凭据流程。

**数据来源**：`GET /api/v1/models`（**既有**端点，`src/hooks/use-model-provider-request.ts`）。它只返回
provider / instance / model 身份与 `model_type`，**payload 中不含任何凭据字段**；相比之下 provider-instance 端点会带
`api_key` 字段，因此**刻意不使用**。概况面板只渲染 provider 名、instance 名、模型名、能力标签与配置状态。

| 显示项             | 来源                                        |
|--------------------|---------------------------------------------|
| Provider Name      | `provider_name`                             |
| Type               | `classifyProviderEndpoint()`（见下）         |
| Configured Model   | `name` 列表 + 数量                           |
| Capabilities       | `model_type` → `[Chat][Embedding][Rerank][VLM]`（+ ASR/TTS/OCR） |
| Connection         | `instance_name` 列表（**不含任何凭据值**）    |
| Status             | 固定文案 "Status: not observed yet" —— 占位，不是健康结论 |

**分组判定**（`src/constants/model-provider-endpoint.ts`）：以仓库自身的 `LLMFactory` 枚举为准，
`Ollama / Xinference / LocalAI / LM-Studio / OpenAI-API-Compatible / VLLM / GPUStack / Builtin / FastEmbed / PaddleOCR.local`
判为 **Private Endpoint**，其余已知 factory 判为 **Managed API**；**不在任一清单中的 factory 落入显式 `Unclassified` 分组**，
而不是被默认当作托管 API —— 猜错会把自建网关标成云 API，所以宁可标注"未分类"。

**不做**：不显示 provider 余额、剩余额度、用量、健康状态、延迟。私有端点根本没有这些概念，
托管商侧也没有任何 adapter 可读，因此一律不显示而不是显示占位数字。

## 4. Team：Usage Policy 限额可视化（只读）

新增 `setting-team/usage-policy.tsx`，作为 Team 页的新卡片区块插入（在 Departments 之前）。

- **仅 OWNER/ADMIN**：`readOnly` 为真时组件返回 `null`；NORMAL 成员的自身额度在 My Usage 内展示。
- 数据来自 `GET /tenants/<id>/usage/quota`，即服务器实际执行的**同一份** `usage_snapshot`。
- 三种状态都必须可辨：
  - limit = 0 → 显示"未启用"，**不是"剩余 0"**；
  - OWNER/ADMIN → 显示"豁免"，不画一个永远达不到的进度条；
  - **缺 `workspace_budget` 行 → 显示"适用后端默认值"**，不暗示有人配置过这些数字。
- 滚动分钟维度的占用**不可得**（在 Redis 中，本读取模型不读 Redis），因此显式显示"此处不跟踪"并给出说明，
  而不是显示 0。
- 服务端自带的忠告文本（`not_answered`）**原文照显**，不做改写。
- 本轮**只做可视化**，不加编辑控件、不发 PUT：U2 不新增后端支持的限额，编辑入口维持原状。

## 5. Usage & Operations（4 个 Tab）

`src/pages/user-setting/usage-operations/`：

| Tab                 | 组件                        | 端点                                     | 可见角色        |
|---------------------|-----------------------------|------------------------------------------|-----------------|
| My Usage            | `my-usage.tsx`              | `/usage/my` + `/usage/quota`              | 全部成员        |
| Workspace Analytics | `workspace-analytics.tsx`   | `/usage/summary`、`/members`、`/models`、`/daily`、`/monthly` | OWNER/ADMIN |
| Provider Health     | `provider-health.tsx`       | 无（诚实空状态）                          | OWNER/ADMIN     |
| Retrieval Health    | `retrieval-health.tsx`      | 无（诚实空状态）                          | OWNER/ADMIN     |

**角色门禁**：`canManageTenant(userInfo?.role)` 为真才**挂载**管理员 tab；在 `/users/me` 返回之前不挂载，
因此 NORMAL 成员不会先看到管理员 tab 再被 108 拒绝。这是渲染决策，**不是授权边界** ——
服务端每次查询都重新校验 live membership，前端隐藏从来不构成权限。

**按视图就地取数**：每个 tab 组件自己发查询（TanStack Query，`WorkspaceUsageKeys` 工厂，key 内含 workspace id），
切 tab 不会连带请求其他视图的数据；隐藏的 `TabsContent` 不挂载，因此 NORMAL 不会触发工作区聚合请求。
统一使用 `empty`/`loading` 分支，加载中显示 skeleton，**不显示任何本地计算的数字**。

**对账条**：Workspace Analytics 顶部显示 `reconciliation`：计数器与账本一致时说明一致；不一致时
**同时列出两个数字**并说明系统不会自动对账，绝不择一显示。

**日 / 月永不求和**：日序列与月序列是两个独立端点、两张独立表格；月表附注说明月度合计独立统计。

**有界区间**：区间控件只提供 7 / 31 / 92 天三个预设（`resolveDayWindow`），始终显式传 `start_day`/`end_day`，
最宽预设正好等于服务端 92 天上限，前端无法构造无界历史请求。

## 6. 成本显示规则（本轮的核心诚实性）

单一实现点 `components/usage-format.ts::resolveCostDisplay`：

| 条件                                          | 渲染                                   |
|-----------------------------------------------|----------------------------------------|
| `coverage === 'unavailable'` 或数值为 `null`    | **"Not available"**（绝无 `$0.00`）      |
| `coverage === 'partial'`                       | 真实金额 + "Partial" 标记                |
| 其余（`complete` 且数值存在）                   | 金额                                    |

- `micros → USD` 单独实现：小于 1 分保留 6 位小数并去尾零，因此真实但极小的成本不会塌成 `$0.00`；≥1 分用 2 位小数。
- 术语只显示服务端返回的 `cost.term`（`Estimated model cost`），并附一句
  "由配置的每百万 Token 单价推算，不是供应商账单/发票"。
- 计数与 Token **按精确整数显示**（千分位），不做 "42.1M" 之类会隐藏精度的缩写。
- 当前 live 栈为 0 PRICED / 75 UNPRICED，因此 live 上所有成本位都会显示 "Not available" —— 这是预期行为。

## 7. 通知铃铛外壳（Global Nav）

`src/layouts/components/notification-center/`：

- `index.tsx`：**NotificationCenter** = 铃铛图标 + 未读数字徽标 + 右侧抽屉（`Sheet`）。
  徽标在 0 时隐藏，符合文档化的三种状态（无未读 / 数字）；铃铛**始终渲染**（只在有未读时出现就永远无法被发现）。
- `notification-store.ts`：Zustand 会话内状态（`items` + `readAtById`），支持 `markRead` / `markAllRead` /
  `syncSource`。**不持久化**（无 localStorage），关闭标签页即清空。
- `src/interfaces/notification.ts`：类型化模型（category / severity / titleKey / params / createdAt? / readAt /
  route / source）。U7 的分类已声明，但**只有拥有真实后端来源的分类才会生成条目**。
- **唯一真实来源**：`GET /tenants` 上未应答的工作区邀请（`role === 'invite'`），即此前 header 已用它给铃铛加点的同一事实。
  它在 `useInvitationNotifications` 中投影为一条通知；`syncSource` 会**替换**该来源的条目，邀请被处理掉后通知随之消失、
  徽标归零。**没有构造任何其他事件**：用量阈值、供应商健康、检索健康在各自后端事实源就绪（U5–U7）前**不产生条目**，
  而不是先放占位通知。
- **不伪造时间**：`createdAt` 只在来源确实提供时设置（邀请行的 `update_date`）；取不到就不显示相对时间，
  不会替换成"just now"。
- 抽屉空状态说明"运维通知将在后端事实源就绪后出现"，并说明**仅站内**、不发邮件/短信/webhook。
- `bell-button.tsx` **已删除**（原先只是一个跳到 Team 的链接 + 一个静态圆点），由 `NotificationCenter` 取代；
  `header.tsx` 的隐藏测量节点改为同尺寸镜像按钮，保持响应式断点计算精确而不额外挂载一个对话框根。

## 8. 文件清单

**新增**

```text
web/src/interfaces/database/workspace-usage.ts             U1 payload 类型（含 cost: number|null 语义）
web/src/interfaces/notification.ts                         通知类型模型
web/src/services/workspace-usage-service.ts                U1 的 7 个 GET 端点（registerNextServer）
web/src/hooks/use-workspace-usage-request.ts               查询钩子 + WorkspaceUsageKeys 工厂
web/src/hooks/use-model-provider-request.ts                既有 /models 端点（凭据无关字段）
web/src/constants/model-provider-endpoint.ts               Managed/Private 分类 + 能力标签顺序
web/src/layouts/components/notification-center/index.tsx          铃铛 + 徽标 + 抽屉
web/src/layouts/components/notification-center/notification-store.ts 会话内通知状态
web/src/pages/user-setting/usage-operations/index.tsx              4 tab 外壳 + 角色门禁
web/src/pages/user-setting/usage-operations/my-usage.tsx
web/src/pages/user-setting/usage-operations/workspace-analytics.tsx
web/src/pages/user-setting/usage-operations/provider-health.tsx
web/src/pages/user-setting/usage-operations/retrieval-health.tsx
web/src/pages/user-setting/usage-operations/components/usage-format.ts        成本/计数/区间（诚实性核心）
web/src/pages/user-setting/usage-operations/components/usage-metric.tsx
web/src/pages/user-setting/usage-operations/components/usage-tables.tsx
web/src/pages/user-setting/usage-operations/components/limit-standing-list.tsx
web/src/pages/user-setting/usage-operations/components/coming-data-panel.tsx
web/src/pages/user-setting/usage-operations/components/usage-range-filter.tsx
web/src/pages/user-setting/setting-model/model-provider-overview.tsx
web/src/pages/user-setting/setting-team/usage-policy.tsx
web/src/pages/user-setting/usage-operations/components/usage-format.test.ts
web/src/layouts/components/notification-center/notification-store.test.ts
web/src/constants/model-provider-endpoint.test.ts
docs/key-usage/workspace-ai-usage-provider-reliability-u2.md               本文件
```

**修改**

```text
web/src/routes.tsx                       新增 Routes.Usage 与 /user-setting/usage 路由
web/src/pages/user-setting/index.tsx     面包屑标签
web/src/pages/user-setting/sidebar/index.tsx  rail 新增 Usage & operations 入口
web/src/pages/user-setting/setting-model/index.tsx  追加 ModelProviderOverview（只读区块）
web/src/pages/user-setting/setting-team/index.tsx   追加 UsagePolicySection（只读区块）
web/src/layouts/components/header.tsx    铃铛始终渲染，改由 NotificationCenter 承担
web/src/locales/en.ts / zh.ts            新增 usage.* / notification.* / setting.* 键（各 +126 行，纯追加；见 §9.2）
docs/key-usage/ROADMAP.md                U2 状态行
AGENTS.md                                U2 里程碑
```

**删除**

```text
web/src/layouts/components/bell-button.tsx   被 NotificationCenter 取代
```

## 9. 验证

| 检查                | 命令                                            | 结果                                                                 |
|---------------------|-------------------------------------------------|----------------------------------------------------------------------|
| 前端单元测试        | `npx jest --no-cache <新测试目录>`               | **3 suites / 23 tests 全部通过**                                      |
| 类型检查（新增文件） | `npm run type-check`                            | **新增/改动文件 0 error**                                             |
| 类型检查（整仓基线） | 同上                                            | 203 个 error **全部为既有**（`src/components/**`、`src/pages/agent/**` 等），本轮未新增任何一条 |
| Lint                | `npx oxlint <新文件>`                            | **0 error / 0 warning**                                               |
| 中英文 locale 校验   | 见 §9.2                                         | **en/zh 键完全对齐；无未翻译条目；105 个被引用键两侧均存在**            |
| 生产构建            | `npm run build`                                 | **成功**（见 §9.1）                                                    |

### 9.1 构建与浏览器验收

`npm run build` 在本轮最终状态上通过（仅剩构建前就存在的 chunk 体积提示，非本轮引入）。

**未做真实浏览器验收**：ROADMAP 的 U2 停止条件是 "Browser/UI gates only"，而真实浏览器验收需要登录态与被测 stack 上的
NORMAL/OWNER 双角色数据，属于需要单独授权的运行态操作（U0.6 已记录 live 上不存在 NORMAL 成员的计量行，
且唯一被计量组合满足 `tenant_id == user_id`）。因此本轮**不声称**浏览器已验证，只声称：
类型检查、lint、单测、locale 校验、构建通过。

### 9.2 中英文 locale 同步校验（`web/src/locales/{en,zh}.ts`）

按 `web/CLAUDE.md` 只改 `en.ts` 与 `zh.ts` 两个文件（均 +126 行，纯追加、零删除）。校验脚本做三件事：

1. **键对齐**：`usage` 块 en=101 / zh=101，`notification` 块 en=12 / zh=12，新增 `setting.*` 9 个键两侧齐全；
2. **无未翻译条目**：逐一比对 zh 与 en 的值，**没有任何一条 zh 值与 en 相同**（即不存在漏译）；
3. **引用完整性**：扫描本轮所有 U2 源文件里的 `t('usage.*'|'notification.*'|'setting.*')` 字面量，
   加上组件中动态拼装的键（限额维度标签、供应商分组标签、能力标签、角色标签），共 **105 个键**，
   在 **en 与 zh 中均存在**。

该校验在本轮抓到一个真实缺口：`limit-standing-list.tsx` 引用了 `usage.limitNotEnforcedPositive`，
而两个 locale 文件里都没有该键（组件会渲染出原始 key）。修法不是补一个冗余键，而是让两条分支共用同一个
`usage.limitNotEnforced`（两种情况下语义都是"未启用"），并把"哪些维度的 0 表示未启用"改为**在限额列表下统一说明一次**
（新增 `usage.zeroMeansNotEnforcedNote`，中英文同步），比逐行重复更准确。

## 10. 明确未做（留给 U3+）

- 未改任何后端代码、路由、schema、迁移、定价配置。
- 未实现 Provider Health 后端事实、未实现任何余额/额度查询 adapter。
- 未实现通知的持久化、阈值、去重、邮件/webhook（U7）。
- 未新增 Usage Policy 的编辑控件（U3 的 Usage Policy 暴露既有后端控件）。
- 未做 CSV 导出、未做图表库引入（日/月以表格呈现，避免为了"看起来像仪表盘"而引入未验证的可视化）。
- 未修复任何 U0 缺陷（特殊任务归因、OCR 绕过、结算缺口、身份域错误等仍为 backlog）。

## 11. 停止点

U2 骨架与 U1 接入完成并通过类型检查 / lint / 单测 / 构建。**U3 未开始，等待明确授权。**
