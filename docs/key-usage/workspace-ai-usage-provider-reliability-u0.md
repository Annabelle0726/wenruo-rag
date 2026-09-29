# Workspace AI Usage & Provider Reliability — U0

审计日期：2026-09-29。范围：Current-State Discovery & Architecture Freeze Proposal。

本报告基于 checkout `138a1a79a67864e1361f3e2cbb70315b97770ffb` 的实际源码、ORM、路由及既有测试源码。工作树已有
`rag/retrieval/rerank.py` 修改和大量部署审计产物，本轮没有修改这些内容。`CLAUDE.md` 内容仅为 `AGENTS.md`；已核对后者。Python
是本工作流唯一支持路径；启动脚本仍有 Go/hybrid 分支，不代表本轮重新启用它们。

**证据限制：本轮没有连接生产 SQL/Redis、读取线上配置行或日志，也没有调用 provider。以下是源码事实，不是新的生产运行认证。**
线上模型定价清单、实际表/索引漂移、部署版本及日志保留时间仍未知。不能用 AGENTS 中历史部署结论填补这些空白。

## 1. Current Architecture Map

```text
认证调用者 -> execution_user（与 tracing user_id 分离）
  -> 资源的 authoritative workspace + 当前 membership/access
  -> TenantModelProvider(workspace)
       -> TenantModelInstance(credential)
            -> TenantModel(extra pricing)
  -> resolve_model_config -> LLMBundle
       -> @budgeted（必须同时有 actor 和 tenant）
            -> SQL membership + per-member day/month counters
            -> Redis rolling minute（NORMAL）
            -> SQL reservation/ledger -> provider dispatch
            -> usage report -> settlement；无报告保留预留

queue_tasks / queue_dataflow -> Task.initiator_user_id
  -> TaskService.get_task 关联 document/knowledgebase 得到 workspace
  -> task_executor.handle_task -> enter_detached_job
  -> LLMBundle；每次受保护 dispatch 重新验证 membership

Provider 异常 -> SDK/wrapper 分类、日志、部分 API 错误 envelope
Retrieval 执行点 -> health_bridge / HealthSession -> P0 health + P0-7 九字段日志
```

冻结三个域，互不替代：

| 域                                  | 回答                              | 当前事实源                                                        | 不允许推断                                               |
|-------------------------------------|-----------------------------------|-------------------------------------------------------------------|----------------------------------------------------------|
| Workspace Budget / Usage Governance | 是否允许该成员在此 workspace 花费 | membership、WorkspaceBudget、WorkspaceUsage、ledger、Redis minute | 余额充足不等于 provider 可用                             |
| Provider Availability / Health      | 上游是否成功服务该次请求          | dispatch 返回/异常、SDK 状态、已有日志                            | ledger settled/unsettled 不是 provider healthy/unhealthy |
| Retrieval Health                    | 本次检索各腿实际发生了什么        | 现有 P0 producer/contract                                         | 检索降级不等于整个 provider 不可用                       |

`WORKSPACE_QUOTA_EXHAUSTED` 与 `UPSTREAM_PROVIDER_QUOTA_EXHAUSTED` 在本报告只是领域名称，不是新增枚举。现有内部拒绝是
WorkspaceAccessDenied；上游有 EMBEDDING_QUOTA_EXHAUSTED / EMBEDDING_RATE_LIMITED 等独立错误来源。本轮不新增 taxonomy。

## 2. Workspace Budget 核实

核心证据：[schema](C:/Projects/RAG/wenruo-rag/api/db/db_models.py:1699)、[budget service](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:183)、[dispatch boundary](C:/Projects/RAG/wenruo-rag/common/model_budget.py:185)。

| 核查项             | 源码结论及边界                                                                                                                                                                |
|--------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 默认 limits        | NORMAL：20/rolling 60s；1,000/day；20,000/month；200,000 tokens/day；4,000,000/month；cost day/month 默认 0                                                                   |
| 限额作用域         | WorkspaceBudget 保存 workspace 的统一规则，实际额度按 `(tenant_id,user_id,period)` 独立核算；不是 workspace 总量共享硬帽                                                      |
| 单位               | calls 是受计量 dispatch attempts；tokens 是总 token；cost_micros 是整数 micro-USD；token/cost=0 不执行该维度限制，calls 下限 1                                                |
| 预留               | SQL transaction 先锁 Tenant（self-update）、查 live membership、检查两种 period，再执行 minute Lua、增加 counter、创建 reserved ledger；成功后才 dispatch                     |
| Redis              | TIME + ZSET + Lua 原子滚动窗；按 workspace/member 共用，TTL 60s。丢 Redis 不丢 SQL day/month 使用量，但会丢 minute 历史；没有查到从 ledger 恢复滚动窗的实现                   |
| attempt 边界       | 预算拒绝前没有 ledger attempt；provider 失败/取消但已预留的 attempt 不退 calls。包装器调用不保证与每一次 SDK 内部 HTTP 重试一一对应                                           |
| 结算               | reservation ID 锁定，只有 reserved 能 settle；重复 settle no-op；两期 counter 同步减去未使用预留，或超预留向上补记                                                            |
| 无 usage / timeout | release_dispatch 只改为 unsettled，不清空预留；随后不能再 settle。这不是“实际用量为零”                                                                                        |
| 零 usage           | 当前 close 依据 token 数是否非零判断；即使报告了 0，也走 unsettled，reported_rounds 没用于区分“报告零”和“没报告”                                                              |
| 故障               | reserve SQL/Redis 非业务异常转换为受控 WorkspaceAccessDenied；不 dispatch。settlement 写失败只记录 warning，已有预留留存；不是所有后台路径都获得相同保证                      |
| 管理员             | OWNER/ADMIN 免 minute、call、token、cost 限制，但仍查 live membership，仍写 counters/ledger；SQL 故障不豁免。管理员路径不访问 minute Redis，故单独 Redis 故障不一定拒绝管理员 |
| timezone           | current_periods 按 workspace zone 产生日期/月字符串；默认 UTC；无效存量 zone 警告后按 UTC 算；写入校验。修改 timezone 不重算历史；历史 period 的 timezone 应保留解释          |
| detached           | 有 initiator 时查当前 membership；已移除则拒绝。无 initiator 回退当前 active owner；无 workspace 或无 owner 则 warning + unmetered，属于明确兼容政策                          |
| 持续撤权           | 受计量的下一次 dispatch 再查成员身份；不是取消已经发往 provider 的网络请求；直接绕过 bundle 的调用另见覆盖表                                                                  |
| 幂等局限           | 同一个 reservation 的结算幂等；同一业务请求重试仍会创建新的 UUID reservation，并非跨请求 exactly-once                                                                         |

SQL counter 是当前 enforcement 读取源；ledger 是可用于对账的逐调用事实。没有查到自动 counter
重建/对账任务。不能将模型注释“reconciliation source”写成已部署 reconciliation 功能。counter 行被删时 settle
跳过该行，既有测试明确接受此行为。

### 当前 GET/PUT contract

[tenant_api.usage_budget](C:/Projects/RAG/wenruo-rag/api/apps/restful_apis/tenant_api.py:358) ->
configure_budget。login_required 后，service 在事务内验证路径 tenant 的 active OWNER/ADMIN；该路由没有
`@require_tenant_admin`，实际权限边界在 service，不能写成没有权限控制。

GET 返回全部七个数值
limits、timezone、unit=model_calls、token_unit=tokens、cost_unit=micro_usd、applies_to=normal、zero_means_unlimited，以及 used
中 day/month/current period/member 聚合。PUT 接受非空字段子集；仅整数（bool 不接受），calls 1..10^10，token/cost
0..10^10；拒绝未知字段，timezone 可单独修改，null 被规范为 UTC。成功更新写 WorkspaceAudit (action=update_budget)。

**GET 也先 self-update Tenant 用于锁定，因此不是数据库层面的纯只读操作。** 本轮没有调用它。使用量 day 和 month
不能相加，否则双计。该接口是当前期 snapshot，尚无历史分页/模型/provider 聚合 API。

WorkspaceAccessDenied -> server_error_response -> get_error_permission_result -> HTTP 200、code=108；流式由
workspace_execution guard 携带拒绝。上游模型错误当前可返回业务 code=429，不能与内部 budget 拒绝混用。后续前端 request
payload 必须 `{data: body}`。

## 3. 实际持久化结构与 Existing Fact Sources

以下各表 SOURCE 都是 [db_models.py](C:/Projects/RAG/wenruo-rag/api/db/db_models.py:264)，行号附在表名后。所有
DataBaseModel 继承 **create_time/create_date/update_time/update_date（均有索引）**；下表 TIME/INDEXES 默认包含这四列。`—`
表示没有该用途的字段，不等于金额/用量为零。INDEXES 是 ORM 声明，未认证线上 DDL。

| SOURCE / PURPOSE                                                                  | PRIMARY KEY                   | WORKSPACE/TENANT KEY                                                     | USER ATTRIBUTION                                | MODEL / PROVIDER ATTRIBUTION                                     | TOKEN / COST FIELDS                                                                                        | TIME / STATUS FIELDS                                                   | INDEXES（另加共同时间索引）                                                                                     | RETENTION                                                   |
|-----------------------------------------------------------------------------------|-------------------------------|--------------------------------------------------------------------------|-------------------------------------------------|------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------|
| WorkspaceBudget:1699 / workspace_budget；规则                                     | tenant_id                     | tenant_id                                                                | 规则适用 NORMAL，无具体 user                    | — / —                                                            | tokens_per_day/month；cost_micros_per_day/month；calls limits                                              | 共同时间；timezone；无 status                                          | PK                                                                                                              | 未见 TTL/清理政策                                           |
| WorkspaceUsage:1723 / workspace_usage；durable counters                           | id=SHA256(tenant:user:period) | tenant_id                                                                | user_id                                         | — / —                                                            | calls,prompt_tokens,completion_tokens,tokens,cost_micros                                                   | period；共同时间；无 status                                            | PK,tenant_id,user_id；period 无独立索引                                                                         | 未见 TTL/清理政策                                           |
| WorkspaceUsageLedger:1747 / workspace_usage_ledger；reservation+settlement 同一行 | id=reservation UUID           | tenant_id                                                                | user_id                                         | model_name,call_kind / 无 provider或instance ID                  | reserved_tokens,reserved_cost_micros；prompt_tokens,completion_tokens,tokens,cost_micros；每行一个 attempt | period_day/month,timezone,settled_at；reserved/settled/unsettled       | PK,tenant_id,user_id,status；model/period 无索引                                                                | 未见 TTL/清理政策                                           |
| WorkspaceAudit:1780 / workspace_audit；管理审计                                   | id                            | tenant_id                                                                | operator_id                                     | — / —                                                            | details 可含配置的 limit；不是 spend                                                                       | 共同时间；action,details                                               | PK,tenant_id                                                                                                    | 未见 TTL/清理政策                                           |
| Task:1535 / task；队列持久化                                                      | id                            | 无直接 tenant；get_task 经 Document→Knowledgebase join；特殊任务形状另论 | initiator_user_id，可空；不等于 tracing user_id | 无可靠 model/instance 外键                                       | — / —                                                                                                      | begin_at,process_duration；task_type,progress,progress_msg,retry_count | PK,doc_id,begin_at,progress,initiator_user_id                                                                   | queue_tasks/queue_dataflow 可删除旧任务；不是不可变财务历史 |
| TenantModelProvider:2049 / tenant_model_provider；workspace provider              | id                            | tenant_id                                                                | —                                               | provider_name                                                    | — / —                                                                                                      | 共同时间；无健康 status                                                | PK,tenant_id,unique(tenant_id,provider_name)                                                                    | 配置生命周期，无健康历史保留                                |
| TenantModelInstance:2059 / tenant_model_instance；credential instance             | id                            | 经 provider_id                                                           | —                                               | provider_id,instance_name；api_key；extra                        | — / —                                                                                                      | status=active 等配置状态；无 last success/failure                      | PK；provider_id 未声明索引                                                                                      | 配置更新/删除，无 key version 历史                          |
| TenantModel:2071 / tenant_model；执行模型                                         | id                            | 经 provider_id                                                           | —                                               | model_name,provider_id,instance_id                               | extra JSON 字符串含 price_input_per_million/output；无 usage counter                                       | status；model_type bitmask；共同时间                                   | PK,instance_id,model_type                                                                                       | 配置生命周期，定价无版本历史                                |
| LLMFactories:1267 / llm_factories；厂商目录                                       | name                          | 全局目录                                                                 | —                                               | name                                                             | — / —                                                                                                      | status 为目录状态                                                      | PK,tags,status,rank 不索引                                                                                      | 未见 TTL                                                    |
| LLM:1281 / llm；模型目录                                                          | composite(fid,llm_name)       | 全局目录                                                                 | —                                               | fid,llm_name,model_type                                          | max_tokens 为能力，不是 usage；无定价列                                                                    | status 为配置状态                                                      | fid,llm_name,model_type,tags,status                                                                             | 未见 TTL                                                    |
| TenantLLM:1300 / tenant_llm；旧配置结构仍在 schema                                | ORM 隐式 id                   | tenant_id                                                                | —                                               | llm_factory,llm_name；api_key,api_base                           | used_tokens；max_tokens；无 cost                                                                           | status 配置状态                                                        | tenant_id,llm_factory,model_type,llm_name,max_tokens,used_tokens,status；unique(tenant_id,llm_factory,llm_name) | 未见 TTL；不作为本工作流新事实源                            |
| APIToken:1641 / api_token；应用访问凭据，不是上游 key                             | composite(tenant_id,token)    | tenant_id                                                                | 无直接 user_id                                  | dialog_id/source 指应用；无 provider instance                    | — / —                                                                                                      | 共同时间；source,beta                                                  | tenant_id,token,dialog_id,source,beta                                                                           | 凭据生命周期；不是 usage                                    |
| Tenant:workspace 配置（credit:1199）                                              | id                            | id                                                                       | 不应普遍等同 user ID                            | 默认 llm/embd/asr/tts/rerank/img2txt/ocr 名称和 tenant_model IDs | credit 旧计数；无新预算 cost 语义                                                                          | status；共同时间                                                       | 各默认模型引用及 credit/status 的声明索引                                                                       | workspace 生命周期                                          |

补充相邻事实结构（不能当成 ledger）：Knowledgebase.token_num（1353）和 Document.token_num（1438）是资产/解析统计；主键
id、tenant_id（KB）或 kb_id（Document），没有 per-dispatch provider/key、成本和成员归因。API4Conversation（1649，隐式 id）有
dialog_id,user_id,exp_user_id,tokens,duration,round,errors,reference；workspace 需从 dialog 解析，user
字段不自动等于认证成员；无成本/密钥归因。PipelineOperationLog（1880，id）有
tenant_id,kb_id,document_id,pipeline_id,task_type,operation_status,process_begin_at/process_duration/progress_msg，无
token/cost/key，不能与无 task_id 的 ledger 精确 join。它们均继承共同时间列；ORM 给 KB/Document 引用和
token_num、API4Conversation 的 dialog/user/duration、pipeline tenant/kb/document/status
等建索引，但没有财务保留保证。TenantLangfuse（1320，tenant_id PK）是 trace 服务连接凭据；其 secret/public key 不是 model API
key，trace 外部保留政策未知。

Redis rolling ZSET 是临时状态而非 durable ledger；无成本/模型字段，保留 60s。没有独立 reservation 表；reservation 和
settlement 都在 workspace_usage_ledger 同一行。

### ledger 是否够聚合

| 维度         | 当前可用性                                                               | 缺什么                                                                                                 |
|--------------|--------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| member       | 可按历史 user_id 精确聚合已计量 attempts/占用；即使成员被移除也保留      | 缺专门历史 query/read API；姓名是可变维表，不应用内连接丢历史                                          |
| model        | 普通 bundle 行可按裸 model_name；不等于具体配置模型                      | provider 同名模型会混合；charge_provider_call 的额外行 model_name/call_kind 为空；配置 ID 在入账前丢失 |
| provider     | 不可可靠历史归因                                                         | 数据未记录；用当前配置反查裸名称有歧义、改名/删除漂移                                                  |
| workload     | call_kind 仅 model_type（chat/embedding…），不是 parsing/chat/agent/task | 缺 workload/task/request/parent-dispatch 关联；不能靠时间窗口猜                                        |
| day/month    | 可按保存的 period 和 timezone 聚合；同一行只有一次 attempt               | 缺 read API；历史改 timezone 的同名日期要说明；不得把两种 counter 加总                                 |
| key instance | 不可                                                                     | 未记录 instance ID/key version，不能从裸模型名恢复                                                     |

read model 必须区分：settled 的 tokens/cost 为已结算值；reserved/unsettled 的有效预算占用取
reserved_tokens/reserved_cost_micros，不能读默认零值列导致低报。calls 计行数；status 不是 provider outcome。每日/月度
snapshot 是包含未结算预留的预算占用，不应标成纯 provider-reported usage。reserved 也不一定仍在运行：进程崩溃可能留下孤立预留。

## 4. Model Cost 语义

[pricing 来源](C:/Projects/RAG/wenruo-rag/api/db/joint_services/tenant_model_service.py:243)：TenantModel.extra 的
price_input_per_million / price_output_per_million，经 `_model_pricing` 放入
model_config.pricing。模型目录没有自动价格来源；检索到的配置代码未提供 provider invoice reconciliation。

哪些模型有定价： **只有实际 extra 包含这些字段且能解析的配置实例**；无字段模型没有成本维度。源码配置中没有可用的线上逐模型定价名录。本轮未查生产表，因此不能声称
Gemini/OpenAI/SiliconFlow 的某个线上模型已定价；上线前需要不含 api_key 的白名单字段查询得到“有价/无价/无效价”清单。Builtin
shortcut 不附带 pricing。

计算路径：[model_budget](C:/Projects/RAG/wenruo-rag/common/model_budget.py:98)：USD/million tokens 数值上等于
micro-USD/token；`round(prompt*price_in + completion*price_out)` 再转整数。无汇率、阶梯价、缓存折扣、音频/图片单位价、税费或账单对账。解析接受
float，没有查到此入口的 finite/nonnegative 定价校验；不得把配置价格天然视为可信价格目录。

| 调用                                                  | 当前计算/结算行为                                                                                                                                                          |
|-------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| chat                                                  | LLMBundle._report_usage 使用总数和一致的 mdl.last_usage split；按输入/输出价格结算；不一致 split 被置零                                                                    |
| embedding                                             | encode/encode_queries 将 wrapper 返回 used_tokens 全部记为 prompt；按输入价；某些 wrapper 自行估 token，所以 ledger 目前也不能区分 provider-reported 与本地估算 provenance |
| reranker                                              | similarity 有 @budgeted，used_tokens 全部作为输入；按输入价；依赖 wrapper 返回值                                                                                           |
| describe / describe_with_prompt / transcription / tts | 有 @budgeted，但读取/日志记录 used_tokens 后未调用 record_dispatch_usage；已预留，通常保持 unsettled，不能称已按返回 token 结算                                            |
| OCR/parser                                            | `rag/flow/parser/parser.py:413,486,547,593,677` 取 ocr_model.mdl 直接 parse；绕过 @budgeted。local OCR 不一定 billable，远程 OCR 成本不能声称已覆盖                        |
| agent/tool subcalls                                   | 经过 bundle 且 actor/workspace 保留的子调用计量；已插 charge_provider_call 的 retry/tool round 加 calls；工具自身外部付费 API 不在此 model ledger 自动覆盖                 |
| 无 usage                                              | 保留完整 token/cost bound，标 unsettled；不按 zero usage 自动释放                                                                                                          |

**已证明的金额精度缺口**：chat 仅有 total_tokens、无可信 split 时，_report_usage 把 prompt/completion 置零；_close_dispatch
有 pricing 时按这两个零计算成本，因而可将非零 tokens 结算为 cost=0。不能把这条路径的成本当作完整估计。

**当前不是严格 monetary hard cap**：

1. 限额是 per-member，OWNER/ADMIN 豁免；不存在整个 workspace 的硬总额帽。
2. 预留 output=min (max_tokens,8192)，不因此修改实际 provider 输出上限；总 token reservation 还受 1,000,000 cap。实际 usage
   可以超 bound 后补记，补记不再检查 cap。
3. extra retry/tool rounds 仅 reserve_call (tenant,actor)，没有额外 token/cost bound，且没有模型归因；其 usage
   期望最终在外层累计，并非每轮完整 monetary reservation。
4. 无定价、split 缺失、OCR bypass、无 actor 都会使成本覆盖不足；settlement 错误没有自动对账修复。
5. 定价字段可能变化，ledger 没保存当时价格版本/单价；保留了数值结果但不能完整复算价格依据。

冻结唯一展示术语： **Estimated model cost**。同时展示 reserved/unsettled 与 coverage；没有 Bill / Invoice / Actual provider
charge。

## 5. Detached Work Coverage Gap Matrix

状态判断针对相应入口，不将整个工作负载一概而论。Budgeted=有 actor+workspace 且经过 decorated bundle。构造 LLMBundle
本身不计费。主要依据：[task enqueue](C:/Projects/RAG/wenruo-rag/api/db/services/task_service.py:446)、[worker](C:/Projects/RAG/wenruo-rag/rag/svr/task_executor.py:1864)、[special enqueue](C:/Projects/RAG/wenruo-rag/api/db/services/document_service.py:1249)、[parser](C:/Projects/RAG/wenruo-rag/rag/flow/parser/parser.py:412)。

| Workload                                      | Entry Point                                           | Model Calls                      | Workspace Known?                                | Initiator Known?                                               | Budgeted?                                          | Membership Revalidated?               | Gap / 分类                                                                               |
|-----------------------------------------------|-------------------------------------------------------|----------------------------------|-------------------------------------------------|----------------------------------------------------------------|----------------------------------------------------|---------------------------------------|------------------------------------------------------------------------------------------|
| 常规 document parsing                         | queue_tasks→get_task→handle_task→refactored handler   | embedding/chat/vision            | document→KB                                     | 新请求保存 authenticated actor                                 | bundle 是                                          | enter+每次 reserve                    | PARTIALLY_COVERED：主路径有归因；OCR/部分结算另列                                        |
| parsing 中 embedding/chunk post-processing    | task_handler/chunk_post_processor/embedding_utils     | encode、keywords/questions/tags  | ctx tenant                                      | 继承 worker                                                    | 是，bundle 边界                                    | 是                                    | COVERED（不保证 SDK 每个 batch/retry 都独立 attempt）                                    |
| dataflow                                      | queue_dataflow:669→handle_task                        | flow embed/chat/vision/OCR       | 关联任务/canvas                                 | Task 保存                                                      | bundle 是                                          | 是                                    | PARTIALLY_COVERED：直接 OCR mdl bypass                                                   |
| 旧 Task / 无请求的定时同步入队                | sync_data_source→后续解析队列                         | worker model calls               | 可关联 workspace 时有                           | NULL                                                           | 按 owner 记账且豁免 limits                         | owner live membership                 | LEGACY_UNATTRIBUTED；明确策略，不自动判 bug；不等于原发起人                              |
| 无 workspace / 找不到 owner 的未知任务        | enter_detached_job                                    | 后续 bundle                      | 否/不完整                                       | 不可归因                                                       | 否                                                 | 无可检验 actor                        | UNMETERED_BY_DESIGN，源码明确 warning；保持政策                                          |
| KB-wide RAPTOR/GraphRAG/mindmap/wiki/skill 等 | dataset_api_service:655→queue_raptor_o_graphrag_tasks | chat/embedding，视任务           | collector 有按形状重读 DB 分支；原消息无 tenant | new_task 未保存 initiator                                      | 能解析 workspace 时 owner fallback；否则 unmetered | 不会 fence 原请求成员                 | BUG / ATTRIBUTION_LOST：新任务丢已知 caller；各 task_type workspace 分支覆盖仍须逐个验证 |
| per-doc RAPTOR helper                         | queue_per_doc_raptor_task:1300                        | 将来 worker chat/embed           | doc 可关联                                      | 未写 initiator                                                 | 条件同上                                           | 原成员归因丢失                        | UNKNOWN 活跃性：repo 搜索仅定义、无调用；不能当现网已触发 bug                            |
| 队列 retry / unacked re-delivery              | task_executor.collect→get_task                        | 原 task model calls              | 原路径                                          | 继承持久化 initiator                                           | 正常 Task 是                                       | 每次重新 enter/reserve                | COVERED（继承原形状缺口；重试不是免费）                                                  |
| 远程 OCR parse                                | flow parser取 ocr_model.mdl                           | parse_pdf                        | canvas tenant                                   | 可能有                                                         | 未经过预算装饰器                                   | 构造时可能查，dispatch 无 budget 再查 | PARTIALLY_COVERED；已证明 bypass，是否收费取决于 provider 配置                           |
| agent HTTP/异步子任务                         | Canvas.run / invoke                                   | bundle chat/embed/tts            | Canvas 按 canvas_id 重取 asset.tenant_id        | 已认证上下文                                                   | 通常是                                             | bundle/reserve 是                     | PARTIALLY_COVERED：Canvas executor复制 context；任意外部工具不保证                       |
| agent webhook detached                        | agent_api._webhook_impl/background_run                | Canvas model calls               | Canvas 修正为 asset workspace                   | anonymous webhook 没有 execution_user；tracing user_id不能代替 | 无 actor 路径不计量                                | 无 actor 路径不进入 reserve           | PARTIALLY_COVERED：独立安全协议，须决定服务身份，不能假定匿名发起人是成员                |
| request 内 retrieval embedding thread         | search.py:230 copy_context().run                      | encode_queries                   | bundle tenant                                   | copied context/bundle actor                                    | 是                                                 | 是                                    | COVERED；不是持久 detached job                                                           |
| FileService.parse 临时上传线程                | file_service:705/717；Canvas 文件处理                 | audio/vision/parser              | 使用 current_user.id 或传入 tenant              | 线程传播因入口不同                                             | 条件性                                             | 条件性                                | PARTIALLY_COVERED；身份域错误见下节，不笼统宣称线程都丢上下文                            |
| standalone 批处理/手工检索脚本                | tools/scripts/controlled_baseline.py:70 等            | bundle embedding                 | KB owner workspace                              | 无 execution_user 设置                                         | 否                                                 | 否                                    | LEGACY_UNATTRIBUTED；工具路径，不等于生产常驻 worker；本轮未执行                         |
| prefix backfill preview                       | tools/scripts/backfill_prefix_preview.py              | 预览文本，不是 re-embedding 实现 | corpus scope                                    | 不适用                                                         | 不适用                                             | 不适用                                | UNMETERED_BY_DESIGN（无模型调用的预览本身无需预算）                                      |
| 专用 re-embedding / migration job             | 未找到明确统一入口                                    | 取决于后续实现                   | UNKNOWN                                         | UNKNOWN                                                        | UNKNOWN                                            | UNKNOWN                               | UNKNOWN；不能把 reparse 的覆盖复制给尚未证实的后台形状                                   |
| memory task / canvas-debug 特殊消息           | collect 的 memory/fake-doc 分支                       | 依 handler                       | Task.to_dict 原表无 tenant；需具体消息验证      | 不一定                                                         | 不能保证                                           | 不能保证                              | UNKNOWN；不把未知形状全部称 bug                                                          |

没有实施后台覆盖修复，没有运行批处理、re-embedding 或 backfill。

## 6. Tenant / Workspace Isolation Audit

扫描 Python 的 `tenant_id=current_user.id`、等价的 model constructor、旧注入 decorator 及其消费者。下面的 YES
是源码链证明的域错误，不代表已实测跨租户读取成功。其余位置明确保留证据不足。

| FILE / FUNCTION                                                                                           | CURRENT_ID                                   | EXPECTED_DOMAIN                         | PROVEN_BUG                       | IMPACT / 证据                                                                                                                                                                                   |
|-----------------------------------------------------------------------------------------------------------|----------------------------------------------|-----------------------------------------|----------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| chat_api.py:1198 update_message_feedback（1238/1244）                                                     | current_user.id                              | conversation/dialog owning workspace    | YES                              | _accessible_chat 接受共享 chat；apply_feedback→chunk_feedback_service.update_chunk_weight:188 直接 index_name(tenant_id)。加入成员操作会写向其个人/不存在索引；未证明可跨 tenant 写入有效 chunk |
| file_service.py:717 FileService.parse（726）                                                              | current_user.id 优先覆盖传入 tenant          | parsing/model owning workspace          | YES（有 request user 的分支）    | audio.chunk:48 按传入 ID 取默认 ASR；加入成员无个人配置会失败，有个人配置可能错选付费 workspace。无请求上下文时传入 tenant 路径不据此判错                                                       |
| openai_api.py:240 openai_chat_completions（270）                                                          | current_user.id                              | chat tenant + assistant access          | YES                              | 直接按 Dialog.tenant_id=user ID 查，加入共享 workspace 的可访问 assistant 会被拒绝；模型校验同样传 user ID。是功能性域错误，不是已证明泄漏                                                      |
| dataset_api.py:create_dataset（154..161）                                                                 | 旧 tenant 参数实际上 user                    | active workspace                        | NO                               | 在写入前 resolve_active_tenant_id，created_by 单独保留 user                                                                                                                                     |
| api_utils.py:277 add_tenant_id_to_kwargs；provider_api_service._active_tenant_id；models_api_service 同类 | user under legacy name                       | 消费者应转换成 workspace                | NO（已检查 provider/model 路径） | service显式 resolver；require_tenant_admin 根据 active workspace 验证，不能单看注入就判 bug；其他消费者仍需逐项审计                                                                             |
| mcp_api.py:create/update/delete/import 等（158/220/303）                                                  | current_user.id                              | USER-scoped MCP config                  | NO                               | 模块注释和读写一致明确用户作用域，另行验证 active workspace                                                                                                                                     |
| agent_api.py:_webhook_impl（2156）                                                                        | cvs.user_id 传 Canvas                        | asset workspace                         | NO（身份参数这一点）             | Canvas(canvas_id) 重新加载 asset.tenant_id；没有 actor 的计量问题是另一个边界                                                                                                                   |
| chat_api.py:create/model/search 路径（268,763,844,1271,1379,1404,1447）                                   | tenant字段或active workspace后 fallback user | 资源 workspace                          | INSUFFICIENT_EVIDENCE            | 正常资源 tenant 优先；需验证缺 tenant 行的可达性，不能仅由 fallback 判定线上错付费                                                                                                              |
| memory_api_service.py:create_memory/_memory_accessible（57/105）；memory_api.py:40                        | user ID                                      | 旧 memory owner 还是 workspace 尚需明确 | INSUFFICIENT_EVIDENCE            | memory_service 以 tenant_id join User，存在明确旧 owner语义；无 membership 的早返回值得复核，但不能直接宣布可利用撤权绕过                                                                       |
| connector_api.py:create_connector/get（98/205）                                                           | user ID                                      | connector owner/domain 待确认           | INSUFFICIENT_EVIDENCE            | 创建/所有权检查相同；共享 connector 的产品契约未证明；不能直接当 workspace provider                                                                                                             |
| compilation_template_group_api.py:create/update（116/149）                                                | user ID                                      | 个人模板集合或 workspace                | INSUFFICIENT_EVIDENCE            | list/detail同样按 user；无证据宣称共享 workspace 隔离错误                                                                                                                                       |
| chat_channel_api.py:create（54）                                                                          | user ID                                      | channel owner及绑定应用 scope           | INSUFFICIENT_EVIDENCE            | 绑定 dialog 要求 conn.tenant_id匹配，需结合 channel owner约定判断；可能限制共享应用但不先定性泄漏                                                                                               |
| backward_compat.py（537/553）                                                                             | user ID                                      | 取决于具体旧入口契约                    | INSUFFICIENT_EVIDENCE            | 旧入口不能整体视为 active workspace，也不能直接视为都安全                                                                                                                                       |

关键安全正例：[get_model_config_by_id](C:/Projects/RAG/wenruo-rag/api/db/joint_services/tenant_model_service.py:388) 检查
provider.tenant_id 与 requested tenant 一致、instance.provider_id 与 model.provider_id 一致，且有 execution_user 时先验证
live membership；[resolve_config_tenant_id](C:/Projects/RAG/wenruo-rag/api/db/services/user_service.py:266) 的真实签名是
`(user_id, owner_tenant_id)`，返回经验证的 resource workspace，不能输入两个已经混淆的 tenant IDs。

全局结论：存在已证实 domain 错误，不能宣告整个系统 tenant isolation 全通过；本轮没有证明全局跨租户数据泄漏，也没有修复。

## 7. Provider Health Existing Fact Sources

| Fact                             | Existing Source                                                                | Persistent?                             | Sanitized?                                       | Provider             | Model                | Key Instance                 | User                                | Workspace  |
|----------------------------------|--------------------------------------------------------------------------------|-----------------------------------------|--------------------------------------------------|----------------------|----------------------|------------------------------|-------------------------------------|------------|
| 内部限额/撤权拒绝                | reserve_call→WorkspaceAccessDenied                                             | 拒绝本身不写 attempt ledger             | 公共消息受控                                     | 无                   | 无                   | 无                           | 调用上下文                          | 调用上下文 |
| 预留/settled/unsettled           | SQL ledger                                                                     | 是                                      | 无 key/prompt 字段                               | 无                   | 裸名称，额外 round空 | 无                           | 是                                  | 是         |
| embedding quota/rate failure     | embedding_model.EmbeddingQuotaExhausted/EmbeddingRateLimited/embedding_failure | exception 瞬时；日志视 sink             | 否；raw_message 与摘要保留上游文本               | 消息参数，不是可靠ID | 不保证               | 无                           | 不保证                              | 不保证     |
| 上游 HTTP 4xx/5xx/timeout        | SDK、_raise_model_exception_if_failed、chat wrappers                           | 无统一事件表，日志可能保留              | 否；response body/exception可入日志              | wrapper已知          | wrapper已知          | dispatch内可知但未标准持久化 | 上下文不保证写出                    | 同左       |
| chat quota/rate/auth/timeout等   | chat_model._classify_error/_handle_error                                       | 临时分类/字符串/日志                    | 不可视为统一脱敏                                 | 上下文               | 上下文               | 无结构化字段                 | 不保证                              | 不保证     |
| location restriction / unknown   | SDK 异常文本                                                                   | 视日志                                  | 未见统一安全持久分类                             | 条件                 | 条件                 | 无                           | 不保证                              | 不保证     |
| P0 retrieval leg failure/success | health_bridge执行点→health_producers.HealthSession                             | request内；响应可能随会话 reference保存 | 对外contract受控；detail不是通用日志许可         | 无                   | 无                   | 无                           | 无固定字段                          | 无固定字段 |
| P0-7 retrieval event             | health_producers._log_operator_event                                           | 日志 sink；线上 retention 未知          | 严格九字段白名单，不含原始异常/密钥              | 无                   | 无                   | 无                           | 无                                  | 无         |
| 模型/instance enabled状态        | TenantModel.status / TenantModelInstance.status                                | SQL                                     | 展示元数据可以                                   | 经关联               | 是                   | instance ID                  | 无                                  | 经provider |
| last-success / last-failure      | 已检查 model/instance schema、服务及dispatch                                   | 未见统一持久列/事实源                   | 不适用                                           | 不完整               | 不完整               | 不完整                       | —                                   | —          |
| Langfuse generation error/usage  | LLMBundle observation                                                          | 配置启用时外部存储                      | 会含 prompt/output/error，不能整体转发 Dashboard | 依trace              | 通常名称             | 不保证                       | session/user attrs可能是tracing身份 | 非统一字段 |
| task/pipeline错误                | progress_msg、PipelineOperationLog                                             | SQL/日志                                | 原始异常可能写入，未统一脱敏                     | 不保证               | 不保证               | 无                           | task可能有initiator                 | 可关联     |

P0-7
的九字段原样冻结：event,schema_version,overall,reason,evidence_completeness,legs,contract_valid,routes_attempted,routes_succeeded。其代码位于 [health_producers.py](C:/Projects/RAG/wenruo-rag/rag/retrieval/health_producers.py:222)
。它没有 provider/model/key/user/workspace 信息，不能单独产生 provider health dashboard。

现有分类并不统一：common.model_errors 能区分 embedding daily/account quota 和 rate；P0 reason_from_exception 仍将 dense 的
quota/429/rate marker 归为 EMBEDDING_QUOTA_EXHAUSTED。因此 P0 的这项 reason 不能作为“上游余额确实耗尽”的严格证据。本轮不修改
P0 reason 或事件。

隐私事实：[model_failure_response](C:/Projects/RAG/wenruo-rag/common/model_errors.py:110) 返回 raw_message 截断到 400
字；[server_error_response](C:/Projects/RAG/wenruo-rag/api/utils/api_utils.py:156) 会将这个字段放入 JSON response。截断和“UI
不渲染”均不等于脱敏。不得直接复用该 raw 字段构建管理员健康信息。

## 8. API Key / Provider Scope 与 Security / Privacy Boundary

当前规范配置链为 **workspace provider → model instance credential → models**；provider 是 tenant-scoped，key 实际存储在
instance。旧 TenantLLM 另有 key 列；APIToken 是 workspace 应用凭据，二者不可混淆。Builtin 模型配置可来自全局
settings，这是执行配置特例，不是全局 usage key registry。

- 同一物理 key 可以被手工填入多个 workspace/instance；schema 没有 key 唯一性约束，也没有安全的 key identity
  registry。不能假定一个 key只付一个 workspace。
- 当前可统计“workspace 已计量使用量”；不可精确统计该 workspace 内按 provider分组的历史使用量，因 ledger 无 provider ID。
- 不能安全算 key total usage：缺实例/版本归因，且同一 key 还可能在系统外使用。即使未来收齐实例ID，也只能声称本系统观察到的
  key usage，不能声称整个上游账户总量。
- Dashboard **不需要读取或展示 API key plaintext**。应从 usage/安全配置投影读 ID、名称、类型、配置状态、定价覆盖；不能用读取明文再
  hash 的方式给本轮补历史归因。
- 普通 ORM 全行读取 instance 会取到 api_key，即使随后 mask；未来 read model必须投影白名单列。已有 provider service使用
  mask_secret 是呈现措施，不证明统计路径无需取 secret。
- workspace 管理员只见自己管理 workspace 的数据；NORMAL 的执行能力不授予配置/密钥访问。已删除成员保留历史用量、不能重新获得执行权限。
- Provider state应以 scoped observation+时间解释；缺近期 observation 是未知/无近期观察，不得显示“Healthy”。成功一次也不能保证之后的可用性。
- 不将 raw SDK body、URL query、headers、prompt/output、token/key或 Langfuse完整trace搬到 Dashboard。密钥轮换后旧事件不能被误当成新
  key 的状态。

## 9. U1–U7 Architecture Freeze Proposal

以下仅是后续范围建议，没有批准或启动 implementation。

| 阶段                 | 建议冻结范围                                                                                                                                                     | 准入/排除                                                                                                                                                          |
|----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| U1 Usage Read Model  | 先基于现有 SQL ledger/counters提供 workspace/member/day/month、calls、tokens占用、settled vs outstanding、Estimated model cost与覆盖说明；model只能标裸名称/未知 | 不先migration；正确处理status与时区；无provider/workload/key伪归因；需要source tests可运行和无secret生产shape核对。新 aggregation可为性能/分页，但不能创造缺失事实 |
| U2 Admin Dashboard   | limits/current counters、成员使用量、日/月趋势、reserved/unsettled比例、定价覆盖与数据缺口                                                                       | 不能展示 provider余额、精确key总量或 invoice；role豁免明确展示；UI不能替代backend auth                                                                             |
| U3 Monetary Hard Cap | 先决定member cap还是workspace总额、管理者政策、定价完整性、预留严格性/重试、无split/无usage语义、对账                                                            | 现有数字cost enforcement已经存在且GET/PUT可配置；**不是仅缺UI**。严格cap需单独设计与授权；不改变本轮已有limits                                                     |
| U4 Detached Coverage | 优先特殊任务enqueue丢actor、远程OCR绕过、vision/ASR/TTS settlement缺口；webhook服务身份单独决策                                                                  | 已证明缺口优先；保留unknown/legacy/by-design区别；inactive per-doc helper不当作活跃事故                                                                            |
| U5 Provider Health   | **PASSIVE_OBSERVATION_FIRST**；在真实dispatch成功/失败处建立安全、带workspace/provider/model/instance归因的独立观察方案                                          | 无需active probe；不从ledger/P0推健康；不修改P0-7；新的持久结构/分类仅后续授权设计                                                                                 |
| U6 Provider UI       | 安全实例名称、模型、enabled配置状态、最近被动观察及其时间/覆盖、受控失败说明                                                                                     | enabled≠healthy；观察≠持续SLA；无plaintext/raw body；没有观察不显示绿灯                                                                                            |
| U7 Alerts            | 内部精确可知的是预算规则、当前SQL占用、计量拒绝（需观察记录后才有历史次数）、unsettled积压；provider按观测失败频率/恢复                                          | provider账户剩余额度、系统外key用量和真实bill未知；先冻结阈值/窗口/去重/权限，再授权email/webhook，不主动发送                                                      |

推荐顺序：批准U0边界 → U1最小read model → U2；U4已证明缺口与U3严格金额定义在资金承诺前完成；U5被动事实归因 → U6 →
U7。若U2首版要求按provider/model-instance/workload精确历史，则不能先做“聚合就够了”，必须先批准未来采集边界，而且历史缺失无法补造。

### Open Decisions requiring authorization

1. U1首版是否接受“已计量范围”的member/day/month视图，以及模型裸名称和未知桶？是否明确排除provider/key/workload精确分组？
2. 生产只读验证使用哪个已授权连接/环境：只取schema/index、status分布、时间范围及模型pricing白名单；不取任何
   key。当前没有完成线上模型价格/覆盖名录。
3. U3要的是员工预算控制还是包含OWNER/ADMIN的workspace严格总额？如何处理无价模型、超预留、无token split及重试？本轮不改变现有豁免。
4. U4 anonymous webhook/background sync 的付费身份政策；明确哪些legacy owner fallback继续保留，哪些新任务必须保存真实成员。
5. 将来provider事实的保留周期、credential rotation identity、可见范围与脱敏规则；不得读取明文补历史。
6. 把本轮已证明的身份/结算缺口纳入哪个后续修复批次；不推进独立retrieval/P1-2。

## 10. 验证记录与停止点

交叉阅读的既有测试：

- [test_workspace_budget_settlement.py](C:/Projects/RAG/wenruo-rag/test/unit_test/api/db/services/test_workspace_budget_settlement.py:80)
  ：实际usage、重复结算、unreported、超额补记、token/cost、timezone、并发、manager、撤权、detached fallback/fencing、snapshot。
- [test_workspace_security.py](C:/Projects/RAG/wenruo-rag/test/unit_test/api/db/services/test_workspace_security.py:128)
  ：rate/durable quotas、并发、故障拒绝、subcalls/streams、retry attempts、HTTP200/code108。
- [test_detached_task_initiator.py](C:/Projects/RAG/wenruo-rag/test/unit_test/api/db/services/test_detached_task_initiator.py:53)
  ：普通enqueue、dataflow、get_task、legacy NULL。

本机尝试执行以上三文件，使用 `--noconftest -p no:cacheprovider` 避开共享conftest下载；首次被本机pytest未知
asyncio配置项打断，诊断重跑仅放宽warning后显示缺 `peewee`、`valkey`， **0 collected / 3 collection errors**
。没有安装依赖、没有宣称测试通过；这也未验证线上并发事务语义。测试源码中未见OCR bypass、定价无split为零成本、provider实例历史归因的相应保障。

只新增本审计文档；没有实现代码、迁移、Dashboard、probe、retag、部署或生产写入。完成Discovery文档后停止。

```text
WORKSPACE_BUDGET_CURRENT_STATE: IMPLEMENTED_PER_MEMBER; LIVE_MEMBERSHIP_GUARDED_ON_METERED_PATHS
USAGE_LEDGER_CURRENT_STATE: DURABLE_RESERVE_SETTLE; PARTIAL_MODEL_ATTRIBUTION; NO_PROVIDER_INSTANCE_WORKLOAD
COST_ENFORCEMENT_CURRENT_STATE: OPTIONAL_ESTIMATED_PER_MEMBER_LIMITS; NOT_STRICT_WORKSPACE_MONETARY_CAP
DETACHED_JOB_ATTRIBUTION_CURRENT_STATE: MAIN_PARSE_DATAFLOW_COVERED; SPECIAL_ENQUEUE_GAPS; LEGACY_FALLBACK
TENANT_ISOLATION_VERDICT: PROVEN_IDENTITY_DOMAIN_ERRORS; NO_GLOBAL_PASS; NO_PROVEN_GLOBAL_DATA_LEAK
PROVIDER_HEALTH_CURRENT_STATE: PARTIAL_PASSIVE_FAILURE_FACTS; NO_UNIFIED_PERSISTENT_INSTANCE_HEALTH
PROVIDER_QUOTA_VISIBILITY: OBSERVED_REFUSALS_ONLY; REMAINING_UPSTREAM_QUOTA_UNKNOWN
API_KEY_PLAINTEXT_REQUIRED_FOR_DASHBOARD: NO
ACTIVE_PROVIDER_PROBE_REQUIRED: NO
U1_IMPLEMENTATION_READY: NO
PRODUCTION_MUTATED: NO
```

U1=NO 表示不能对完整目标直接开工：最小query-only范围已有源码设计依据，但尚需确认范围、线上安全数据形状与可运行测试；不是建议先新增字段。本轮到此停止。
