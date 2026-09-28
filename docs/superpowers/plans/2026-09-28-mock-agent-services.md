# Mock Agent 服务实施计划

> **供执行者使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。使用 `- [ ]` 复选框跟踪步骤。

**目标：** 构建可在本地运行的 FastAPI Mock 服务，通过 HTTP 和 MCP 提供 OAuth2 风格的 SSO、人员目录与假勤流程，支持可重复的 Agent 集成测试。

**架构：** 一个 ASGI 进程包含 `auth`、`people`、`leave`、`mcp` 四个模块。HTTP 与 MCP 适配层调用同一组业务函数。MySQL 持久化人员和假勤单据；Redis 保存短期有效且可撤销的不透明令牌。

**技术栈：** Python 3.12、uv、FastAPI、Pydantic、SQLAlchemy 2 异步接口、Alembic、asyncmy、redis-py asyncio、使用 Argon2 的 pwdlib、官方 Python MCP SDK、pytest/httpx。

**设计依据：** `docs/superpowers/specs/2026-09-28-mock-agent-services-design.md`

## 全局约束

- 本项目只用于本地及受控测试环境；OAuth2 `password` grant 仅用于此目的，文档须明确说明其不适用于真实 SSO。
- 全面使用 `leave` 命名：HTTP 集合路径为 `/leaves`，路径参数为 `leave_id`，MCP 工具为 `create_leave`、`list_leaves`、`get_leave`、`update_leave`、`decide_leave`、`withdraw_leave`。
- 一个 FastAPI 应用提供 `/docs`、`/openapi.json` 和 Streamable HTTP `/mcp`；无需网页界面。
- 预置约 12 名稳定的测试人员，覆盖至少三个部门及员工、主管、HR、管理员角色。显式 CLI 重置命令恢复确定的人员和样例单据。
- 访问令牌有效期为 30 分钟，刷新令牌有效期为 7 天；刷新时轮换令牌，登出时撤销整个会话。
- API 时间必须带时区，入库时使用 UTC。`days` 由调用方提供，必须是正十进制数，不计算日历天数。
- 使用少量针对常见流程的测试和一个冒烟脚本，不建立庞大的单测矩阵。

## 审查重点

1. 刷新令牌轮换后再次使用必须返回 `invalid_grant`；由任务 3 的刷新测试验证。
2. 用户即使知道无权查看的单据 ID，也只能收到 `404`，不能获得单据详情；由任务 4 的 ACL 测试和任务 5 的 HTTP 测试验证。
3. 无时区时间，以及结束时间早于开始时间的输入，必须在入库前被拒绝；由任务 4 的校验测试验证。
4. 申请人将自己指定为审批人时必须被拒绝；由任务 4 的创建测试验证。
5. 终态单据再次修改、审批或撤回时必须返回 `409`；由任务 4 的状态转换测试验证。

---

## 文件分工

| 路径 | 职责 |
| --- | --- |
| `pyproject.toml`、`uv.lock`、`.env.example` | Python 依赖和本地配置约定 |
| `src/mockfastapi/config.py`、`db.py`、`cache.py`、`app.py` | 配置、MySQL/Redis 连接、ASGI 应用组装和就绪检查 |
| `alembic.ini`、`alembic/env.py`、`alembic/versions/*.py` | 数据库迁移 |
| `src/mockfastapi/people/{models,schemas,service,seed,http}.py` | 人员模型、目录、固定数据和 HTTP 适配层 |
| `src/mockfastapi/auth/{schemas,service,http}.py` | 令牌生命周期、身份查找和 OAuth HTTP 适配层 |
| `src/mockfastapi/leave/{models,schemas,service,http}.py` | 假勤状态、ACL 和 HTTP 适配层 |
| `src/mockfastapi/mcp_server.py` | MCP 工具和请求中的 Bearer 令牌提取 |
| `src/mockfastapi/cli.py` | 初始化与显式重置命令 |
| `tests/conftest.py`、`tests/test_*.py` | 精简的集成测试夹具和行为检查 |
| `docs/mcp.md`、`README.md` | 工具契约、配置、调试、后台运行和冒烟示例 |

### 任务 1：可运行应用与依赖就绪检查

**文件：** 新建 `pyproject.toml`、`uv.lock`、`.env.example`、`src/mockfastapi/{__init__,config,db,cache,app}.py`、`tests/{conftest,test_bootstrap}.py`。

**接口：** 在 `config.py` 提供 `Settings`；在 `db.py` 提供 `get_session() -> AsyncIterator[AsyncSession]`；在 `cache.py` 提供 `get_redis() -> Redis`；在 `app.py` 提供 `create_app() -> FastAPI`。后续任务复用这些接口。默认地址为 `127.0.0.1:3306` 和 `127.0.0.1:6379`，凭据由 `.env` 提供。

- [ ] **步骤 1：在 `tests/test_bootstrap.py` 编写 `test_readiness_reports_mysql_and_redis`。** 配置本地测试数据库和 Redis，断言 `GET /health/ready` 返回 `200` 且两个依赖均就绪。测试配置须与开发数据隔离。
- [ ] **步骤 2：运行 `uv run pytest tests/test_bootstrap.py -v`。** 应因应用和路由尚不存在而失败。
- [ ] **步骤 3：实现上述接口和就绪端点。** 添加 Python 3.12 版本约束、依赖、`.env.example` 和 `uv.lock`。端点检查两个依赖；任一不可用时，返回 `503` 和稳定的错误体。
- [ ] **步骤 4：运行 `uv run pytest tests/test_bootstrap.py -v` 和 `uv run python -c "from mockfastapi.app import create_app; print(create_app().title)"`。** 测试应通过，并输出应用标题。
- [ ] **步骤 5：提交。** 执行 `git add pyproject.toml uv.lock .env.example src/mockfastapi tests` 和 `git commit -m "feat: bootstrap mock service"`。

### 任务 2：数据库结构、人员数据与确定性重置

**文件：** 新建 `alembic.ini`、`alembic/env.py`、`alembic/versions/0001_initial.py`、`src/mockfastapi/people/{models,schemas,service,seed}.py`、`src/mockfastapi/leave/models.py`、`src/mockfastapi/cli.py`、`tests/test_seed.py`。

**接口：** 提供 SQLAlchemy 模型 `Person` 和 `Leave`，以及 `PersonOut`；提供 `async list_people(session: AsyncSession, *, limit: int, offset: int) -> list[Person]`、`async get_person(session: AsyncSession, person_id: int) -> Person | None`、`async seed(session: AsyncSession, *, reset: bool, redis: Redis) -> None`。`python -m mockfastapi.cli seed` 补齐缺失的固定数据；`python -m mockfastapi.cli reset` 删除 Mock 数据和令牌，再恢复固定数据。预置人员和样例单据使用稳定的数值 ID。

- [ ] **步骤 1：在 `tests/test_seed.py` 编写 `test_seed_is_idempotent_and_reset_restores_fixed_records`。** 断言约有 12 名人员、至少三个部门及四种角色；连续运行两次初始化后数量不变；额外创建一张单据，重置后断言该单据消失，固定 ID 和四种样例状态恢复。
- [ ] **步骤 2：运行 `uv run pytest tests/test_seed.py -v`。** 应因模型和 CLI 尚不存在而失败。
- [ ] **步骤 3：实现模型、首个 Alembic 迁移、固定数据和 CLI。** Person 包含稳定的 `id`、`username`、`name`、`department`、`level`、`role`、密码哈希；Leave 包含设计文档中的所有字段。重置按事务依赖顺序删除数据，只清理本应用前缀下的 Redis 键。
- [ ] **步骤 4：运行 `uv run alembic upgrade head` 和 `uv run pytest tests/test_seed.py -v`。** 迁移和测试均应通过。
- [ ] **步骤 5：提交。** 执行 `git add alembic.ini alembic src/mockfastapi/people src/mockfastapi/leave/models.py src/mockfastapi/cli.py tests/test_seed.py` 和 `git commit -m "feat: add personnel fixtures and reset"`。

### 任务 3：OAuth 令牌生命周期与身份识别

**文件：** 新建 `src/mockfastapi/auth/{__init__,schemas,service,http}.py`、`tests/test_auth.py`；修改 `src/mockfastapi/app.py`、`src/mockfastapi/config.py`。

**接口：** 在 `schemas.py` 提供 `Principal(id: int, username: str, role: str)` 和 `TokenPair(access_token: str, refresh_token: str, expires_in: int)`。服务函数为 `authenticate_client(client_id: str, client_secret: str, settings: Settings) -> None`、`async issue_password_tokens(session: AsyncSession, redis: Redis, username: str, password: str) -> TokenPair`、`async refresh_tokens(redis: Redis, refresh_token: str) -> TokenPair`、`async principal_for_access(redis: Redis, token: str) -> Principal`、`async revoke_token(redis: Redis, token: str) -> None`、`async logout(redis: Redis, token: str) -> None`、`async introspect(redis: Redis, token: str) -> dict[str, bool | int | str]`。HTTP 和 MCP 在执行密码登录、刷新、撤销或令牌校验前，均须认证预置测试客户端。无效授权与凭据映射为明确的领域异常。HTTP 路由为 `/oauth/token`、`/oauth/revoke`、`/oauth/introspect`、`/auth/me`、`/auth/logout`。

- [ ] **步骤 1：在 `tests/test_auth.py` 编写 `test_password_refresh_replay_logout` 和 `test_client_and_user_credentials`。** 断言表单令牌响应为 Bearer，且 `expires_in=1800`；刷新返回新令牌对，即使两个刷新请求竞争，旧刷新令牌也只能成功使用一次；登出后新访问令牌失效；错误的客户端或用户凭据不能获得令牌。
- [ ] **步骤 2：运行 `uv run pytest tests/test_auth.py -v`。** 应因路由尚不存在而失败。
- [ ] **步骤 3：实现 Schema、Redis 会话与令牌映射、Argon2 密码校验、Basic 客户端认证及 OAuth HTTP 路由。** 使用 Redis 事务或 Lua 脚本原子地消耗刷新令牌，避免并发重放签发两组令牌。Redis TTL 分别为 30 分钟和 7 天；业务错误返回稳定的 `code` 和 `message`。
- [ ] **步骤 4：运行 `uv run pytest tests/test_auth.py -v`。** 所有认证测试应通过。
- [ ] **步骤 5：提交。** 执行 `git add src/mockfastapi/auth src/mockfastapi/app.py src/mockfastapi/config.py tests/test_auth.py` 和 `git commit -m "feat: implement mock OAuth token lifecycle"`。

### 任务 4：假勤业务规则

**文件：** 新建 `src/mockfastapi/leave/{__init__,schemas,service}.py`、`tests/test_leave_service.py`。

**接口：** 提供 Pydantic Schema `LeaveCreate`、`LeavePatch`、`LeaveDecision`、`LeaveOut`。服务函数为 `async create_leave(session: AsyncSession, actor: Principal, data: LeaveCreate) -> Leave`、`async list_leaves(session: AsyncSession, actor: Principal, status: str | None, limit: int, offset: int) -> list[Leave]`、`async get_leave(session: AsyncSession, actor: Principal, leave_id: int) -> Leave`、`async update_leave(session: AsyncSession, actor: Principal, leave_id: int, data: LeavePatch) -> Leave`、`async decide_leave(session: AsyncSession, actor: Principal, leave_id: int, data: LeaveDecision) -> Leave`、`async withdraw_leave(session: AsyncSession, actor: Principal, leave_id: int) -> Leave`。共享领域异常表示无效输入、无权操作、记录不存在或不可见，以及状态冲突。

- [ ] **步骤 1：编写聚焦的服务测试。** `test_create_rejects_self_approver_and_invalid_time` 检查自我审批、无时区时间和时间倒置；`test_visibility_and_approver_acl` 检查只有申请人、指定审批人及管理员可见，且无权查看的 ID 返回未找到；`test_terminal_transitions_conflict` 检查终态单据再次修改、审批或撤回时发生冲突。
- [ ] **步骤 2：运行 `uv run pytest tests/test_leave_service.py -v`。** 应因服务尚不存在而失败。
- [ ] **步骤 3：实现 Schema、数据校验、ACL 和状态转换。** 申请人来自 `Principal`；审批人必须是主管或 HR；`days > 0`；时间按 UTC 入库；只有 `pending` 状态可修改。每次变更使用一个数据库事务。
- [ ] **步骤 4：运行 `uv run pytest tests/test_leave_service.py -v`。** 所有假勤服务测试应通过。
- [ ] **步骤 5：提交。** 执行 `git add src/mockfastapi/leave tests/test_leave_service.py` 和 `git commit -m "feat: implement leave workflow rules"`。

### 任务 5：人员与假勤 HTTP 接口

**文件：** 新建 `src/mockfastapi/people/http.py`、`src/mockfastapi/leave/http.py`、`tests/test_http_flows.py`；修改 `src/mockfastapi/app.py`。

**接口：** HTTP 路由严格对应设计文档：`GET /people`、`GET /people/{person_id}`、`POST /leaves`、`GET /leaves`、`GET /leaves/{leave_id}`、`PATCH /leaves/{leave_id}`、`POST /leaves/{leave_id}/decision`、`POST /leaves/{leave_id}/withdraw`。全部调用任务 3 的 `principal_for_access` 与任务 4 的服务函数。人员和单据列表使用 `limit`/`offset` 分页；单据列表支持按 `status` 过滤。

- [ ] **步骤 1：在 `tests/test_http_flows.py` 编写 `test_http_create_update_decide_and_visibility`。** 分别以申请人和审批人登录；创建并修改单据；确认无关用户不能审批；指定审批人能够审批；无权查看详情时返回 `404`；`/openapi.json` 应包含全部路径。
- [ ] **步骤 2：运行 `uv run pytest tests/test_http_flows.py -v`。** 应因路由尚不存在而失败。
- [ ] **步骤 3：实现轻量 HTTP 适配层和统一异常映射。** 区分 `401`、`403`、`404`、`409`、`422`；错误体稳定包含 `code`、`message` 和可选 `details`。创建单据时不从请求中读取 `applicant_id`。
- [ ] **步骤 4：运行 `uv run pytest tests/test_http_flows.py -v`。** 测试应通过。
- [ ] **步骤 5：提交。** 执行 `git add src/mockfastapi/people/http.py src/mockfastapi/leave/http.py src/mockfastapi/app.py tests/test_http_flows.py` 和 `git commit -m "feat: expose people and leave HTTP API"`。

### 任务 6：MCP 能力对齐

**文件：** 新建 `src/mockfastapi/mcp_server.py`、`tests/test_mcp_flows.py`、`docs/mcp.md`；修改 `src/mockfastapi/app.py`。

**接口：** 在 `/mcp` 挂载 Streamable HTTP。工具包括 `sso_login`、`sso_refresh`、`sso_logout`、`sso_validate`、`list_people`、`get_person`、`create_leave`、`list_leaves`、`get_leave`、`update_leave`、`decide_leave`、`withdraw_leave`。`sso_login` 和 `sso_refresh` 通过参数接收客户端凭据；受保护工具从 MCP 请求头读取 Bearer 令牌，并调用任务 2–4 的服务函数。

- [ ] **步骤 1：在 `tests/test_mcp_flows.py` 编写 `test_mcp_login_leave_and_acl`。** 通过 Streamable HTTP 使用官方 MCP 客户端发现工具、登录、以申请人创建单据、尝试无权审批、以审批人完成审批，再与 HTTP 详情比较。断言鉴权及业务错误使用相同错误码。
- [ ] **步骤 2：运行 `uv run pytest tests/test_mcp_flows.py -v`。** 应因 `/mcp` 尚不存在而失败。
- [ ] **步骤 3：实现 MCP 服务、挂载及生命周期集成，并编写 `docs/mcp.md`。** 工具只做适配；请求头提取和异常转换集中处理。文档列出工具输入、输出、错误和最小客户端示例。
- [ ] **步骤 4：运行 `uv run pytest tests/test_mcp_flows.py -v`。** 通过本地运行的 ASGI 服务执行，测试应通过。
- [ ] **步骤 5：提交。** 执行 `git add src/mockfastapi/mcp_server.py src/mockfastapi/app.py docs/mcp.md tests/test_mcp_flows.py` 和 `git commit -m "feat: expose mock services through MCP"`。

### 任务 7：README 与最终冒烟验证

**文件：** 修改 `README.md`；新建 `scripts/smoke.py`。

**接口：** `uv run python scripts/smoke.py` 针对运行中的服务执行常见 HTTP 和 MCP 流程，失败时以非零状态退出。README 覆盖配置、Docker 依赖、迁移、初始化与重置、前台调试、PowerShell 隐藏窗口后台运行及日志、Swagger、MCP、测试账号，以及 OAuth `password` grant 仅限测试的说明。

- [ ] **步骤 1：编写 `scripts/smoke.py`，明确断言登录、人员查询、创建/修改/审批、撤回、刷新/登出和至少一次 MCP 调用。** 脚本使用刚重置的固定数据和运行中的服务。
- [ ] **步骤 2：执行迁移、`python -m mockfastapi.cli reset`，启动服务，然后运行 `uv run python scripts/smoke.py`。** 所有断言均应通过；继续之前修复集成不一致的问题。
- [ ] **步骤 3：根据刚验证过的命令编写 README 命令和示例。** PowerShell 后台启动说明必须使用 `Start-Process -WindowStyle Hidden`，并指定标准输出与错误日志路径。
- [ ] **步骤 4：运行 `uv run pytest -v`、`uv run python scripts/smoke.py` 和 `git diff --check`。** 测试和端到端冒烟流程应通过；如有环境限制，须如实记录。
- [ ] **步骤 5：提交。** 执行 `git add README.md scripts/smoke.py` 和 `git commit -m "docs: add runbook and smoke flow"`。

## 执行交接

实施前阅读已批准的设计文档和本计划。按顺序执行任务，保留每项任务的红灯/绿灯验证和提交记录；宣布 Mock 可用前，对整个分支进行一次整体审查。
