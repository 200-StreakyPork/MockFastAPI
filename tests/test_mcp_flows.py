"""MCP Streamable HTTP parity with the business HTTP API."""

import asyncio
import os
import socket
import subprocess
import sys
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@asynccontextmanager
async def running_server():
    port = _port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mockfastapi.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(port)],
        env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError(f"server exited: {process.stdout.read().decode()}")
                try:
                    if (await client.get("/openapi.json")).status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("server did not start")
        yield base_url
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


@asynccontextmanager
async def mcp_session(url: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=10) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def payload(result):
    assert result.structuredContent is not None, result
    return result.structuredContent


@pytest.mark.asyncio
async def test_mcp_login_leave_and_acl(isolated_settings: None) -> None:
    """Missing MCP mount, wrong service delegation, or wrong ACL/error code breaks this flow."""
    reset = subprocess.run(
        [sys.executable, "-m", "mockfastapi.cli", "reset"],
        env=os.environ.copy(), capture_output=True, text=True,
    )
    assert reset.returncode == 0, reset.stdout + reset.stderr

    async with running_server() as base_url:
        async with mcp_session(f"{base_url}/mcp") as session:
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert tools == {
                "sso_login", "sso_refresh", "sso_logout", "sso_validate",
                "list_people", "get_person", "create_leave", "list_leaves",
                "get_leave", "update_leave", "decide_leave", "withdraw_leave",
            }
            invalid_client = await session.call_tool("sso_login", {
                "client_id": "wrong", "client_secret": "wrong", "username": "alice",
                "password": "TestPass123!",
            })
            assert invalid_client.isError
            assert payload(invalid_client)["code"] == "invalid_client"
            alice = payload(await session.call_tool("sso_login", {
                "client_id": "test-client", "client_secret": "test-secret",
                "username": "alice", "password": "TestPass123!",
            }))["access_token"]
            bob = payload(await session.call_tool("sso_login", {
                "client_id": "test-client", "client_secret": "test-secret",
                "username": "bob", "password": "TestPass123!",
            }))["access_token"]

        async with mcp_session(f"{base_url}/mcp", alice) as session:
            created = payload(await session.call_tool("create_leave", {
                "days": "1.5", "leave_type": "annual", "start_at": "2026-10-05T09:00:00Z",
                "end_at": "2026-10-07T09:00:00Z", "approver_id": 2,
                "reason": "Travel",
            }))
            assert created["applicant_id"] == 1
            assert created["status"] == "pending"
            assert created["start_at"].endswith("Z")
            leave_id = created["id"]
            forbidden = await session.call_tool("decide_leave", {
                "leave_id": leave_id, "decision": "approved",
            })
            assert forbidden.isError
            assert payload(forbidden)["code"] == "forbidden"

        async with mcp_session(f"{base_url}/mcp", bob) as session:
            decided = payload(await session.call_tool("decide_leave", {
                "leave_id": leave_id, "decision": "approved",
            }))
            assert decided["status"] == "approved"
            assert decided["decided_at"].endswith("Z")

        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.get(f"/leaves/{leave_id}", headers={"Authorization": f"Bearer {alice}"})
            assert response.status_code == 200, response.text
            assert response.json() == decided
            denied = await client.post(f"/leaves/{leave_id}/decision", json={"decision": "approved"},
                                       headers={"Authorization": f"Bearer {alice}"})
            assert denied.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_mcp_refresh_directory_update_withdraw_and_logout(isolated_settings: None) -> None:
    """The other common tools use the same tokens and persisted records as HTTP."""
    reset = subprocess.run(
        [sys.executable, "-m", "mockfastapi.cli", "reset"],
        env=os.environ.copy(), capture_output=True, text=True,
    )
    assert reset.returncode == 0, reset.stdout + reset.stderr

    async with running_server() as base_url:
        url = f"{base_url}/mcp"
        async with mcp_session(url) as session:
            first = payload(await session.call_tool("sso_login", {
                "client_id": "test-client", "client_secret": "test-secret",
                "username": "alice", "password": "TestPass123!",
            }))
            invalid_refresh = await session.call_tool("sso_refresh", {
                "client_id": "bad", "client_secret": "bad", "refresh_token": first["refresh_token"],
            })
            assert invalid_refresh.isError
            assert payload(invalid_refresh)["code"] == "invalid_client"
            refreshed = payload(await session.call_tool("sso_refresh", {
                "client_id": "test-client", "client_secret": "test-secret",
                "refresh_token": first["refresh_token"],
            }))
            assert refreshed["access_token"] != first["access_token"]

        async with mcp_session(url) as session:
            missing = await session.call_tool("list_people", {})
            assert missing.isError
            assert payload(missing)["code"] == "invalid_token"

        async with mcp_session(url, refreshed["access_token"]) as session:
            identity = payload(await session.call_tool("sso_validate", {}))
            assert identity["username"] == "alice"
            people = payload(await session.call_tool("list_people", {"limit": 2, "offset": 0}))
            assert [person["username"] for person in people["people"]] == ["alice", "bob"]
            person = payload(await session.call_tool("get_person", {"person_id": 2}))
            assert person["username"] == "bob"
            missing_person = await session.call_tool("get_person", {"person_id": 99999})
            assert missing_person.isError
            assert payload(missing_person)["code"] == "not_found"
            leaves = payload(await session.call_tool("list_leaves", {"status": "pending"}))
            assert any(leave["id"] == 1001 for leave in leaves["leaves"])
            patched = payload(await session.call_tool("update_leave", {
                "leave_id": 1001, "reason": "Updated by MCP",
            }))
            assert patched["reason"] == "Updated by MCP"
            detail = payload(await session.call_tool("get_leave", {"leave_id": 1001}))
            assert detail == patched
            withdrawn = payload(await session.call_tool("withdraw_leave", {"leave_id": 1001}))
            assert withdrawn["status"] == "withdrawn"
            assert payload(await session.call_tool("sso_logout", {})) == {"revoked": True}
            invalid = await session.call_tool("sso_validate", {})
            assert invalid.isError
            assert payload(invalid)["code"] == "invalid_token"
