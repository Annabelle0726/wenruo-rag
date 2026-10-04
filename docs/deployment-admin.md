# 部署配置与验收管理员

## 新机器初始化

在项目根目录执行：

```powershell
python tools/scripts/initialize_deployment.py
```

脚本从 `docker/.env.example` 创建本机 `docker/.env`，为数据库、对象存储和缓存生成独立的随机密码。管理员邮箱为 `admin@wenruo.local`；密码保存在本机 `delivery-private/admin-password.txt`。这些文件不会进入 Git 或 Docker 镜像。

已存在的 `.env` 不会被覆盖。现有 MySQL 和 Elasticsearch 需要先在服务内部修改密码，再同步应用配置，不能只替换环境文件。保留现有数据库名、索引名、Compose 项目名和数据卷。

## 完整构建与启动

先在 `web` 目录执行 `npm ci` 和 `npm run build`，然后回到项目根目录：

```powershell
docker compose -f docker/docker-compose.yml build --build-arg WEB_DIST_MODE=prebuilt
docker compose -f docker/docker-compose.yml --profile cpu up -d --force-recreate wenruo-rag-cpu
python tools/scripts/initialize_deployment.py --seed
```

默认网页地址为 http://127.0.0.1:9222 。构建镜像和启动容器是两个步骤；只构建不会替换正在运行的容器。

seed 创建超级管理员及其自己的工作区，角色为 Owner。它不会调用模型提供方，不会创建 API Key，也不会复制原机器的用户或聊天记录。重复执行不会重置密码，也不会重复创建账号。首次登录后可在个人设置修改密码；以后不应再用旧初始化密码执行 seed。

## 本机已有资料的验收

如果需要让新管理员查看已有工作区，可明确指定该工作区：

```powershell
python tools/scripts/initialize_deployment.py --seed --workspace-id <现有工作区ID>
```

新管理员在该现有工作区中获得 Admin 权限，现有 Owner 和资料归属保持原样。可管理团队并创建邀请链接；邀请链接可由管理员自行转交，不依赖 SMTP。发送邀请邮件和找回密码需要另行配置真实邮箱服务。

`admin@wenruo.local` 是本地初始化登录名，不是可收邮件的真实邮箱。

## 数据交付

Git 源码和 Docker 镜像不包含数据库中的业务数据。PDF、解析切片、向量、元数据和选定助手仍须通过独立的数据导出与恢复流程交付；不能把完整本机数据库直接交给客户，因为其中可能包含个人账号、聊天记录和模型凭据。

密码改名不等于数据库或索引改名。现有 `rag_flow` 数据库和 `ragflow_*` 索引可继续使用，它们的名称不会显示为产品品牌。
