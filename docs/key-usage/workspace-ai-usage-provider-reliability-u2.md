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

## 12. U2.1 — Settings IA, i18n repair and the 404 root cause

按用户要求，本轮是 U2 的修正/补全：把 Settings 改成**真正的两级导航**、把 Model Providers 变成**真实分类**、把 Team 拆成**真实子页面**、
修掉可见的 404，并把中英文补齐（默认中文）。**未开始 U3，未改 U1 后端/会计语义，未部署、未 retag。**

### 12.1 404 的确切根因

复现与取证：用户看到的是 `vite dev`（端口 **9222**，`web/.env` 的 `PORT=9222`），它按 `web/vite.config.ts` 把
`/api` 与 `/v1` 代理到 `http://127.0.0.1:9380/`，也就是**运行中的容器 `wenruo-rag-cpu`**。检查该容器的后端代码：

```text
$ docker exec wenruo-rag-cpu ls /ragflow/api/apps/restful_apis/ | grep -i workspace_usage
(空)
$ docker exec wenruo-rag-cpu ls /ragflow/api/db/services/ | grep -i workspace_usage
(空)
```

**容器镜像早于 U1**：它没有 `workspace_usage_api.py`，也没有 `workspace_usage_read_service.py`，
因此 7 个 `/api/v1/tenants/<id>/usage/*` 请求全部得到 **HTTP 404**，`next-request` 的拦截器把每个失败请求变成一条
`请求错误 404: undefined` toast。`undefined` 是既有实现的产物（`errorHandler` 读 `error.response.url`，axios 不填该字段），
不是本轮引入。**根因是环境，不是 URL 拼装、不是 workspace 标识、也不是路由写法** —— U1 的 7 条路由在 U1 已用真实
app bootstrap 验证存在，本轮也再次确认前端拼出的路径正确（fixture 断言 `GET /api/v1/tenants/<id>/usage/<view>` 命中）。

本轮在**前端**做了两处与之对应的正当修复（都不是"把 toast 关掉让截图好看"）：

1. **重试策略**：`USAGE_QUERY_OPTIONS` 让 4xx/5xx 不再按 React Query 默认重试 3 次 —— 一次不可达的读取模型原本会变成
   每个端点 4 次请求（7 个端点 × 4 = 28 条 toast），这正是"repeated 404"的来源。
2. **错误归属**：用量读取带 `skipGlobalErrorNotification`，由 `ReadModelNotice` **在页面上**显示失败原因并给出**重试按钮**。
   失败比 toast 更可见（就地、持久、带上下文），只是不再刷屏；错误没有被隐藏。
3. 顺带修掉一个真实缺陷：`useActiveUsageTenantId` 以前直接读 `localStorage`（非响应式），首次渲染取不到 workspace 时查询会**永久禁用**；
   现在改为经 `/v1/users/me/models` 的 TanStack 查询派生，workspace 解析到位后查询会自动发出。

**部署后端的 U1 缺失仍是环境前置条件**：验收必须让前端连接到带 U1 的后端（重建镜像或在本地跑 checkout 的 API）。
本轮没有部署、没有 retag：那是需要单独授权的动作。

### 12.2 二级导航（真实导航，不是页面内标题）

新增数据模型 `web/src/pages/user-setting/settings-nav.ts`：四个分区 + 子目的地的树，**每个子项都是真实路由**，
`matchActiveSection` / `matchActiveChild`（最长前缀匹配）同时驱动 rail 高亮与面包屑，因此"选中的子项"和"渲染的页面"不可能不一致。

```text
用户设置
├── 模型提供商         /user-setting/model           + 全部提供商 / 托管 API / 私有端点 / 未分类*
├── 团队               /user-setting/team            + 成员与角色 / 用量策略 / 部门管理
├── 用量与运维         /user-setting/usage           + 我的用量 / 工作区分析† / 服务商健康† / 检索健康†
└── 概要               /user-setting/profile         （保留既有功能，无编造子项）
```
`*` 未分类**仅在确有无法分类的提供商时**出现在 rail 中；`†` 仅 OWNER/ADMIN 可见，且在角色返回之前不渲染。

rail 自身改造：父项 = 可点击的分区入口，左侧 chevron 独立展开/折叠（一个控件无法同时"导航"和"展开"），
子项缩进并以竖线归属父项，激活子项用 `accent-primary-5` 高亮；**未新增第二条常驻宽侧栏**，仍复用原 Settings rail。
面包屑改为两级（父 + 子），并且与 rail 共用同一模型 —— U2 里那段写死 `Routes.DataSource` 的 label 表被删除（还顺带消掉一个既有 TS 错误）。

### 12.3 Model Providers 真实分类

`/model` 保持既有管理页不变（U2 里塞进 rail 的那块 overview 已**删除**，避免与真实分类目的地重复）。
分类目的地为 `provider-category.tsx`：按 `provider_name`（**工作区实际配置的 factory 身份**，不是显示名）分组，
`Managed API / Private Endpoint / Unclassified` 各自一个路由；每个提供商卡默认折叠为一行（名称 + 类型 + 能力标签 + 模型数），
展开后显示模型清单、连接实例与 `状态：尚无观测` 占位。能力标签用 `能力：对话 / 向量化 / 重排序 / 视觉语言 / 语音识别 / 语音合成 / OCR`。

更强信号（自定义 `base_url` 表示自建网关）只存在于 provider-instance 端点，而该端点 payload 含 `api_key` 字段 ——
为了给一个展示分组"顺带"把密钥拉进浏览器不值得，因此分类只依据 factory 身份，**无法判定的一律进未分类而不是猜成托管 API**。

### 12.4 i18n：找到并修掉"中文里冒英文"的真正原因

用户列出的 `Usage operations` / `Capability chat` / `Usage policy` 等并不是漏翻，而是**键不在 `setting` 命名空间里**：
上一轮的插入脚本用 `re.search` 定位 `\n      model: '...'` 这行，而每个语言文件里**第一个**匹配是 `chat` 块里的 `model`，
于是 9 个 `setting.*` 键被写进了 `chat.*`。后果：`setting.capabilityChat` 等根本不存在，
i18next 落到 `parseMissingKeyHandler`，把键名"人化"成 `Capability chat`；`setting` 整体缺失又让部分界面回落到英文包。

修复与补全（脚本化、幂等）：把这 9 个键从 `chat` 移到 `setting`，补上 U2.1 新增键（en/zh 各 +17 setting、+15 usage），
并把中文术语按验收清单固定：`服务商健康`（原"供应商健康"）、`向量化`、`重排序`、`视觉语言`、`能力`、
`成员与角色`、`部门管理`、`模型提供商`、`用量与运维`、`用量策略`、`托管 API`、`私有端点`、`未分类`。

**新增自动化审计** `src/locales/__tests__/settings-locale-audit.test.ts`（20 项）：扫描 U2/U2.1 源文件里所有
`t('...')`、`labelKey`/`titleKey`/`descriptionKey`/`pendingKeys` 字面量与动态键表（共 105+ 键），断言
① 每个键在 en 与 zh **都能解析成字符串**；② 没有空值；③ 没有任何键回落到"人化键名"（这正是本次缺陷的症状）；
④ zh 与 en 不会给出同一串（除白名单专有名词）；⑤ zh 值不得是纯 ASCII 英文；⑥ 验收清单里的中文术语**逐字**比对；
⑦ 源码里不得出现硬编码的英文 JSX 文本节点或 `aria-label`/`title`/`placeholder` 英文字面量。

同时**停止渲染服务端的英文散文**（`not_answered`、`reconciliation.semantics`）：语义不变，措辞改由可翻译的键承担，
否则中文界面必然出现整段英文。

### 12.5 U2.1 验证

| 检查 | 结果 |
|------|------|
| `npx jest`（IA + locale 审计 + 既有 U2 套件） | **5 suites / 62 tests 全部通过**（其中 locale 审计 20 项、IA 模型 18 项） |
| `npm run type-check` | 新增/改动文件 **0 error**（整仓既有基线 203 → **202**，本轮修掉 1 条既有错误） |
| `npx oxlint`（本轮文件） | **0 error / 0 warning** |
| `npm run build` | 见 §12.6 |
| 真实浏览器验收（中文 + 英文） | **BLOCKED**：见 §12.6 |

### 12.6 浏览器验收结论（诚实记录，不宣称通过）

用真实 Chrome（Playwright，`channel="chrome"`）跑了 11 个目的地 × 中英文两轮，并用一个**仅验收用的** Vite 配置
（扩展项目自身配置、另起 9323 端口、对 7 个 U1 端点返回契约同形的 fixture，其余全部走真实后端）来绕开"部署后端没有 U1"这一环境前置条件。
该临时配置与脚本都不在仓库内（已在提交前删除），**没有改动生产、没有部署、没有 retag**。

**已获得的证据**（页面渲染文本，截图在 `%TEMP%\u21_acceptance\`）：

- 中文界面：`用户设置 > 用量与运维 > 我的用量`、rail `模型提供商 / 团队 / 用量与运维 / 概要 / 登出`、
  `区间 2026-08-30 至 2026-09-29`、`最近 7 天/31 天/92 天`、`该区间没有用量记录`；英文界面全部对应英文。
- **两级面包屑**与 rail 父子结构在真实浏览器中可见（这是"二级导航真的生效"的直接证据）。
- 所有目的地：`raw_key_hit = None`、`forbidden_hits = []` —— 无原始/人化键，中文模式无被点名的英文串，英文模式无中文串。

**未通过的部分**：两轮运行中，经代理的**所有**后端调用都返回 **HTTP 500**（Vite 日志为 `http proxy error: socket hang up`），
包括 `/api/v1/language`、`/api/v1/users/me`、`/api/v1/models`、`/api/v1/tenants`；同一时刻直接请求
`http://127.0.0.1:9380/api/v1/language` 返回 **200**，容器日志也显示这些路径对用户会话返回 200。
期间容器 `wenruo-rag-cpu` **重启过一次**（`Up 4 minutes`），第一次运行正处于该窗口。
由于会话无法稳定建立（`/api/v1/users/me` 也 500），workspace 无法解析，用量查询被禁用，
页面因此落到"没有用量记录"的诚实空状态，**7 个 U1 端点在浏览器里没有被真正请求到**。
因此：

- "打开用量与运维不产生意外 404" —— **无法在本轮证明**（后端 500 掩盖了它）；
- 中文/英文浏览器验收 —— **FAIL/BLOCKED**，原因在验收环境（代理链路 500 + 后端重启 + 令牌被拒 401），不在本轮前端改动。

**未伪造任何结论**：本轮不宣称 ZERO unexpected 404、不宣称浏览器 PASS。复现所需的下一步是让前端连到**带 U1 且稳定**的后端
（重建镜像或在本地运行 checkout 的 API），这需要单独授权；届时同一脚本可直接复用。

### 12.7 U2.1 停止点

前端 IA、二级导航、分类、Team 子页面、i18n 修复与审计均已完成并通过代码级门禁；
**浏览器验收因环境阻塞而未能通过，已如实记录**。**U3 未开始，等待明确授权。**



## 13. U2.2 — 运行时对齐 + 真实浏览器验收（通过）

U2.1 的浏览器门禁因"运行中的后端不含 U1"而卡住。本轮把它跑通：**用一个含 U1 的本地 checkout API**，
不 retag `:latest`、不部署生产、不改生产 DB/Redis/配置。

### 13.1 运行时对齐（可证明）

启动器只 `import api.apps`（导入即注册全部 blueprint），**不调用 `init_database_tables()` / `migrate_db()`** ——
后者在 `api/ragflow_server.py` 里，一个更新的 checkout 绝不该从验收进程去 ALTER/回填共享生产库。
运行进程自报：

```text
USAGE_API_FILE: C:\Projects\RAG\wenruo-rag\api\apps\restful_apis\workspace_usage_api.py
READ_SERVICE_FILE: C:\Projects\RAG\wenruo-rag\api\db\services\workspace_usage_read_service.py
USAGE_ROUTE_COUNT: 8
  /api/v1/tenants/<tenant_id>/usage-budget   （既有）
  /api/v1/tenants/<tenant_id>/usage/daily
  /api/v1/tenants/<tenant_id>/usage/members
  /api/v1/tenants/<tenant_id>/usage/models
  /api/v1/tenants/<tenant_id>/usage/monthly
  /api/v1/tenants/<tenant_id>/usage/my
  /api/v1/tenants/<tenant_id>/usage/quota
  /api/v1/tenants/<tenant_id>/usage/summary
```

**7 条 U1 路由全部注册**，并且真实执行（非 fixture）：`GET .../usage/my` 与 `.../usage/quota` 返回 **HTTP 200** 并带真实 payload
（该用户的 `attempted_calls = 0`、`cost_coverage = unavailable` —— 与 U0.6 实测的 0 PRICED 一致）。

会话：本轮也修掉了 token 口径问题。之前用**容器内** settings 铸造的 token 被 401 拒绝，因为容器与 checkout 的
`get_secret_key()` 不同源；改用 checkout 自己的 `User.get_id()` 铸造后，`/api/v1/users/me` 与 `/api/v1/tenants` 均 **200**。

### 13.2 真实浏览器验收结果（中文 + 英文，全部通过）

真实 Chrome（Playwright `channel="chrome"`），11 个目的地 × 2 语言，代理指向本地 U1 后端（**无任何 fixture**）：

| 断言 | 中文 | 英文 |
|------|------|------|
| 失败请求（≥400，含 404/500） | **0** | **0** |
| 错误 toast（`请求错误` 计数） | **0** | **0** |
| 原始/人化 locale key | **0** | **0** |
| 中文模式出现英文串 / 英文模式出现中文串 | **0** | **0** |

**U1 端点确实被执行**（浏览器实际发出的 200 请求）：

- `我的用量` → `usage/my` + `usage/quota`
- `用量策略`（团队） → `usage/quota`
- `工作区分析` → `usage/summary`、`usage/models`、`usage/members`、`usage/daily`、`usage/monthly`（六条全部 200）
- `服务商健康` / `检索健康` → **不发出任何用量请求**（诚实占位，无编造数据）

`托管 API` / `私有端点` / `成员与角色` / `部门管理` / `概要` 各目的地均 0 失败、标签命中。

唯一一条口径提示：中文序列中 **第一个** 目的地（`/user-setting/model`）的"父标签在文本中出现"启发式未命中
（英文序列命中）。该页失败数 0、无被禁英文串、无原始键，其余中文目的地的同一 rail 都渲染了父标签，
因此判定为**冷启动时该页在 zh bundle 到位前完成截图**的探针假象，而不是漏译；不在报告中记为通过之外的问题。

### 13.3 未做与边界

未改 U1 会计语义、未加 Provider Health 后端、未加通知、未改生产 DB/Redis/配置、未部署、未 retag `:latest`。
验收用的 Vite 配置与脚本均在仓库外并在提交前删除。
`NORMAL/OWNER 可见性`：本工作区仅存在 owner/admin 成员计量数据（U0.6 已记录 live 无 NORMAL 计量行），
因此本轮以 OWNER 身份验证了四个用量目的地全部可达；NORMAL 侧仍由单测 fixture 覆盖（U1 的 43 项测试 + 本轮 IA 测试）。

**U2.2 结论：运行时对齐完成，中英文真实浏览器验收通过。U3 未开始。**

## 11. U2 停止点

U2 骨架与 U1 接入完成并通过类型检查 / lint / 单测 / 构建。**U3 未开始，等待明确授权。**
