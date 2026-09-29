多数客户未必自建 GPU，第一阶段以 Managed API + Private Endpoint 框架为主，私有算力/GPU 监控以后再补
还有一个关键判断：“查看 API Key 剩余额度”不能设计成所有 Provider 都必须支持。
不同厂商差异非常大。例如 DeepSeek 官方确实提供 /user/balance，可以查账户可用余额，但这仍是“账户余额”，不等于每个 API Key 独立 quota。DeepSeek API Docs OpenAI 有组织级 Usage/Costs API，并且 Usage 可以按 api_key_id 聚合，但这也更接近“历史消耗统计”，不等于一个统一的“这个 key 还剩 37% 配额”接口。OpenAI Platform SiliconFlow 更明确：Rate Limit 是账户级而不是 API Key 级，而且按模型分别限制。SiliconFlow
所以不要做一个假的统一字段：
API Key Remaining = 37%
而要做 Provider Capability Adapter：
Provider Capability
├── supports_balance_query
├── supports_usage_query
├── supports_cost_query
├── supports_rate_limit_metadata
└── supports_health_observation
比如：
DeepSeek
Balance Query      Supported
Usage Query        Limited
Health Observation Supported

OpenAI
Usage Query        Supported
Costs Query        Supported
Balance Remaining  Not exposed as this concept

Private vLLM
Balance Query      N/A
Usage Query        Internal only
Health Observation Supported
这样你的产品不会被某一家 Provider 的 API 形态绑死。
你提的 Nav 铃铛也很适合。我会把它做成统一 Notification Center，但第一版不用邮件：
🔔 3

- Workspace 月度 Token 已使用 90%
- DeepSeek Provider 最近连续失败 5 次
- Embedding 服务当前不可用
它消费的是已经经过归一化的内部事件，不是直接把 provider error body 塞进去。
结合 Codex U0 审查，我建议现在正式把路线调整成下面这样。U0 已经发现：现有 ledger 缺少 provider、key instance、workload attribution，所以历史数据无法凭查询准确重建；同时还有 OCR bypass、detached initiator 丢失、部分 settlement 不完整和 identity-domain 问题。因此不能直接跳进“完整 Dashboard”。 粘贴的文本 (1)
我会采用：
U0.5 → U1 → U2 → U3 → U4 → U5 → U6 → U7 → U8
其中最先把你现在想看到的 UI 框架搭出来，但不造假数据。
下面这份可以作为你接下来给 DSH/Codex 的总工作说明。实际执行时一次只发一个 Stage，不要让它跨阶段。
Workspace AI Usage & Provider Reliability
Product Goal
Build a provider-agnostic enterprise control and observability layer for wenruo-rag.
The product must support both:
Managed API providers
DeepSeek
SiliconFlow
Gemini
OpenAI
other compatible providers
Private / On-Prem endpoints
vLLM
TEI
Ollama
OpenAI-compatible internal gateways
Do not design the product around Gemini specifically.
The architecture must keep three domains separate:
Workspace Usage Governance
Question:
Is this member/workspace allowed to consume AI resources?
Provider Health
Question:
Can this configured model service actually serve requests right now?
Retrieval Health
Question:
What actually happened during this RAG retrieval?
These are independent facts and must never be inferred from each other.

Frozen Settings Information Architecture
Settings
│
├── 1. Model Providers
│   ├── Managed API
│   │   ├── DeepSeek
│   │   ├── SiliconFlow
│   │   ├── Gemini
│   │   └── OpenAI
│   │
│   └── Private Endpoint
│       ├── vLLM
│       ├── TEI
│       ├── Ollama
│       └── Custom / OpenAI-compatible Gateway
│
│   Each provider displays capabilities:
│   [Chat] [Embedding] [Rerank] [VLM]
│
├── 2. Team — Control Plane
│   ├── Members & Roles
│   └── Usage Policy
│       ├── Calls
│       ├── Tokens
│       └── Estimated Cost Limits
│
└── 3. Usage & Operations — Observation Plane
    ├── My Usage
    ├── Workspace Analytics
    ├── Provider Health
    └── Retrieval Health
Global navigation also gains:
Notification Bell
🔔 0 / 1 / 2 / ...
The bell represents unread operational notifications.
Initial notification delivery is in-product only.
No email, SMS or webhook implementation in the first version.

Provider Capability Principle
Do NOT assume every provider exposes:
remaining balance;
remaining quota;
per-key quota;
provider usage API;
billing API.
Define provider-level optional capabilities instead.
Example internal capability model:
supports_balance_query
supports_usage_query
supports_cost_query
supports_rate_limit_metadata
supports_health_observation
A provider adapter may support any subset.
If a provider does not expose authoritative remaining quota:
DO NOT estimate provider remaining quota from local usage.
Display:
Provider quota: Not available
instead of inventing a percentage.

Notification Principle
Notifications may originate from:
Internal Workspace Governance
Examples:
daily calls 80% used;
daily tokens 90% used;
monthly estimated-cost limit reached;
budget store unavailable.
These thresholds are authoritative because they are controlled internally.
Provider Health
Examples:
provider quota exhaustion observed;
repeated provider timeouts;
provider unavailable;
authentication failure observed;
provider rate-limited.
These are observed operational facts.
Do NOT generate:
Provider quota remaining 20%
unless the provider exposes an authoritative API for that value.
Retrieval Health
Examples:
Dense failed;
Lexical succeeded;
overall retrieval degraded.
Never infer retrieval fallback from provider failure alone.
Only say:
Lexical retrieval continued successfully
when Retrieval Health actually records lexical success.

U0.5 — Readiness Closure
Goal
Resolve the current blockers behind:
U1_IMPLEMENTATION_READY: NO
Do not implement product functionality yet.
Tasks
Freeze U1 V1 metrics to facts supported by existing authoritative storage.
Allowed V1 metrics:
attempted calls;
settled tokens;
reserved/unsettled token occupancy;
estimated model cost;
reserved/unsettled estimated-cost occupancy;
member breakdown;
daily/monthly aggregation;
workspace aggregate;
limited recorded model-name grouping where truthful.
Excluded:
historical provider attribution;
API-key-instance attribution;
workload attribution;
reconstructed historical data.
Restore repository-supported test environment.
Run the existing budget/security/detached attribution tests in a supported environment.
Do not install arbitrary host dependencies merely to make collection pass.
Validate production-safe schema shape read-only.
No secret retrieval.
Hard invariant:
API_KEY_PLAINTEXT_READS = 0
Freeze reserved / settled / unsettled accounting semantics.
Freeze authorization matrix.
Freeze terminology:
Estimated model cost
Never:
Actual provider bill
unless provider billing reconciliation exists.
Exit Gate
Return:
U1_V1_SCOPE_ACCEPTABLE:
TEST_ENVIRONMENT_READY:
PRODUCTION_SHAPE_VALIDATED:
ACCOUNTING_SEMANTICS_FROZEN:
AUTHORIZATION_MATRIX_FROZEN:
COST_TERMINOLOGY_FROZEN:
API_KEY_PLAINTEXT_READS: 0
U1_IMPLEMENTATION_READY:
Stop.

U1 — Usage Read Model
Goal
Expose trustworthy workspace/member usage from existing authoritative accounting records.
Do not redesign billing.
Required backend views
workspace_summary
my_usage
member_breakdown
daily_series
monthly_series
quota_status
recorded_model_breakdown
Required metrics
Where authoritative:
attempted_calls
settled_tokens
outstanding_reserved_tokens
estimated_cost_micros
outstanding_reserved_cost_micros
Also expose:
cost_coverage:
  complete
  partial
  unavailable
Do not render missing pricing as known $0.
Authorization
NORMAL:
own authorised usage only.
OWNER / ADMIN:
workspace aggregate;
member breakdown;
current workspace only.
Reconciliation Gate
For identical scopes:
sum(member_breakdown) == workspace_total
subject to the exact same accounting semantics.
Stop Condition
Do not build UI yet.

U2 — Settings UI Framework
Goal
Build the final navigation and page skeleton before adding all features.
Implement:
Settings
├── Model Providers
├── Team
└── Usage & Operations

Model Providers
Split display into:
Managed API
Private Endpoint
Each Provider card may show:
Provider Name
Type
Configured Model
Capabilities
Connection Configuration
Status Placeholder
Capabilities:
Chat
Embedding
Rerank
VLM
Do not implement fake provider balance yet.
Team
Existing Members & Roles remain.
Add:
Usage Policy
for existing backend-supported limits only.
Usage & Operations
Create tabs:
My Usage
Workspace Analytics
Provider Health
Retrieval Health
At this stage Provider Health may be an honest empty/coming-data state.
Do not fabricate metrics.
Global Notification Bell
Add navigation shell:
Bell Icon
Unread Count Badge
Notification Drawer
Initially support a local typed notification model and UI shell.
Do not implement email/webhook.
Do not yet invent persistent notification events if no backend source exists.
Stop
Browser/UI gates only.
No Provider Health backend yet.

U3 — Usage & Quota Productisation
Goal
Connect U1 authoritative usage data to U2 UI.
My Usage
Show:
Today
Calls
Tokens

This Month
Calls
Tokens
Estimated API Cost
NORMAL users see only permitted own usage.
Workspace Analytics
OWNER/ADMIN sees:
Total Calls
Total Tokens
External API Estimated Cost
Member Breakdown
Recorded Model Breakdown
Important:
Private endpoints do NOT automatically show $0 actual cost.
Use:
External API Estimated Cost
not:
Total Infrastructure Cost
Usage Policy
Expose only backend-supported existing controls.
Examples:
Calls / rolling minute
Calls / day
Calls / month

Tokens / day
Tokens / month

Estimated Cost / day
Estimated Cost / month

Workspace timezone
Do not claim workspace-wide hard-cap semantics if enforcement is still per-member.
CSV Export
May be added only from the authoritative read model.
No direct frontend ledger queries.

U4 — Accounting Coverage Closure
This stage addresses defects discovered by U0.
Keep separate from Dashboard implementation.
Audit/fix one work item at a time:
detached initiator attribution loss;
OCR budget bypass;
incomplete settlement paths;
proven tenant/workspace identity-domain errors.
Each defect requires:
root cause
blast radius
migration impact
regression gate
live acceptance plan
Do NOT silently backfill unverifiable historical attribution.
Historical unknown stays:
unattributed

U5 — Provider Health Fact Model
Goal
Build Provider Health using real model-dispatch observations.
Default architecture:
PASSIVE_OBSERVATION_FIRST
Do NOT start with dummy requests.
Provider identity
Provider Health should attach to a stable internal model/provider instance identifier where available.
Do not require plaintext API key.
Provider Health state
Suggested normalized state:
UNKNOWN
HEALTHY
DEGRADED
UNAVAILABLE
Observations
Record sanitized operational facts:
last_success_at
last_failure_at
consecutive_failures
recent_failure_rate
recent_latency
failure_class
capability
Potential capabilities:
Chat
Embedding
Rerank
VLM
Security
Never persist/render:
plaintext API key;
provider raw body;
stack trace;
request prompt;
retrieved chunks.
Provider API Capabilities
Separately define optional adapters:
BalanceProvider
UsageProvider
CostProvider
RateLimitMetadataProvider
No adapter capability means:
Not available
—not guessed data.
Important
Do NOT change existing P0 Retrieval Health taxonomy merely for this Dashboard.

U6 — Provider Health UI
Provider Status Matrix
Example:
Provider / Endpoint       Type       Capability    Status      P95
DeepSeek V3               Managed    Chat          Healthy     620 ms
SiliconFlow BGE           Managed    Embedding     Degraded    940 ms
Private TEI               Private    Embedding     Unavailable Timeout
Allowed Admin Details
Last success
Last failure
Recent error rate
P95 latency
Sanitized failure class
Optional Provider Account Information
Only display if authoritative adapter exists.
Examples:
DeepSeek:
provider balance may be available.
Other provider:
usage may be available;
remaining quota may not be.
UI must distinguish:
Internal Usage
Provider Account Information
Provider Health
Do not merge them.
No automatic-fallback claim
Provider Health may say:
Embedding service unavailable.
It may NOT say:
System switched to Lexical.
unless Retrieval Health provides that exact observed fact.

U7 — Notification Center & Alerts
Goal
Activate the previously created Nav bell.
Notification Event Model
Minimal categories:
USAGE_WARNING
USAGE_DENIED
PROVIDER_DEGRADED
PROVIDER_UNAVAILABLE
RETRIEVAL_DEGRADED
SYSTEM_WARNING
Each notification should support:
id
workspace_id
category
severity
title_key
created_at
read_at
source_ref
Avoid storing duplicated raw provider errors.
Internal quota thresholds
Because internal quotas are authoritative, support configurable or frozen thresholds such as:
80%
90%
100%
Avoid repeated alerts within the same quota period through deduplication.
Provider alerts
Use observed health:
consecutive failures
failure rate
unavailable duration
Do not create 20%/10% remaining-provider-quota alerts unless authoritative provider data exists.
Bell UX
🔔      no unread
🔔 ●    unread
🔔 3    three unread
Drawer:
Provider unavailable
5 minutes ago

Monthly token usage reached 90%
2 hours ago
Support:
Mark as read
Mark all as read
Open relevant Settings page
No email/webhook in V1.

U8 — Cross-Layer Acceptance
Validate that the layers remain independent.
Required scenarios:
Scenario A — Internal quota exhausted, Provider healthy
Expected:
Workspace Budget: denied
Provider Health: healthy
No provider failure invented
Scenario B — Workspace budget available, Provider unavailable
Expected:
Workspace Budget: available
Provider Health: unavailable
Retrieval Health: actual runtime result
Scenario C — Dense Provider fails, Lexical succeeds
Only if observed:
Provider Health:
Embedding unavailable

Retrieval Health:
Dense failed
Lexical succeeded
Overall degraded
UI may then honestly tell the administrator that lexical retrieval continued.
Scenario D — Private endpoint
Expected:
Usage metrics available where internally measured
Provider Health available
External API Cost: N/A
Provider Balance: N/A
Scenario E — Provider exposes balance API
Expected:
Provider account information may be displayed as authoritative external data, clearly distinguished from internal usage.
Final invariant
Workspace Usage ≠ Provider Health ≠ Retrieval Health
No layer may infer another layer's state without an explicit observed fact.

Standing Red Lines
Throughout U0.5–U8:
no API key plaintext in analytics;
no provider raw errors in ordinary UI;
no reconstructed fake historical attribution;
no fake provider remaining quota;
no assumption that private endpoint costs $0;
no retrieval fallback claim without Retrieval Health evidence;
no Gemini-specific architecture;
no email/webhook in V1;
no active provider dummy probing unless separately authorised later;
no hidden changes to P0 health contracts;
no mixing unrelated retrieval/P1 work into Usage & Operations.
我还建议把你想象中的最终 UI 稍微改成这种文案，会更企业化：
Workspace Analytics

This month
Calls                     128,400
Tokens                    42.1M
External API Est. Cost    $42.50
Usage with known pricing  84%
而不是：
Local compute share 82.4%
因为 Codex 已经证明目前 ledger 没有 provider/workload 归因，现在没有数据基础准确算这个 82.4%。 粘贴的文本 (1)
Member table 也可以变成：
Member     Calls    Tokens    External API Est. Cost
张三        42.1k    12.4M     —
李四         8.3k     2.1M     $14.20
王五        78.0k    27.6M     Partial
— / Partial 比 $0.00（纯私有） 更诚实。
最后，关于“API Key 额度是不是很难”，答案是：
统一做很难；按 Provider Capability 做，不难。
例如 DeepSeek 已经有官方余额接口，可以很自然地做 Adapter。DeepSeek API Docs OpenAI 可以查 Usage/Costs，甚至 Usage 可按 api_key_id 聚合，但产品语义应该是“usage/cost”，而不是假装存在统一的 remaining-quota。OpenAI Platform SiliconFlow 的 rate limit 明确是账户级而非 API Key 级，更说明 UI 不该叫“API Key 剩余额度”。SiliconFlow
所以最终建议把这个模块命名成：
Provider Account & Limits
而不是：
API Key Quota
里面按 Provider 能力动态显示：
Balance        ¥86.20          // if supported
Usage          1.2M tokens     // if supported
Rate Limit     2000 RPM        // if supported
Remaining      Not available   // honest
Health         Healthy         // passive observations
这样你以后接 DeepSeek、SiliconFlow、OpenAI、政府客户的私有模型网关，都不用重新设计 Settings
