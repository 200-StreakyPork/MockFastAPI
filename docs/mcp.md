# MCP tools

The mock service exposes the official MCP Streamable HTTP transport at `http://127.0.0.1:8000/mcp`. Run it with `uv run uvicorn mockfastapi.app:create_app --factory`. The MCP app shares the FastAPI process, its startup and shutdown lifecycle, and the existing MySQL, Redis, authentication, personnel, and leave services.

`sso_login` and `sso_refresh` receive `client_id` and `client_secret` as tool arguments. The default pair is `test-client` / `test-secret`; environment settings can override it. All other tools read `Authorization: Bearer <access_token>` from each MCP HTTP request. A new client connection with that header is needed after login. Do not send access tokens as tool arguments.

| Tool | Input | Output |
| --- | --- | --- |
| `sso_login` | `client_id`, `client_secret`, `username`, `password` | `access_token`, `refresh_token`, `expires_in`, `token_type` |
| `sso_refresh` | `client_id`, `client_secret`, `refresh_token` | Rotated token pair, as above |
| `sso_logout` | Bearer header | `revoked: true` |
| `sso_validate` | Bearer header | `active`, `sub`, `username`, `role`, `token_type` |
| `list_people` | Bearer header; optional `limit=20`, `offset=0` | `people`: array of personnel records |
| `get_person` | Bearer header, `person_id` | Personnel record |
| `create_leave` | Bearer header; `days`, `leave_type`, `start_at`, `end_at`, `approver_id`, `reason` | Leave record |
| `list_leaves` | Bearer header; optional `status`, `limit=20`, `offset=0` | `leaves`: array of visible leave records |
| `get_leave` | Bearer header, `leave_id` | Leave record |
| `update_leave` | Bearer header, `leave_id`, any non-null leave fields to change | Updated leave record |
| `decide_leave` | Bearer header, `leave_id`, `decision` (`approved` or `rejected`) | Decided leave record |
| `withdraw_leave` | Bearer header, `leave_id` | Withdrawn leave record |

Leave records have the same fields as the HTTP `/leaves` API. Timestamps are UTC ISO 8601 values ending in `Z`, including values read back from MySQL. `days` is serialized as a decimal string.

Business and authentication failures return an MCP tool result with `isError=true` and `structuredContent` containing `code` and `message`. The same JSON is included in text content for clients that do not read structured content. Common codes are `invalid_client`, `invalid_grant`, `invalid_token`, `invalid_input`, `not_found`, `forbidden`, and `conflict`. MCP protocol/transport failures can instead raise a client exception. A missing or invalid Bearer token yields `invalid_token`; a leave invisible to the caller yields `not_found`.

```python
import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8000/mcp"


async def call(headers, name, arguments):
    async with httpx.AsyncClient(headers=headers) as http:
        async with streamable_http_client(URL, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(name, arguments)


async def main():
    login = await call(
        {},
        "sso_login",
        {
            "client_id": "test-client",
            "client_secret": "test-secret",
            "username": "alice",
            "password": "TestPass123!",
        },
    )
    token = login.structuredContent["access_token"]
    people = await call({"Authorization": f"Bearer {token}"}, "list_people", {})
    print(people.structuredContent["people"])


asyncio.run(main())
```
