# 内部 Agent 集成测试 Mock 服务设计

## 目标与范围

本项目为内部 Agent 项目提供可重复运行的外部服务替身。测试方应能通过 HTTP 或 MCP 完成身份获取、令牌续期与撤销、人员查询以及假勤单据的完整常见流程，并用预置的跨部门、跨职级人员验证 ACL。项目只用于本地及受控测试环境。

首期交付一个 Python 3.12、uv 管理依赖的 FastAPI 服务。现有本地 Docker MySQL（`mysql-local-test:3306`）保存人员和单据，Redis（`redis-local-test:6379`）保存令牌状态。服务无需网页界面、复杂组织架构或完整生产级 SSO。

## 系统结构

一个 ASGI 进程包含四个边界清晰的模块：

- `auth`：测试用户认证、OAuth2 令牌、当前身份与鉴权。
- `people`：固定人员目录和种子数据。
- `leave`：假勤单据、状态转换与 ACL。
- `mcp`：将前述业务能力暴露为 MCP 工具，不复制业务规则。

HTTP 路由和 MCP 工具调用同一服务层。MySQL 使用独立的用户、单据表；Redis 按会话保存不透明的随机 access token 和 refresh token，支持有效期与即时撤销。配置通过环境变量或 `.env` 注入，仓库只提交不含真实凭据的 `.env.example`。使用 uv 锁定依赖，数据库表结构由迁移维护。

## 身份与人员

### 测试人员

固定种子数据约 12 人，覆盖至少三个部门、多个职级及普通员工、主管、HR、管理员角色。每人稳定提供 `id`、`name`、`department`、`level`，另有 `username` 和测试角色；账号与初始测试密码写入 README。样本须包含同部门、跨部门、不同级别、可审批人与管理员。重置后人员 ID 不变。

### 令牌接口

`POST /oauth/token` 接受表单编码请求，支持 `grant_type=password`（测试账号、密码）及 `grant_type=refresh_token`（刷新令牌）。预置一个测试 OAuth 客户端，`client_id` 和 `client_secret` 通过配置提供；HTTP 客户端使用 Basic 认证提交这组凭据。响应含 `access_token`、`token_type=Bearer`、`expires_in`、`refresh_token`。访问令牌默认有效 30 分钟，刷新令牌默认有效 7 天；刷新时轮换刷新令牌并使旧令牌失效。

`POST /oauth/revoke` 由测试 OAuth 客户端使用 Basic 认证，撤销指定令牌；`POST /auth/logout` 撤销当前会话的访问令牌及刷新令牌；`GET /auth/me` 返回当前人员；`POST /oauth/introspect` 由测试 OAuth 客户端使用 Basic 认证，返回令牌是否有效及关联人员信息，供测试系统做鉴权验证。业务接口通过 `Authorization: Bearer <access_token>` 获取身份。过期或撤销后立即拒绝访问。

用户名密码直接换令牌符合早期 OAuth2 `password` grant 定义，但现行 OAuth2 安全最佳实践禁止在真实系统使用。此功能仅为受控 Mock 测试满足 API 直连要求；README 必须明确这一限制。这里不声称提供 OpenID Connect、浏览器 SSO、授权码流程或生产级身份提供方。

## 假勤数据与状态

单据字段：`id`、`days`、`leave_type`、`start_at`、`end_at`、`applicant_id`、`approver_id`、`created_at`、`updated_at`、`decided_at`、`decision`、`status`、`reason`。请假类型包括年假、病假、事假、调休。所有时间在接口中使用带时区的 ISO 8601 格式，数据库按 UTC 保存。`days` 为大于零的十进制数；结束时间必须晚于开始时间。天数由请求提供，不根据日历自动计算，以便测试半天等场景。

状态从 `pending` 开始，只能变为 `approved`、`rejected` 或 `withdrawn`。审批结果在待审批时为空；审批后为 `approved` 或 `rejected`，并记录审批时间。撤回不产生审批结果或审批时间。终态不可修改或再次流转。

创建时申请人取自令牌，不接受调用方伪造。指定审批人必须是预置主管或 HR，且不能与申请人相同。申请人只能修改或撤回自己的待审批单据；指定审批人或管理员能审批。单据仅对申请人、指定审批人和管理员可见；管理员可查看全部并审批任何待审批单据。HR 仅因被指定为审批人而获得该单据的审批权限。

## 外部接口

### HTTP

FastAPI 自动生成 `/openapi.json`、`/docs`。业务路径如下，具体请求和响应模型由 OpenAPI 明示：

| 操作 | 方法与路径 |
| --- | --- |
| 获取或刷新令牌 | `POST /oauth/token` |
| 撤销令牌 | `POST /oauth/revoke` |
| 登出当前会话 | `POST /auth/logout` |
| 查看当前人员 | `GET /auth/me` |
| 校验令牌 | `POST /oauth/introspect` |
| 查询人员 | `GET /people`、`GET /people/{person_id}` |
| 创建单据 | `POST /leave-requests` |
| 列表与详情 | `GET /leave-requests`、`GET /leave-requests/{request_id}` |
| 修改待审批单据 | `PATCH /leave-requests/{request_id}` |
| 审批或驳回 | `POST /leave-requests/{request_id}/decision` |
| 撤回 | `POST /leave-requests/{request_id}/withdraw` |

人员目录需要有效访问令牌。列表支持基础分页；单据列表至少支持状态过滤和分页，且始终先施加当前用户的可见性规则。

### MCP

在 `/mcp` 提供 Streamable HTTP。使用 Python MCP SDK 挂载到同一 ASGI 应用，并正确管理其生命周期。提供与 HTTP 能力对应的工具：`sso_login`、`sso_refresh`、`sso_logout`、`sso_validate`、`list_people`、`get_person`、`create_leave_request`、`list_leave_requests`、`get_leave_request`、`update_leave_request`、`decide_leave_request`、`withdraw_leave_request`。`sso_login` 和 `sso_refresh` 可在无 Bearer 令牌时调用，工具参数包含测试 OAuth 客户端凭据及账号密码或刷新令牌；其余工具通过 MCP HTTP 请求的 Bearer 令牌识别人员，并复用 HTTP 的鉴权和 ACL。`sso_validate` 校验当前 Bearer 令牌。

`docs/mcp.md` 列出 MCP 入口、工具、参数、返回值、错误和最小调用示例。MCP 客户端直接配置服务地址及 Bearer 令牌；首期不提供 MCP 专用的 OAuth 自动发现或动态客户端注册。

## 错误处理

- 参数不合法：HTTP `422`；MCP 返回包含字段原因的工具错误。
- 测试账号、客户端认证或令牌无效：OAuth 端点返回标准 OAuth 错误；受保护业务接口返回 `401`。
- 已登录但权限不足：`403`。
- 不存在或不可见的单据：`404`，避免向无权用户泄露记录存在性。
- 对终态单据重复修改、审批或撤回：`409`。
- MySQL 或 Redis 不可用：启动或就绪检查清楚报告依赖异常，不返回伪成功。

错误体保持稳定的 `code`、`message`、可选 `details` 字段，MCP 工具沿用相同业务错误码。

## 初始化、运行和验收

项目提供数据库迁移、固定种子初始化、显式手动重置命令。重置会清除 Mock 用户、单据和相关测试令牌，再恢复固定人员及覆盖待审批、通过、驳回、撤回状态的样例单据。重置是命令行操作，不暴露公开 HTTP 删除接口。

README 包含 Python/uv 与 Docker 依赖、环境变量、迁移与重置、前台调试、后台启动、日志位置、Swagger 与 MCP 文档位置、测试账号、curl 与 MCP 示例。后台启动示例需适用于当前 Windows PowerShell 环境。

验证以少量可执行的集成流程为准，无需复杂单测套件：

1. 登录、查询身份与人员、刷新、登出，并确认旧令牌失效。
2. 申请人创建和修改单据，指定审批人批准或驳回，终态操作被拒绝。
3. 申请人撤回待审批单据；其他普通员工不能查看或操作。
4. 通过 HTTP 和 MCP 各跑一条主要流程，确认数据与 ACL 一致。
5. 手动重置后人员 ID 与样例单据恢复为预期状态。

## 参考规范

- OAuth2 框架（含历史 `password` grant）：<https://www.rfc-editor.org/info/rfc6749/>
- OAuth2 安全最佳实践（禁止真实系统使用 `password` grant）：<https://www.rfc-editor.org/info/rfc9700/>
- OAuth2 令牌撤销：<https://www.rfc-editor.org/info/rfc7009/>
- Python MCP SDK 的 ASGI 挂载说明：<https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/asgi.md>
