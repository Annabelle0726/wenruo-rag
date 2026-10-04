# Wiki 安全生成与操作说明

## 实际入口和权限

知识库 → 文件 → 上传；在文件列表启动解析，等待启用文件全部解析完成。知识库 → 配置 → 解析方法中选择/关联数据管道。选择器只查询 `dataflow_canvas`，但“创建数据管道”跳到 `/agents`，因为数据管道、智能体流程、编译模板共用管理列表与画布。它不要求创建聊天助手。

配置者先在模型服务配置可用的聊天和嵌入模型；模型服务管理仅 OWNER/ADMIN。知识库创建者或该工作区 OWNER/ADMIN 可绑定管道、解析、生成和更新；只有读取权限的成员只能阅读。后端再次校验权限，页面隐藏不是授权边界。

已有管道直接打开检查：Compiler（编译器）的模型和编译模板组必须有效，模板组包含 Wiki 模板。没有模板时在共用管理页使用“添加模板”；没有管道才使用“创建数据管道”。知识库及文件须绑定有效管道，不能只创建一个未绑定的画布。

## 普通用户步骤

1. 打开知识库的“文件”，点击“上传”，按文件列表操作启动解析，等到解析成功。
2. 打开“知识成果”，查看“生成准备与使用说明”：已解析文件、生成管道、编译模板、模型配置。缺项用“查看配置”；没有配置权限时联系知识库创建者/工作区管理员。
3. 首次点击“生成”。已有成果且文件解析完成后点击“更新”。已有管道不必重建；不要以“清空”代替更新。
4. 生成期间继续阅读旧版。只有完整生成、源快照未变化、版本保存成功后才切换。模型服务限流时稍后重试；模板失效时先由配置者处理。

## 页面文案（随界面语言切换）

中文：先上传并解析文件，再绑定包含 Compiler 的数据管道和 Wiki 编译模板。管道与聊天 Agent 共用编辑入口，但不是聊天助手；已有管道直接检查和使用，无需重建。

English: Upload and parse files, then bind a data pipeline with a Compiler and a Wiki template. Pipelines share the Agent editor but are not chat assistants. Check and reuse an existing pipeline instead of creating another one.

中文：新版本独立生成，模型变化时重建，不混用向量。配置检查不代表服务配额可用。生成期间旧版持续可读，验证成功后才切换。

English: New versions are built separately; a model change rebuilds the Wiki without mixing vectors. Configuration checks do not verify provider quota. Previous results remain readable until the new version is validated and published.

## 实现与边界

`common/wiki_generation.py` 将编译隔离在保留真实 ES mapping 的私有索引；模型变化触发的清空只影响该私有副本。SQL `wiki_generation` 指针和页面版本记录在同一事务中发布。普通读取通过指针定位，旧物理成果保留。并发编辑/清空与生成互斥；缺配置时 API 拒绝入队，页面按钮禁用。

适用 Elasticsearch。非 ES 后端禁止该安全生成入口。配置检查不发模型调用、不替用户切换模型。失败暂存索引与旧代保留，尚无自动清理；需要容量管理。进程被强制杀死时旧成果仍安全，但数据库互斥 token 可能残留，须管理员确认没有任务运行后处理，不能自动抢占仍存活任务。没有跨 ES/SQL 的分布式事务：发布先确认完整索引，然后原子切换 SQL 指针；失败对象可能保留但不会发布。

## 9224 数据差异（只读核查，不恢复）

FREEZE.md 记录579页面；本轮开始实际原知识库 Wiki 页面为0。未恢复、改绑或触发该知识库生成。

- 模板组 `cb12287862ff407b8cd888298c249640`：status=0，创建2026-10-03 17:23:49，更新17:55:01。
- Wiki 模板 `99fcb86ab558480f93acb9c3b1744b50`：status=0，所属上述组，同样创建17:23:49、更新17:55:01。
- Pipeline `3ab59da173bd4086ab4ce2d97c8c98fa`：dataflow_canvas，创建17:23:49，更新17:59:37；表无status列。DSL仍引用上述组，知识库和6份文件仍绑定该Pipeline。
- workspace_audit 未找到包含这三个ID的记录，不能据此推断操作者。

隔离测试自行创建有效模板、管道、文件与知识库，控制注入429/中途失败/取消/失效模板/版本存储失败，使用测试栈真实ES、MySQL和MinIO验证保留与成功切换；不是成功执行整套真实LLM生成的证明。

## 构建边界

仅从本修复提交构建。Dockerfile使用完整后端源码与锁定依赖、在镜像内构建前端，不以旧应用镜像覆盖文件。依赖资源镜像固定digest；SOURCE_COMMIT写入VERSION。只更新9224 app服务，保留所有卷、生产和latest。主工作区 invitation_service.py 及其他并发未提交内容不在本修复中。
