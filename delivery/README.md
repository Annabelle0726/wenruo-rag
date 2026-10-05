# 客户交付环境

本目录是 Python 后端、预构建前端和独立依赖的唯一客户启动入口。原部署的 Compose 配置、Git 历史、日志、账号及凭据不属于交付内容。

## 三类交付物

- 源码：干净发布仓库及其源码 ZIP，含 Python 后端、Web 前端、完整 Dockerfile、迁移与隔离脚本；不含 `.git` 历史、运行配置、模型 Key、业务 PDF 或密码。
- 镜像：由该发布源码的 Dockerfile 以 `WEB_DIST_MODE=prebuilt` 构建。镜像清单记录 SHA256；使用固定摘要，不以 `latest` 判定版本。依赖镜像也需要随离线交付包导出。
- 业务数据：format=2 的白名单包，含 `database.json`、ES JSONL 与映射、关联对象和 SHA256 清单。不是全库 SQL dump。旧 `business-data` 不是本交付物。

## 从源码构建

先安装 Docker 和 Node.js 22。在 `web` 执行 `npm ci`，设置 `NODE_OPTIONS=--max-old-space-size=4096`、`VITE_BUILD_SOURCEMAP=false` 和 `VITE_MINIFY=esbuild` 后执行 `npm run build`。回到根目录：

```powershell
$revision = git rev-parse HEAD
docker build --build-arg WEB_DIST_MODE=prebuilt --build-arg SOURCE_COMMIT=$revision -t wenruo:customer-release .
```

这是完整 Dockerfile 构建，不能通过覆盖旧应用镜像内的少数文件替代。首次构建需要网络下载锁定的依赖。

## 客户首次部署与恢复

解压源码与已验证业务包；离线部署先 `docker load -i images.tar`。在源码根目录执行（Python 3.10+，初始化脚本仅用标准库）：

```powershell
python delivery/manage.py init --project wenruo-delivery-customer01 --image wenruo:customer-release --revision <发布提交> --package C:/wenruo/business-data
python delivery/manage.py start
```

默认 Web 端口 9222；若验收机器已占用，初始化时指定 `--port 19222`。数据库、ES、MinIO、Redis 不向宿主机暴露端口。项目名必须唯一且以 `wenruo-delivery-` 开头。容器、网络、卷均隔离并绑定本次初始化标记；发现已有资源或配置密码发生变化就拒绝启动。

启动完整依赖并等待后端 `/api/v1/system/version` 真正就绪后，脚本才恢复资料、创建唯一账号 `admin@wenruo.local`，赋予超级管理员及目标工作区 Owner 权限。密码由客户本机随机生成，存于 `delivery/private/admin-password.txt`。服务密码、会话签名密钥、登录 RSA 私钥同样只在本机生成。不要打包或上传 `delivery/private`。不要将整个工作目录交给客户。

重复运行 `start` 校验恢复回执和数据，不新增账号、不重置密码。密码文件与数据库不一致时拒绝恢复。中途失败可在同一配置、同一包上重试；跨包和非空未知环境会被拒绝。不要执行 `docker compose down -v`，也不要手工改密码文件或用其他目录的 `.env` 替换。

模型名称和绑定保留，所有提供商实例凭据和地址为空；管理员须在模型设置中自行配置。未配置时应用应明确提示模型配置缺失。登录必须由页面公开获取本机公钥，不再使用仓库内固定私钥。

## 业务范围与 Wiki

正式资料仅三个知识库：海底电力电缆、电力电缆、架空绝缘导线。助手每组只保留一个经确认的较早正式副本，排除 QA、Test 和重复副本。

Wiki 来自停止的测试栈数据卷的只读副本。发布指针、579 篇非空正文、6 份源文档及 314 条源切片均经核对；源切片 ID 和正文与正式资料一致。16,135 是 Wiki 各类记录总数，不能表述成篇数。保留工作区自有编译管道、模板组及模板，但不改变正式文档的解析绑定，不触发任务。Wiki 历史向量 1024 维、文档向量 3072 维分别保留，不做转换。旧用户操作历史和页面版本评论不迁移。

导出白名单在 `policy.py`；嵌套配置中的凭据字段清空，自由文本出现已知秘密则阻断导出。PDF 原始字节、可提取正文与元数据均扫描；图片仅复制切片显式引用的对象。`scan.py` 只报告命中文件名，不输出秘密。源码 ZIP 必须从已审核 Git 提交生成，业务 ZIP 必须只包含 manifest 列出的文件。不得把扫描所用已知秘密清单交付。

## 验收

`transfer.py verify` 校验账号、Owner、空聊天/Token 表、空模型 Key、数量、映射及对象哈希。交付验收还必须实际登录，打开 PDF、切片、元数据、Wiki，核对助手绑定与缺模型提示；未登录访问受保护页面应进入登录页。以独立验收报告为准，仅导出成功或容器 Started 不代表交付完成。
