"""Streamable HTTP tools adapting the shared mock service layer."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.auth.schemas import Principal
from mockfastapi.auth.service import (
    AuthError, authenticate_client, introspect, issue_password_tokens, logout,
    principal_for_access, refresh_tokens,
)
from mockfastapi.cache import get_redis
from mockfastapi.config import Settings
from mockfastapi.db import get_session
from mockfastapi.leave.schemas import LeaveCreate, LeaveDecision, LeaveOut, LeavePatch
from mockfastapi.leave.service import (
    LeaveError, create_leave as service_create_leave, decide_leave as service_decide_leave,
    get_leave as service_get_leave, list_leaves as service_list_leaves,
    update_leave as service_update_leave, withdraw_leave as service_withdraw_leave,
)
from mockfastapi.people.schemas import PersonOut
from mockfastapi.people.service import get_person as service_get_person, list_people as service_list_people


class ServiceMCP(FastMCP):
    """Preserve domain codes in MCP tool errors."""

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        try:
            return await super().call_tool(name, arguments)
        except ToolError as error:
            source = error.__cause__
            if isinstance(source, (AuthError, LeaveError)):
                data = {"code": source.code, "message": source.message}
            elif isinstance(source, (ValidationError, ValueError)):
                data = {"code": "invalid_input", "message": "Invalid tool input"}
            else:
                data = {"code": "internal_error", "message": "Tool execution failed"}
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(data))],
                structuredContent=data, isError=True,
            )


@asynccontextmanager
async def _resources() -> AsyncIterator[tuple[AsyncSession, Redis]]:
    sessions = get_session()
    redis = get_redis()
    try:
        session = await anext(sessions)
        yield session, redis
    finally:
        await sessions.aclose()
        await redis.aclose()


def _token(context: Context) -> str:
    request = context.request_context.request
    value = request.headers.get("Authorization", "") if request is not None else ""
    if not value.startswith("Bearer ") or not value[7:]:
        raise AuthError("invalid_token", "Bearer token required")
    return value[7:]


async def _principal(context: Context, redis: Redis) -> Principal:
    return await principal_for_access(redis, _token(context))


def _leave(leave: Any) -> dict[str, Any]:
    return LeaveOut.model_validate(leave).model_dump(mode="json")


def create_mcp_server() -> ServiceMCP:
    mcp = ServiceMCP("MockFastAPI", streamable_http_path="/mcp", stateless_http=True,
                     json_response=True)

    @mcp.tool(structured_output=True)
    async def sso_login(client_id: str, client_secret: str, username: str, password: str) -> dict[str, Any]:
        """Exchange configured client and user credentials for a token pair."""
        authenticate_client(client_id, client_secret, Settings())
        async with _resources() as (session, redis):
            pair = await issue_password_tokens(session, redis, username, password)
        return {**pair.model_dump(), "token_type": "Bearer"}

    @mcp.tool(structured_output=True)
    async def sso_refresh(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
        """Rotate a refresh token after client authentication."""
        authenticate_client(client_id, client_secret, Settings())
        async with _resources() as (_, redis):
            pair = await refresh_tokens(redis, refresh_token)
        return {**pair.model_dump(), "token_type": "Bearer"}

    @mcp.tool(structured_output=True)
    async def sso_logout(context: Context) -> dict[str, Any]:
        """Revoke the Bearer access token in the MCP request."""
        async with _resources() as (_, redis):
            await logout(redis, _token(context))
        return {"revoked": True}

    @mcp.tool(structured_output=True)
    async def sso_validate(context: Context) -> dict[str, Any]:
        """Return active identity for the Bearer token in the MCP request."""
        async with _resources() as (_, redis):
            token = _token(context)
            await principal_for_access(redis, token)
            return await introspect(redis, token)

    @mcp.tool(structured_output=True)
    async def list_people(context: Context, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List personnel visible to an authenticated caller."""
        if limit < 1 or offset < 0:
            raise ValueError("invalid pagination")
        async with _resources() as (session, redis):
            await _principal(context, redis)
            people = await service_list_people(session, limit=limit, offset=offset)
            return {"people": [PersonOut.model_validate(person).model_dump(mode="json") for person in people]}

    @mcp.tool(structured_output=True)
    async def get_person(person_id: int, context: Context) -> dict[str, Any]:
        """Get one person by ID."""
        async with _resources() as (session, redis):
            await _principal(context, redis)
            person = await service_get_person(session, person_id)
            if person is None:
                raise LeaveError("not_found", "person not found", 404)
            return PersonOut.model_validate(person).model_dump(mode="json")

    @mcp.tool(structured_output=True)
    async def create_leave(days: Decimal, leave_type: str, start_at: datetime,
                           end_at: datetime, approver_id: int, reason: str,
                           context: Context) -> dict[str, Any]:
        """Create a pending leave for the Bearer principal."""
        data = LeaveCreate(days=days, leave_type=leave_type, start_at=start_at,
                           end_at=end_at, approver_id=approver_id, reason=reason)
        async with _resources() as (session, redis):
            return _leave(await service_create_leave(session, await _principal(context, redis), data))

    @mcp.tool(structured_output=True)
    async def list_leaves(context: Context, status: str | None = None,
                          limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List leave records visible to the Bearer principal."""
        if limit < 1 or offset < 0 or status not in (None, "pending", "approved", "rejected", "withdrawn"):
            raise ValueError("invalid filters")
        async with _resources() as (session, redis):
            leaves = await service_list_leaves(session, await _principal(context, redis),
                                               status, limit, offset)
            return {"leaves": [_leave(leave) for leave in leaves]}

    @mcp.tool(structured_output=True)
    async def get_leave(leave_id: int, context: Context) -> dict[str, Any]:
        """Get a visible leave record by ID."""
        async with _resources() as (session, redis):
            return _leave(await service_get_leave(session, await _principal(context, redis), leave_id))

    @mcp.tool(structured_output=True)
    async def update_leave(leave_id: int, context: Context, days: Decimal | None = None,
                           leave_type: str | None = None, start_at: datetime | None = None,
                           end_at: datetime | None = None, approver_id: int | None = None,
                           reason: str | None = None) -> dict[str, Any]:
        """Patch a pending leave owned by the Bearer principal."""
        changes = {key: value for key, value in locals().items()
                   if key in {"days", "leave_type", "start_at", "end_at", "approver_id", "reason"}
                   and value is not None}
        data = LeavePatch(**changes)
        async with _resources() as (session, redis):
            return _leave(await service_update_leave(session, await _principal(context, redis), leave_id, data))

    @mcp.tool(structured_output=True)
    async def decide_leave(leave_id: int, decision: Literal["approved", "rejected"],
                           context: Context) -> dict[str, Any]:
        """Approve or reject a pending leave as its approver or admin."""
        async with _resources() as (session, redis):
            return _leave(await service_decide_leave(session, await _principal(context, redis),
                                                     leave_id, LeaveDecision(decision=decision)))

    @mcp.tool(structured_output=True)
    async def withdraw_leave(leave_id: int, context: Context) -> dict[str, Any]:
        """Withdraw a pending leave owned by the Bearer principal."""
        async with _resources() as (session, redis):
            return _leave(await service_withdraw_leave(session, await _principal(context, redis), leave_id))

    return mcp
