# MockFastAPI

供本地 Agent 集成测试使用的人员目录、请假审批、OAuth 和 MCP Mock 服务。HTTP 文档在 `http://127.0.0.1:8000/docs`，MCP Streamable HTTP 端点在 `http://127.0.0.1:8000/mcp`。

## 准备依赖

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、MySQL 和 Redis。以下示例在 Windows PowerShell 中执行。若本机已有 MySQL 和 Redis，可直接使用，跳到“配置”。也可以用 Docker 启动依赖：

```powershell
$MySqlPassword = Read-Host 'MySQL root password'
$RedisPassword = Read-Host 'Redis password'
docker run -d --name mockfastapi-mysql -e "MYSQL_ROOT_PASSWORD=$MySqlPassword" -e MYSQL_DATABASE=mockfastapi -p 3306:3306 mysql:8.4
docker run -d --name mockfastapi-redis -p 6379:6379 redis:7 redis-server --requirepass $RedisPassword
```

测试需要独立的 `mockfastapi_test` schema。Docker 环境可创建如下：

```powershell
docker exec mockfastapi-mysql mysql -uroot "-p$MySqlPassword" -e 'CREATE DATABASE IF NOT EXISTS mockfastapi_test CHARACTER SET utf8mb4;'
```

## 配置与初始化

服务读取环境变量，也可读取仓库根目录的 `.env`。以 `.env.example` 为起点配置 `DATABASE_URL`、`REDIS_URL`；`.env` 已被 Git 忽略。下面用环境变量演示，密码换成自己的实际值，Redis URL 中的 `/15` 是隔离的测试 DB：

```powershell
$env:DATABASE_URL = "mysql+asyncmy://root:${MySqlPassword}@127.0.0.1:3306/mockfastapi_test"
$env:REDIS_URL = "redis://:${RedisPassword}@127.0.0.1:6379/15"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
$env:TEST_REDIS_URL = $env:REDIS_URL
uv sync
uv run alembic upgrade head
uv run python -m mockfastapi.cli reset
```

日常初始化可用 `uv run python -m mockfastapi.cli seed`，只补齐缺失的固定样本。`reset` 会删除当前配置库中的人员与请假数据，并清除当前 Redis DB 中 `mockfastapi:*` 键，然后重建固定样本；执行前确认 URL 指向可重置的 Mock 环境。迁移针对 `DATABASE_URL`，`seed` 和 `reset` 也使用当前 `DATABASE_URL` 与 `REDIS_URL`。

固定用户包括 `alice`（员工）、`bob`（主管）、`carol`、`frank`（主管）、`kate`（HR）和 `leo`（管理员），共 12 人；密码均为 `TestPass123!`。初始请假单有 `1001` 至 `1004`。预置 OAuth 客户端为 `test-client` / `test-secret`，可通过 `OAUTH_CLIENT_ID` 和 `OAUTH_CLIENT_SECRET` 覆盖。OAuth 的 `password` grant 仅用于本地测试，不适合作为生产登录方案。

## 启动与检查

前台调试：

```powershell
uv run uvicorn mockfastapi.app:create_app --factory --host 127.0.0.1 --port 8000
```

后台运行时，在同一个已设置环境变量的 PowerShell 中执行；标准输出和错误日志分别写入仓库根目录：

```powershell
$stdout = Join-Path (Get-Location) 'mockfastapi.stdout.log'
$stderr = Join-Path (Get-Location) 'mockfastapi.stderr.log'
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
$server = Start-Process -FilePath $python `
  -ArgumentList @('-m','uvicorn','mockfastapi.app:create_app','--factory','--host','127.0.0.1','--port','8000') `
  -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
  -WindowStyle Hidden -PassThru
$server.Id
Get-Content $stderr -Tail 30
```

后台命令通过虚拟环境中的 Python 启动服务。在同一 PowerShell 中执行 `Stop-Process -Id $server.Id` 停止这次启动的服务。服务就绪检查为 `http://127.0.0.1:8000/health/ready`，Swagger UI 为 `http://127.0.0.1:8000/docs`。`/health/ready` 只有在 MySQL、Redis 均可连接时才返回 200。

服务运行且刚执行 `reset` 后，用冒烟脚本检查登录、人员查询、请假创建/修改/审批、撤回、刷新、MCP 调用及登出。脚本会写入测试数据，因此应在隔离环境使用；失败时退出码非零。可用 `MOCKFASTAPI_BASE_URL` 指定其他服务地址。

```powershell
uv run python scripts/smoke.py
uv run pytest -v
```

`pytest` 默认指向 `mockfastapi_test` 和 Redis DB 15；如果有密码，务必像上例设置 `TEST_DATABASE_URL`、`TEST_REDIS_URL`。测试会重置这两个隔离存储中的 Mock 数据。

## HTTP 与 MCP

HTTP OAuth 端点为 `POST /oauth/token`、`POST /oauth/revoke`、`POST /oauth/introspect`，用户端点为 `GET /auth/me`、`POST /auth/logout`。三个 OAuth 端点只接受 `application/json` 请求体，客户端凭据仍通过 `Authorization: Basic` 提交。例如：

```powershell
$basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('test-client:test-secret'))
$headers = @{Authorization="Basic $basic"}
$tokens = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/oauth/token' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{grant_type='password'; username='alice'; password='TestPass123!'} | ConvertTo-Json)
$token = $tokens.access_token
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/people' -Headers @{Authorization="Bearer $token"}
$refreshed = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/oauth/token' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{grant_type='refresh_token'; refresh_token=$tokens.refresh_token} | ConvertTo-Json)
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/oauth/introspect' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{token=$refreshed.access_token} | ConvertTo-Json)
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/oauth/revoke' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{token=$refreshed.refresh_token} | ConvertTo-Json)
```

对应的 curl 登录示例：

```sh
curl -u test-client:test-secret -H 'Content-Type: application/json' \
  -d '{"grant_type":"password","username":"alice","password":"TestPass123!"}' \
  http://127.0.0.1:8000/oauth/token
```

人员接口为 `GET /people`、`GET /people/{person_id}`；请假接口为 `GET/POST /leaves`、`GET/PATCH /leaves/{leave_id}`、`POST /leaves/{leave_id}/decision` 与 `POST /leaves/{leave_id}/withdraw`。所有业务接口使用 Bearer access token。审批人用 `decision: "approved"` 或 `"rejected"` 作决定。

MCP 使用同一进程与数据。`sso_login`、`sso_refresh` 工具接收客户端凭据；其他工具从 MCP HTTP 请求的 `Authorization: Bearer <access_token>` 读取令牌。登录后应带着令牌建立新 MCP 连接。工具清单、参数、错误约定和 Python 客户端示例见 [MCP 文档](docs/mcp.md)。
