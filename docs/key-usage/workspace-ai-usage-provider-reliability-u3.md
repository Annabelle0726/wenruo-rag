# U3 — Usage Policy & Pricing Foundation: Design / Implementation Readiness

状态：**DESIGN READY；IMPLEMENTATION PARTIAL（Usage Policy 后端已实施并测试；Pricing 未实施；详见 §9）**。
基线提交：`3a22425f6`。本轮只读核对源码与封存报告，只更新本文和 AGENTS.md；不连接生产、不实施 U3。

## 1. 决策与接受基线

接受 U1 read model 已完成、U2/U2.1/U2.2 已接受、中英文真实浏览器验收 PASS。接受最近已验证的 live pricing：**0 PRICED / 75 UNPRICED**；本轮不重新探测、不将历史 live 数值冒充新测量。U0.5 最初的 U1 readiness blocker 已由后续阶段关闭，不在本轮重新打开。

**最小安全 U3 = 四个现有 Calls/Tokens 控制的管理界面 + 有边界的手工模型定价配置。不开启 monetary-limit 产品功能，不承诺严格金额硬帽。**

| 决定 | 冻结范围 |
|---|---|
| Usage Policy | Settings → Team → Usage Policy；OWNER/ADMIN 编辑适用于每个 NORMAL 成员的 daily/monthly Calls、Tokens |
| 保持不变 | OWNER/ADMIN 限额豁免但仍计量、live membership 校验、reserve/settle、失败封闭、时区和现有默认值 |
| 不新增可编辑项 | rolling-minute、timezone、cost limits；继续如实只读显示后端已存在的值，不清零、不覆盖 |
| Pricing | Settings → Model Providers → Managed API 的已保存模型，独立的安全定价入口；仅 USD / million input/output tokens |
| 不包含 | monetary-cap UI/启用流程、对账/释放预留、批量定价、自动价目表、历史回算、provider/instance历史归因、基础设施成本 |
| 排除的后端 | Provider Health、Retrieval Health、notification/bell、quota/balance polling、email/webhook、GPU monitoring |

已有预算执行服务仍是唯一权威。控制面只能配置已有规则，不能用前端本地状态作 admission decision。界面必须说明“每位普通成员的使用策略”，不得将 workspace 总使用量除以 per-member limit 来画总体额度进度条。

## 2. 源码证据与复用边界

| 事实 | 当前来源 | U3 决定 |
|---|---|---|
| PUT 已存在 | [tenant_api.usage_budget](C:/Projects/RAG/wenruo-rag/api/apps/restful_apis/tenant_api.py:358) → [configure_budget](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py:117) | 复用 `PUT /api/v1/tenants/<tenant_id>/usage-budget`；不造第二份 budget service |
| 事务授权、partial update、audit | configure_budget 锁 Tenant、查询 active UserTenant OWNER/ADMIN、更新给定字段、写 WorkspaceAudit(action=update_budget) | 保留并做必要的条件更新支持；不改变 reserve_call |
| 只读权威展示 | [quota_status](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_usage_read_service.py:792) | 继续 GET `/usage/quota`，不改用会 self-update Tenant 的 budget GET |
| 当前只读 UI | [usage-policy.tsx](C:/Projects/RAG/wenruo-rag/web/src/pages/user-setting/setting-team/usage-policy.tsx:21) | 在本页加显式 Edit/Save/Cancel，不另建 Settings 页面 |
| pricing 在模型而非凭据 | TenantModel.extra，[_model_pricing](C:/Projects/RAG/wenruo-rag/api/db/joint_services/tenant_model_service.py:243) | 复用两个既有 JSON keys，不新增价格表/列 |
| 通用 model PATCH 接受 extra | [provider_api.alter_model](C:/Projects/RAG/wenruo-rag/api/apps/restful_apis/provider_api.py:973)、[update_model](C:/Projects/RAG/wenruo-rag/api/apps/services/provider_api_service.py:1396) | 不能直接复用其任意 extra 写入作为安全 pricing API：无专用价格校验/audit，且 hydrate instance含api_key |
| 输入/输出 cost 计算 | [model_budget](C:/Projects/RAG/wenruo-rag/common/model_budget.py:98) | 本轮设计不改公式/settlement；新配置必须面对既有精度限制 |
| U1 coverage 依据 | [read service](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_usage_read_service.py:115)：正 cost 是 evidence | 配置覆盖与历史 cost evidence 分开；配置完成不改写历史 coverage |
| Managed 分类 | [model-provider-endpoint.ts](C:/Projects/RAG/wenruo-rag/web/src/constants/model-provider-endpoint.ts:29) | 是 provider identity 分类，不是上游账单证明；后端必须复核 eligibility，不能信任前端 kind |

已有 `configure_budget` 不带 stale-write 检测：事务能串行写入，但同字段会 last-committed-write-wins。现有模型 extra 写还会 read/merge/write，可能覆盖并发修改。U3 不将这些行为误称“已有 optimistic concurrency”。

## 3. Usage Policy 写入契约

### 3.1 表单与数值

四个字段：`calls_per_day`、`calls_per_month`、`tokens_per_day`、`tokens_per_month`。只提交 dirty fields；清空不是 0，不允许空字符串、null、bool、非整数、NaN、负数或隐式字符串转换。Calls 必须正整数；Tokens=0 明确表示 **Not enforced / 未启用**，不是零额度。daily和monthly各自独立执行，不强加 day≤month 关系。

当前服务接受数值至 10^10，但 Calls 存在 IntegerField、Tokens 为 BigIntegerField。U3 的写入验证须与存储范围一致：Calls 1..2,147,483,647；Tokens 0..10^10；服务端验证，前端镜像提示。对旧接口中 Calls 的超存储范围请求返回受控验证错误，而不是数据库异常；这是本轮控制面写验证范围，不是改执行限额默认值。

缺 budget row 时读取 backend defaults并标“默认策略”；无修改不发 PUT、不创建行。第一次有效编辑创建行，未编辑字段由既有后端默认值填充。不得在前端拼一份七字段默认对象回写。任何保存都不重置 counters、不刷新 period、不删除 reservation。

管理员降低 limit 到已用占用以下：允许保存，预先展示具体变更和“后续受计量调用可能立即被拒绝”；下一次 reserve 按既有规则判断，不撤回已发出的 provider 请求。不能承诺 instant cancellation。提高额度或设置 Tokens=0 同样只改变规则，不退款、不消除已发生记录。

### 3.2 授权、事务与审计

- 路径 workspace 是目标；认证 user 是 operator。服务内部重新查询该 workspace 的 active membership/role，不靠 UI、用户ID等于tenantID、缓存role或所选个人workspace判断。
- header中显式选择workspace如与路径不同，应受控拒绝，不静默fallback。测试必须覆盖“个人workspace的OWNER，同时目标workspace的NORMAL”。
- 每次 PUT 成功更新与 WorkspaceAudit 在同一事务；audit failure rollback。保留 action=update_budget，details保持既有字段和值的含义；无需审计schema迁移。
- 权限/撤权/跨workspace拒绝沿用 HTTP200 + code=108；成功必须检查业务 code=0，HTTP200本身不表示成功。无权请求不返回目标workspace的配置或差异。

### 3.3 并发：最小配置条件更新，而不是前端乐观改已生效值

给 U1 quota响应增加可选的 `policy_revision`（只读投影，无会计变更）：对workspace ID、budget row是否存在、七个limits与timezone的规范化值计算opaque hash。**不包含用量/counters**，否则每个model call都会制造冲突。

U3 PUT带 `If-Match: <policy_revision>`，body仍为既有字段子集，不把revision塞进未知字段body。configure_budget在已有Tenant锁/事务内授权后重新算revision并比较；不匹配返回HTTP200 + code=101、稳定 `error_type=POLICY_CONFLICT`，不更新、不写成功audit。新增UI永远带此条件。原有无header调用保留明确的last-committed-write-wins兼容语义，不声称强制全客户端CAS；不会因新增UI而破坏旧API。

本版选择**整份配置冲突**：即使两管理员编辑不同字段，后提交也先refresh/review再保存，最小且容易解释。partial PUT仍只改给定字段。读取后原值A→B→A不视为冲突，因为策略值相同；不是审计序列号，不承诺检测每次中间修改。revision不是授权凭证。

### 3.4 UI loading / error / navigation

1. workspace/role未解析、首次加载失败：不允许编辑，不展示假默认值；提供明确Retry。已有数据refresh失败时标stale并禁用Save直到成功刷新。
2. Edit保存本地draft与已确认baseline；本地输入可以即时显示，但**不optimistically修改已生效limits、usage/query cache或成功提示**。
3. Save禁重入；显示pending；不自动重试mutation，不触发provider/Redis probe。Cancel恢复baseline。
4. code=0才确认保存，按目标workspace失效quota/相关usage缓存并refetch。PUT成功但refresh失败须显示“已保存，刷新失败”，而不是“保存失败”或再次提交。
5. 超时/连接断开属于结果未知：禁自动重发，读取目标策略核对；值相同只表示“当前值已是所需值”，不能证明本操作产生了audit。保留draft供用户复核。
6. conflict保留draft，展示新baseline和diff，要求明确重新保存；不自动merge重试。权限丢失则停用编辑并刷新权限。
7. 切workspace时dirty draft提示放弃；pending响应绑定原tenant ID，不能写入新workspace UI/cache。切页不等于撤销已经发出的保存。
8. 中英文完整，包括按钮、0语义、exemption、冲突、未知结果、默认值、缺价说明；沿用现有error surface，避免一次失败多份toast。

客户端PUT使用项目请求适配层正确的 `{ data: patch }` body封装；对axios-native配置同样明确区分config和payload，测试实际网络JSON而非仅mock函数入参。

## 4. 成本与 Pricing Foundation

### 4.1 当前金额不是账单，也不是严格硬帽

现有 `price_input_per_million` / `price_output_per_million` 来自管理员模型extra；USD/million token数值上等于micro-USD/token。dispatch预留input估算 + min(output bound,8192)，随后按返回usage结算；cost_micros为整数。无价格默认成本0在执行账本中只表示没有成本计量，不证明免费。

已知限制仍成立：OWNER/ADMIN豁免；per-member而非workspace总帽；actual可超预留后补记；retry/tool额外轮次没有完整token/cost预留；无可信split可把非零tokens结算成cost0；vision/ASR/TTS缺结算报告；OCR bypass；无caller路径可不计量；无自动对账；ledger无单价版本/provider-instance归因。**Monetary cap本版NO，不是“等UI补齐就能安全启用”。**

统一术语 **Estimated model cost / 估算模型成本**。不使用actual bill、provider balance、remaining provider quota。缺价显示Not available/不可用；不把空值转成$0.00。私有端点也不推定免费。

### 4.2 哪些模型先允许配置

最小版本只允许已存在的Managed API模型记录，且该record的所有启用能力都属于 **chat / embedding / rerank**。OCR/vision/ASR/TTS或混合包含这些能力的record先只读：两个token价格不能代表按页、图片、秒数收费，当前结算路径也不完整。不通过改model_type来绕过限制。

后端依据provider_name和明确的known/private factory集合计算eligibility，未知provider拒绝，不由浏览器传 `managed=true` 决定。与现有前端分类做一致性fixture；provider名称分类不是网络端点/收费真实性证明，管理员必须确认输入的是该配置所使用API的token报价。无需读取base_url、api_key或检测网络。将来扩展能力/单位另行授权。

定价按 **TenantModel.id**，不是裸model_name；同名、不同provider/instance可有不同价格。model.provider_id必须属于路径workspace；instance_id只投影id/provider_id/instance_name校验关联，不能hydrate含secret的ORM实例。

### 4.3 定价表单、验证与保存

只提供每模型一个显式Save的Pricing编辑器，位于现有Managed API分类页的已保存模型项；不挂进会自动加载key/verify/remote-model-list的instance设置表单。

- 输入USD per 1,000,000 input tokens、USD per 1,000,000 output tokens，及明确“这是手工配置的估算单价”；不带provider实时价格/余额承诺。
- 启用定价必须完整提交两个值，避免现有解析器把缺失输出价默认为0；embedding/rerank输出价必须显式为0。chat允许某一方向明确免费，但不把留空当0。
- 两值允许0，均为finite nonnegative，最多6位小数，上限1,000,000 USD/million tokens；后端Decimal验证后按既有解析器兼容形式存入extra。拒绝bool、NaN/Infinity、负数、无穷大溢出、货币符号、未知字段及超过精度/上限输入，不静默round用户输入。金额计算仍采用既有运行时公式，不能宣称新写接口改变了账本精度。
- 提供显式“清除定价”：删除两个keys；不写0、不只清一个。清除意味着未来配置无价，不抹去历史成本。不提供partial价格激活。
- 读取旧数据允许 `unconfigured / partial / configured / invalid` 配置状态；partial/invalid不得显示成完整价格。存在不合法旧值时不猜、不自动修复；用户需显式提交完整合法pair或clear。
- 保存仅merge/delete两个白名单price keys，保留max_tokens、verify、capabilities及其他extra；总序列化长度必须符合TenantModel.extra的现有1024字符限制，超长拒绝并不写audit。

拟增加狭窄API：`GET/PUT /api/v1/tenants/<tenant_id>/models/<model_id>/pricing`。GET只返回IDs、display names、能力/eligibility、两项价格、配置状态、revision、cost-limit guard状态；PUT body是完整pair或明确clear操作。GET无写锁、无audit、无provider call；GET/PUT均要求目标workspace的active OWNER/ADMIN。PUT对目标模型、provider和instance归属做事务内复验。UI不需要通过credential详情获取名称或ID。

新的pricing service不调用resolve_model_config（它读key），不复用get_by_id(instance)全行读取，不向响应/日志/audit输出raw extra或credential。audit使用既有WorkspaceAudit，action=`update_model_pricing`，details仅model/provider/instance IDs、旧/新两项价格、set/clear；与价格update同事务，失败rollback。

### 4.4 定价不能偷偷启用金额限制

**设置、修改、清除价格前**，在与configure_budget一致的Tenant锁下读取cost_micros_per_day/month：任一非零即拒绝本版pricing mutation，提示“此workspace存在金额限制；U3尚未提供其安全变更流程”。只读价格仍可查看。不得自动清零限制，不得忽略它继续写价。缺budget row按现有默认0解释，不创建budget row。

这保证价格提交时不意外激活原有非零cost policy。若另一个已授权客户端随后通过既有budget API设置金额限制，仍由现有enforcement决定；U3不会禁用/绕过这个已有API。与并发budget写串行化，明确其先后顺序；不能声称本版阻止所有外部管理员启用金额限制。cost非零环境应单独批准后续monetary工作，而不是由本版UI试图接管。

价格保存并非离线draft：已有resolver会让**后续加载该配置的dispatch**使用新价格。已构造的bundle/长任务可能继续使用原model_config；in-flight reservation不重算。audit时间是配置commit时间，不是所有执行同步切价时间。无需清理授权cache、重启服务、provider验证或生产backfill。

### 4.5 写入口与并发闭合是定价上线门

pricing GET返回opaque revision（workspace/model identity、model type、两价格及存在性）；PUT必须If-Match，否则受控验证拒绝。事务内Tenant→model一致锁顺序，重新读extra再比较revision；冲突HTTP200/code101 `PRICING_CONFLICT`，无成功audit；不按旧extra覆盖新metadata。

不能只保护新按钮而保留任意extra绕过：已有provider `alter_model`、`add_model_to_instance`、`update_provider_instance`/create携带model_info.extra等用户可控路径，须拒绝新增/变更/清除保留price keys，并指引专用pricing接口。旧UI回传完全相同的price pair可剥离后保留数据库原值；回传stale不同pair拒绝，不能静默改价。模型目录发现/类型/max_tokens更新必须在原子读取合并中保留最新price pair，不能让并发更新以旧extra覆盖定价。删除整个模型保持其原有授权契约，不伪装成clear pricing。

上述是**新定价功能自己的必要写入口闭合**，不是授权修复U4会计缺口。实现时须枚举模型extra所有写入点，含直接ORM写；若无法在小范围内证明保留/拒绝规则，不得交付pricing写功能，也不得以“只有管理员会调用”绕过审计。可先交付独立的Usage Policy子范围，再报告pricing gate未通过。

### 4.6 配置覆盖与使用成本呈现

| 状态 | Pricing UI | Usage UI（继续U1/U2） |
|---|---|---|
| live 0 PRICED / 75 UNPRICED | 未配置价格 | unavailable + null → Not available，不是$0 |
| 有些配置有价 | 逐模型configured/unconfigured，配置覆盖可说明只限当前列表 | 不由配置计数改写usage coverage；同scope有/无成本evidence混合时partial |
| 完整pair有效 | Configured；可以显示明确0单价 | 只按ledger既有evidence判断complete/partial/unavailable，不是保存成功即available |
| 正成本已成立 | 不影响配置标签 | positive amount；partial必须标部分；complete仅表示该scope全部行有现有evidence，不表示系统账单完整 |
| 两价格显式0 / 微小金额四舍五入0 | 允许说明“配置单价为0”，不是声称消费免费 | U1依赖positive cost evidence，仍可能unavailable；不修改U1去猜已定价免费行 |
| 旧无split导致cost0 / 历史无价 | 不推断 | 保留unavailable/partial，绝不按当前价格重估历史 |

避免命名混淆：配置的`configured`不复用U1 `cost_coverage=complete`。U3不新增ledger pricing provenance，因此不承诺覆盖状态能区分合法零价、round-to-zero和旧结算缺陷。

## 5. Sealed U0/U0.5 Backlog：阻塞什么、不阻塞什么

来源：[U0.5 §6](C:/Projects/RAG/wenruo-rag/docs/key-usage/workspace-ai-usage-provider-reliability-u0-5.md:283)。全部旧项保持未修复；本表明确的是对**本次窄控制面**与**未来完整金额承诺**的不同影响。

| Backlog | 最小U3 Calls/Tokens控制面 + 限定pricing | 完整monetary/全路径enforcement |
|---|---|---|
| stale/orphaned reserved；无自动对账U3-02 | 非阻塞：占用保留，不提供释放/重结算按钮，不声称reserved仍运行；可能保守拒绝需诚实提示 | 阻塞可靠资金恢复/完整财务承诺；不能按时间自动退款 |
| U4-03 vision/ASR/TTS未上报结算 | 非阻塞：旧执行不变；排除这些能力的价格编辑，不改变其占用 | 阻塞完整token/cost计量 |
| U4-04 chat无split→cost0 | 不修复；限定为不完整Estimated model cost，U1将无证据行显式显示unknown/partial；阻塞任何准确总价宣传 | 阻塞monetary cap readiness |
| U4-01特殊enqueue丢actor；U4-02 OCR bypass | 非阻塞现有规则的管理界面；不承诺所有后台模型调用都受每成员限制 | 阻塞全路径预算/金额保证 |
| U4-05 detached归因唯一载体/撤权覆盖 | 不碰队列；新控制面每次mutation必须事务内查live角色 | 阻塞完整detached保证。注意当前reserve_call每次确实查membership；封存标题“mid-job不重查”不能扩展成所有bundle dispatch都不查。绕过/丢actor路径另论 |
| U4-06 identity-domain错误 | 已知chat反馈/file parsing/openai入口不在控制面调用链，不顺手修；新pricing必须用显式workspace/model IDs，任何新路径混用user ID即阻塞交付 | 错选workspace/拒绝共享资源等旧缺陷仍在U4 |
| U4-07仅定义的per-doc helper | 非阻塞；UNKNOWN不转成活跃事故 | 先验证活跃性 |
| U4-08 anonymous webhook身份未决 | 不涉及本版管理员写路径；非阻塞 | 阻塞宣称所有消费均有准确成员归因 |
| OWNER/ADMIN豁免、U3-01预留非严格上界 | 保留并显示；是接受的行为，不是顺手修复项 | 阻塞workspace总金额硬帽；必须另行改变产品/预算契约 |
| ledger无period/model索引及retention | 本版policy/pricing均PK或明确模型范围写，不增历史扫描/轮询；非阻塞。沿用U1有界查询 | 多成员大规模read SLA前独立索引/retention授权；不能删ledger后假定quota正确 |
| 无price version/provider instance历史关联 | 不backfill；审计记录本次安全价格变化，但不伪称能完整重算历史 | 阻塞精确归因/可复算金额保证 |
| U5-01/U5-02 Provider Health/P0 reason | 非阻塞、完全排除 | 不与内部预算状态混用 |

因此本版**无需先解封全部U4**。真正阻塞最小U3上线的是本次新增控制面的授权、条件更新、audit、价格校验/保留、无secret访问与cost-limit guard未达门槛；它们是待实现的acceptance gates，不能写成已通过。旧backlog仍阻止扩大到monetary cap。

## 6. Proposed Files（仅未来实施候选，本轮不改）

### Usage Policy

- [web/src/pages/user-setting/setting-team/usage-policy.tsx](C:/Projects/RAG/wenruo-rag/web/src/pages/user-setting/setting-team/usage-policy.tsx)：四字段编辑、确认与状态机。
- [web/src/hooks/use-workspace-usage-request.ts](C:/Projects/RAG/wenruo-rag/web/src/hooks/use-workspace-usage-request.ts)、[services/workspace-usage-service.ts](C:/Projects/RAG/wenruo-rag/web/src/services/workspace-usage-service.ts)、[interfaces/database/workspace-usage.ts](C:/Projects/RAG/wenruo-rag/web/src/interfaces/database/workspace-usage.ts)：mutation、workspace scoped缓存、revision。
- [api/apps/restful_apis/tenant_api.py](C:/Projects/RAG/wenruo-rag/api/apps/restful_apis/tenant_api.py)、[workspace_budget_service.py](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_budget_service.py)：If-Match交接、事务内条件更新、Calls存储范围校验；不改reserve/settle。
- [workspace_usage_read_service.py](C:/Projects/RAG/wenruo-rag/api/db/services/workspace_usage_read_service.py)：仅新增policy revision只读metadata，既有会计与coverage不变。

### Pricing

- 拟新增 `C:/Projects/RAG/wenruo-rag/api/db/services/model_pricing_service.py`、`C:/Projects/RAG/wenruo-rag/api/apps/restful_apis/model_pricing_api.py`：狭窄secret-free读写、事务、授权、audit、guard、conditional update。
- [provider_api_service.py](C:/Projects/RAG/wenruo-rag/api/apps/services/provider_api_service.py)、[tenant_model_service.py](C:/Projects/RAG/wenruo-rag/api/db/services/tenant_model_service.py)：仅关闭price-key旁路、保留并发价格；不改provider验证或执行。
- [provider-category.tsx](C:/Projects/RAG/wenruo-rag/web/src/pages/user-setting/setting-model/provider-category.tsx)：Managed已保存模型项挂独立Pricing dialog；不改含key的instance表单。
- 拟新增 `C:/Projects/RAG/wenruo-rag/web/src/pages/user-setting/setting-model/model-pricing-dialog.tsx`、`C:/Projects/RAG/wenruo-rag/web/src/services/model-pricing-service.ts`、`C:/Projects/RAG/wenruo-rag/web/src/hooks/use-model-pricing-request.ts`：仅安全字段请求。eligibility集合在新service定义，和现有 [model-provider-endpoint.ts](C:/Projects/RAG/wenruo-rag/web/src/constants/model-provider-endpoint.ts) 做契约测试，不新建endpoint分类产品。
- [en.ts](C:/Projects/RAG/wenruo-rag/web/src/locales/en.ts)、[zh.ts](C:/Projects/RAG/wenruo-rag/web/src/locales/zh.ts)：成对更新最小表单文案。

### Tests

扩展 [test_workspace_budget_settlement.py](C:/Projects/RAG/wenruo-rag/test/unit_test/api/db/services/test_workspace_budget_settlement.py)、[test_workspace_usage_read_model.py](C:/Projects/RAG/wenruo-rag/test/unit_test/api/db/services/test_workspace_usage_read_model.py)；新增隔离的pricing service/route测试、policy/pricing UI mutation测试。测试文件应分别靠近现有backend unit与前端组件测试。既有security/detached回归保留。

**不在候选变更中**：db_models/migration、common.model_budget、LLMBundle、task worker/queue、retrieval模块、health/event/taxonomy、通知后端、部署配置。若后续实现必须动这些边界，应先说明具体依赖，不能自动把U4并入。

## 7. Implementation Gates（未来须全部证明，不是本轮已执行）

| Gate | 场景与可判定结果 |
|---|---|
| G1 OWNER/ADMIN写授权 | 两个角色分别成功保存四字段子集/合法价格；服务直接调用也查目标workspace角色；保存前撤权或降为NORMAL后拒绝；成功恰有对应audit |
| G2 NORMAL拒绝 | 直接HTTP请求/手工JSON/已缓存旧UI均HTTP200 code108；无budget/model/audit改变；不能拿个人OWNER身份跨目标workspace写 |
| G3 workspace隔离 | fixtures至少两个workspace、多个不同user IDs；A管理员写B失败；model→provider→instance链任一跨tenant失败；header/path mismatch拒绝；失败不泄露B字段 |
| G4 partial PUT | 仅改daily_calls后其他calls/tokens/minute/timezone/cost完全不变；无budget行采用服务默认值；空patch/unknown/invalid拒绝；数字上下界按存储验证 |
| G5 0语义 | token0保存成功显示Not enforced；calls0拒绝；cost0继续为不执行；blank不是0；零单价≠missing；manager exemption与member规则分开显示 |
| G6 audit原子性 | 每个成功mutation目标tenant/operator正确，pricing audit仅IDs+old/new prices；模拟audit写失败，两表全部rollback；拒绝/conflict无成功audit，日志不含secret |
| G7 并发更新 | 两admin同baseline：第一次成功，第二次conflict且不丢第一值；refresh后partial save保留其他字段。metadata与pricing并发不丢extra/价格；pricing与budget cost修改按Tenant锁串行。使用隔离的生产同类型SQL验证锁语义，不能只靠SQLite证明 |
| G8 价格验证/旁路闭合 | input/output pair、explicit0、clear、invalid legacy、NaN/Inf/bool/negative/precision/size全部fixture；generic extra与model_info不能改price绕audit；不同provider同名模型定价独立 |
| G9 cost-limit guard | day或month任一非零，pricing set/update/clear拒绝且不改限额；零/缺row可保存；并发limit提交行为可预测；U3无monetary enable控件，无自动把现有限额清零 |
| G10 unavailable/partial/available | 0/75主路径为Not available，无$0.00；有价/无价混合为partial并显示真实已知部分；positive-evidence scope可complete。价格配置保存不能将旧无价ledger改成有价；tiny/zero/split缺陷继续诚实不可用。zh/en真实浏览器都验证 |
| G11 零secret读取/暴露 | SQL捕获证明无api_key/secret列、无SELECT * credential hydrate；对key getter/credential loading/resolve_model_config/provider SDK设置raising stub仍能读写pricing；HTTP响应、日志、audit、UI DOM均无secret/raw extra。无连接测试/model-list自动请求 |
| G12 权威执行回归 | 已有预算/settlement/security/detached/read-model suites无新增失败；按修改后的daily/monthly Call/Token设置在isolated fixture触发reserve拒绝/允许；OWNER/ADMIN仍记账且豁免；membership始终验证；无报告不退款、settle幂等、SQL故障fail-closed、时区保持 |
| G13 UI状态 | code108即使HTTP200也不成功；timeout不重试且结果未知；保存后refresh失败分开提示；conflict保留draft；pending切workspace不污染新cache；角色未解析/过期禁止写；GET保持只读 |
| G14 构建/真实浏览器/隔离 | type/lint/unit/build无新增问题；真实Chrome zh/en验证四字段和pricing流程；写验收必须隔离SQL/Redis/认证fixtures，绝不连共享生产库跑mutation；rolling Redis测试若skip必须明确，不冒充PASS |

不要求为了U3调用真实付费provider：dispatch可用可观察stub，计量/权限仍使用真实service；也不需要生产DB/Redis mutation验证。U2.2已有read-only browser PASS不能代替新增U3写流程验收。

## 9. U3 实施记录（本轮，部分交付并如实标注）

基线 `3a22425f6`。本轮**只实现了 Usage Policy 的后端控制面**；Pricing Foundation 未实现，
因此按用户预设的降级口径**单独报告 Usage Policy、Pricing 标 NOT ACCEPTED**。

### 9.1 已实施（backend，18 个新测试）

| 文件 | 变更 |
|---|---|
| `api/db/services/workspace_budget_service.py` | 新增 `policy_revision(tenant_id, budget=None)`：对 workspace ID、budget 行是否存在、七个 limits 与 timezone 做规范化 opaque hash，**不含 counters/ledger**；新增 `PolicyConflict`；`configure_budget` 新增可选 `expected_revision`（在既有 Tenant 锁与事务内重新计算并比较，不匹配即抛错且不写任何行/不写成功 audit）；写入范围改为与存储一致（Calls 1..2,147,483,647、Tokens 0..10^10），超范围变成受控拒绝而不是数据库异常 |
| `api/db/services/workspace_usage_read_service.py` | `quota_status` 增加只读 `policy_revision` 投影（不改任何会计/coverage 语义） |
| `api/apps/restful_apis/tenant_api.py` | PUT 读取 `If-Match: <policy_revision>` 并透传；冲突返回 HTTP200 + `code=101` + `error_type=POLICY_CONFLICT`；无 header 调用保留既有 last-committed-write-wins |

实施中发现并修掉一个**真实缺陷**（由测试捕获，不是测试写错）：`configure_budget` 最初把**写前**读到的行用于响应里的 revision，
于是调用者拿到的 `policy_revision` 是它刚提交的那个值，**下一次保存必然冲突**。现在响应返回写后 revision。

### 9.2 Gate 状态（G1–G14，逐条如实）

| Gate | 状态 | 证据 / 缺口 |
|---|---|---|
| G1 OWNER/ADMIN 写授权 + audit | **PASS** | `test_owner_and_admin_can_save_and_each_write_is_audited`（两个角色各写四字段子集，audit 的 operator/action/details 正确）；`test_authorization_is_rechecked_in_the_service_not_only_in_the_route` 证明降级为 normal 后服务层直接拒绝 |
| G2 NORMAL 拒绝 | **PASS** | `test_g2_normal_member_cannot_write`：拒绝且 budget 行与 audit 均未产生 |
| G3 workspace 隔离 | **PASS（policy 范围）** | `test_g3_a_personal_workspace_owner_cannot_write_another_workspace`：只拥有"自己"workspace 的 owner 对另两个 workspace 写入均拒绝、零行零 audit。**header/path mismatch 与 model→provider→instance 链未覆盖**（pricing 未实现） |
| G4 partial PUT | **PASS** | `test_g4_a_partial_update_touches_only_the_given_field`（只改 calls_per_day，其余 calls/tokens/minute/timezone 全不变）、`test_g4_an_empty_or_unknown_patch_is_refused`（空/未知/字符串/bool/float）、`test_g4_calls_are_validated_against_the_storage_column`（边界恰好） |
| G5 0 语义 | **PASS** | `test_g5_tokens_zero_means_not_enforced_and_calls_zero_is_refused` |
| G6 audit 原子性 | **PASS** | `test_g6_a_failed_audit_write_rolls_the_limits_back`（模拟 audit 写失败 → 零行）；`test_a_refused_update_writes_no_success_audit` |
| G7 并发更新 | **部分：SQLite 语义已证，生产同类型 SQL 未执行** | 已证：`test_a_matching_revision_saves_and_a_stale_one_conflicts`（第一个成功、第二个 conflict 且第一个的值未被覆盖、无成功 audit）、`test_a_caller_without_the_header_keeps_the_legacy_behaviour`、`test_saving_never_resets_counters_or_creates_a_second_row`、`test_the_revision_covers_policy_and_ignores_usage`（用量变化不产生 revision 变化）。**缺口**：设计明确要求用隔离的生产同类型 SQL（MySQL/GaussDB，含 InnoDB 行锁语义）验证锁行为；本机 SQLite 不能证明该语义，本轮**没有**取得隔离的 MySQL 写入环境（共享实例属于被禁止变更的生产型资源），因此**不宣称 G7 通过**。 |
| G8–G11 | **NOT EXECUTED** | 全部属于 Pricing Foundation；该功能本轮未实现 |
| G12 权威执行回归 | **PASS** | 预算/settlement/security/detached/read-model 五个套件共 `109 passed, 2 skipped`，无新增失败；policy 写入不触 counters/period/reservation |
| G13 UI 状态 | **NOT IMPLEMENTED** | 前端 Edit/Save/Cancel 与 §3.4 状态机本轮未实施（见 9.3） |
| G14 构建 / 真实浏览器 / 隔离 | **未完成** | 类型检查/lint/单测在本轮改动范围内通过；`npm run build` 与 **zh/en 真实浏览器写流程验收未执行**（没有 UI 可验），因此不宣称通过 |

### 9.3 明确未交付（本轮如实标注）

- **Pricing Foundation 完全未实施**（无 `model_pricing_service.py` / `model_pricing_api.py` / 前端 dialog / 旁路闭合 / cost-limit guard）。
  因此 `PRICING_WRITE_PATHS_CLOSED: NO`（既有 `alter_model` 等任意 extra 写入路径**未收敛**，price key 仍可被旧入口改写）。
  **不得**在本状态下启用任何定价 UI。
- **Usage Policy 前端编辑器未实施**：`usage-policy.tsx` 仍是只读展示，因此 §3.4 的 drafting/conflict/timeout/切 workspace 语义尚未存在；
  后端契约（If-Match、revision、冲突码）已就绪，UI 只是消费者。
- 未改 U1 会计语义、未开 monetary cap、未加 Provider/Retrieval Health、未加通知、未做 schema migration、未部署、未 retag `:latest`。
- API key 明文读取：本轮改动**只涉及** `workspace_budget`/`workspace_usage*` 与租户路由，**未新增任何 credential 读取**；
  但在缺少 SQL 捕获证据的情况下，本轮**只声明“本轮的改动没有新增 secret 访问”，不冒充 G11 已通过**。

### 9.4 结论

`U3_USAGE_POLICY_IMPLEMENTED`：**后端契约 YES / 前端编辑器 NO**；`U3_PRICING_FOUNDATION_IMPLEMENTED: NO`；
`U3_ACCEPTANCE_VERDICT: USAGE_POLICY_BACKEND_ACCEPTED_AT_CODE_LEVEL; PRICING_NOT_ACCEPTED; G7_PRODUCTION_TYPE_SQL_AND_G13/G14_OPEN`。

## 10. U3-A 记录：Usage Policy 垂直切片

### 10.1 本轮交付

**后端**（上一轮已交付，本轮回归保持）：`policy_revision` / `PolicyConflict` / `If-Match` 条件更新 / 存储范围校验 / `quota_status` 只读 revision。

**前端**（本轮新增，Settings → Team → Usage policy）：

| 文件 | 作用 |
|---|---|
| `web/src/pages/user-setting/setting-team/usage-policy-validation.ts` | 纯逻辑：字段校验（Calls 1..2147483647、Tokens 0..10^10、**留空不等于 0**、拒绝 `1.5`/`1e3`/`1,000`/`+3` 等非整数字面量）、只提交 dirty 字段的 patch、字段错误收集、`code=101 + error_type=POLICY_CONFLICT` 判定 |
| `web/src/pages/user-setting/setting-team/usage-policy.tsx` | 编辑器状态机：Edit/Save/Cancel、draft 与 baseline 分离、conflict 需先 reload、超时=结果未知且**不自动重发**、保存成功但刷新失败单独提示、保存中禁重入、role 未解析或非管理员禁止编辑 |
| `web/src/services/workspace-usage-service.ts` | 新增 `updateUsageBudget`：复用既有 `PUT /tenants/<id>/usage-budget`，patch 走 `data`、revision 走 `headers['If-Match']`（native 配置，二者不可能混淆） |
| `web/src/hooks/use-workspace-usage-request.ts` | `useUpdateUsagePolicy` mutation：`retry: false`、只在 `code===0` 时按 workspace key 失效 quota/usage 缓存 |
| `web/src/locales/{en,zh}.ts` | 各 +23 个 `usage.*` 键（含 0 语义、豁免、冲突、未知结果、缺省策略文案） |

行为要点：编辑器**不改动已生效的 limits/cache/成功提示**（无 optimistic 写），只按 dirty 字段提交，因此保存一个字段不会覆盖其他字段；`0` 在 Calls 上被拒绝、在 Tokens 上即"未启用"；OWNER/ADMIN 豁免由服务端返回并显式显示；滚动分钟的 `used` 仍显示为"此处不跟踪"，不编造数值。

### 10.2 Gate 状态

| Gate | 状态 | 证据 |
|---|---|---|
| G1–G6 | **PASS** | `test_workspace_usage_policy.py` 18 项（含 audit 原子性、拒权、跨 workspace、partial、0 语义、存储范围） |
| **G7** | **PASS（隔离生产同类型 SQL）** | 新增 `test_workspace_usage_policy_mysql.py`，跑在**临时 MySQL 8.0.40 容器**（`mysql:8.0.40`，与部署大版本一致，端口 3399，**不是**共享的 3307 实例）：`3 passed`。证明：引擎确为 8.0；两写入者持同一 revision → 恰好一个 `saved`、另一个 `POLICY_CONFLICT`；胜者值原样保留（**无丢失更新**），无关字段 `tokens_per_day` 不变；仅胜者留下 1 条成功 audit；10 个并发写入者恰好 1 个提交、0 异常 |
| G12 | **PASS** | policy + budget/settlement/security/read-model/detached：`109 passed, 2 skipped`（本轮新增前），policy 写入不动 counters/period/reservation |
| G13 | **部分 PASS** | 纯逻辑与状态机语义由 13 项 jest 单测覆盖（blank≠0、只发 dirty、冲突判定、越界拒绝）；**未做组件级 jsdom 交互测试**，UI 渲染状态未在浏览器中验证 |
| G14 | **未执行** | 本轮上下文预算在完成 G7 与前端实现后耗尽，**未运行** `npm run build`、也未做 zh/en 真实浏览器写流程（保存→重载→持久化、stale conflict、NORMAL 拒绝入口）。因此**不宣称 G14**，`U3_USAGE_POLICY_COMPLETE` 保持 **NO** |

### 10.3 结论

Usage Policy 的**后端契约、前端编辑器、纯逻辑与 G7 并发门**均已交付并通过；**G14（构建 + 真实浏览器写流程）未执行**，
故本轮不宣告 U3-A 完成。Pricing Foundation 仍未实施（`PRICING_WRITE_PATHS_CLOSED: NO`），不得启用任何定价 UI。
未开 monetary cap、未做 schema migration、未改生产 DB/Redis/配置、未部署、未 retag `:latest`。
本轮改动**未新增任何 credential 读取**。

## 8. 状态板与停止点

```text
U3_RECOMMENDED_SCOPE: FOUR_CALL_TOKEN_POLICY_CONTROLS + GUARDED_MANUAL_MANAGED_MODEL_PRICING_FOUNDATION
U3_MONETARY_CAP_READY: NO
U3_PRICING_CONFIGURATION_READY: YES
U3_BLOCKING_BACKLOG: NONE_FOR_RECOMMENDED_NARROW_SCOPE; MONETARY_ONLY—U3-01/U3-02, relevant U4 accounting/attribution/identity gaps, missing pricing provenance/full coverage
U3_NON_BLOCKING_BACKLOG: FOR_NARROW_CONTROL_PLANE—sealed U0/U0.5 accounting/identity items; stale reservations; ledger indexes/retention; U4-07 UNKNOWN; U5 health
SCHEMA_MIGRATION_REQUIRED: NO
API_KEY_PLAINTEXT_REQUIRED: NO
PRODUCTION_MUTATION_REQUIRED_FOR_IMPLEMENTATION: NO
PROPOSED_FILES: section 6
IMPLEMENTATION_GATES: G1–G14, NOT EXECUTED IN THIS DESIGN ROUND
U3_IMPLEMENTATION_READY: YES
```

两处READY=YES均指**上述窄范围设计已可实施、没有未决产品选择**，不是已实施/测试通过/已批准上线。monetary仍NO；定价的guard/validation/secret-free/CAS/审计/旁路闭合是交付前硬门。若任一门无法满足，pricing不得启用，可单独交付policy并明确未完成范围。

生产管理员将来使用已部署功能保存策略/价格，当然会有被授权的业务DB mutation；`PRODUCTION_MUTATION_REQUIRED_FOR_IMPLEMENTATION: NO`表示开发、实现及验收无需先改生产数据，不否认功能本身是写控制面。部署和生产配置仍需独立授权。

本轮仅源码/报告审阅与文档一致性检查；不重复运行产品测试、不宣称新增gate PASS。既有U1/U2验收作为用户接受基线保留。仅提交本文与AGENTS.md后停止，不实施U3，不解封修复backlog。
