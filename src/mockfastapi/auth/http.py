"""OAuth JSON routes and authenticated identity endpoints."""

import base64
import binascii
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.auth.schemas import Principal, TokenResponse
from mockfastapi.auth.service import (
    AuthError,
    authenticate_client,
    introspect,
    issue_password_tokens,
    logout,
    principal_for_access,
    refresh_tokens,
    revoke_token,
)
from mockfastapi.cache import get_redis
from mockfastapi.config import Settings
from mockfastapi.db import get_session

router = APIRouter()


async def redis_client() -> AsyncIterator[Redis]:
    redis = get_redis()
    try:
        yield redis
    finally:
        await redis.aclose()


def _basic_client(request: Request) -> None:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Basic "):
        raise AuthError("invalid_client", "Client authentication required")
    try:
        decoded = base64.b64decode(value[6:], validate=True).decode("utf-8")
        client_id, client_secret = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise AuthError("invalid_client", "Invalid client credentials") from error
    authenticate_client(client_id, client_secret, Settings())


def _bearer(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer ") or not value[7:]:
        raise AuthError("invalid_token", "Bearer token required")
    return value[7:]


async def _json_body(request: Request) -> dict[str, str]:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise AuthError("invalid_request", "JSON request body required")
    try:
        values = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AuthError("invalid_request", "Invalid JSON request body") from error
    if not isinstance(values, dict):
        raise AuthError("invalid_request", "JSON object required")
    return values


@router.post("/oauth/token", response_model=TokenResponse)
async def token(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(redis_client),
) -> TokenResponse:
    _basic_client(request)
    body = await _json_body(request)
    grant = body.get("grant_type")
    if grant == "password":
        pair = await issue_password_tokens(session, redis, body.get("username", ""), body.get("password", ""))
    elif grant == "refresh_token":
        pair = await refresh_tokens(redis, body.get("refresh_token", ""))
    else:
        raise AuthError("unsupported_grant_type", "Unsupported grant type")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TokenResponse(**pair.model_dump(), token_type="Bearer")


@router.post("/oauth/revoke", status_code=200)
async def revoke(request: Request, redis: Redis = Depends(redis_client)) -> Response:
    _basic_client(request)
    body = await _json_body(request)
    await revoke_token(redis, body.get("token", ""))
    return Response(status_code=200)


@router.post("/oauth/introspect")
async def token_introspection(request: Request, redis: Redis = Depends(redis_client)) -> dict[str, bool | int | str]:
    _basic_client(request)
    body = await _json_body(request)
    return await introspect(redis, body.get("token", ""))


@router.get("/auth/me")
async def me(request: Request, redis: Redis = Depends(redis_client)) -> Principal:
    return await principal_for_access(redis, _bearer(request))


@router.post("/auth/logout", status_code=204)
async def end_session(request: Request, redis: Redis = Depends(redis_client)) -> Response:
    await logout(redis, _bearer(request))
    return Response(status_code=204)
