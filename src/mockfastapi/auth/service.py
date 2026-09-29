"""Opaque Redis-backed access and refresh tokens for the local mock."""

import json
import secrets

from pwdlib import PasswordHash
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.auth.schemas import Principal, TokenPair
from mockfastapi.config import Settings
from mockfastapi.people.models import Person


ACCESS_TTL = 30 * 60
REFRESH_TTL = 7 * 24 * 60 * 60
PREFIX = "mockfastapi:"


class AuthError(Exception):
    """A stable OAuth error that adapters can translate to a response."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def authenticate_client(client_id: str, client_secret: str, settings: Settings) -> None:
    if not (secrets.compare_digest(client_id, settings.oauth_client_id)
            and secrets.compare_digest(client_secret, settings.oauth_client_secret)):
        raise AuthError("invalid_client", "Invalid client credentials")


def _key(kind: str, token: str) -> str:
    return f"{PREFIX}{kind}:{token}"


async def _issue(redis: Redis, principal: Principal) -> TokenPair:
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(32)
    identity = principal.model_dump()
    await redis.setex(_key("access", access), ACCESS_TTL,
                      json.dumps({**identity, "refresh_token": refresh}))
    await redis.setex(_key("refresh", refresh), REFRESH_TTL,
                      json.dumps({**identity, "access_token": access}))
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=ACCESS_TTL)


async def issue_password_tokens(
    session: AsyncSession, redis: Redis, username: str, password: str
) -> TokenPair:
    person = await session.scalar(select(Person).where(Person.username == username))
    if person is None or not PasswordHash.recommended().verify(password, person.password_hash):
        raise AuthError("invalid_grant", "Invalid username or password")
    return await _issue(redis, Principal(id=person.id, username=person.username, role=person.role))


async def refresh_tokens(redis: Redis, refresh_token: str) -> TokenPair:
    data = await redis.getdel(_key("refresh", refresh_token))
    if data is None:
        raise AuthError("invalid_grant", "Invalid refresh token")
    record = json.loads(data)
    await redis.delete(_key("access", record["access_token"]))
    return await _issue(redis, Principal.model_validate(record))


async def principal_for_access(redis: Redis, token: str) -> Principal:
    data = await redis.get(_key("access", token))
    if data is None:
        raise AuthError("invalid_token", "Invalid access token")
    return Principal.model_validate(json.loads(data))


async def revoke_token(redis: Redis, token: str) -> None:
    access = await redis.get(_key("access", token))
    refresh = await redis.get(_key("refresh", token))
    if access is not None:
        record = json.loads(access)
        await redis.delete(_key("access", token), _key("refresh", record["refresh_token"]))
    elif refresh is not None:
        record = json.loads(refresh)
        await redis.delete(_key("refresh", token), _key("access", record["access_token"]))


async def logout(redis: Redis, token: str) -> None:
    await principal_for_access(redis, token)
    await revoke_token(redis, token)


async def introspect(redis: Redis, token: str) -> dict[str, bool | int | str]:
    data = await redis.get(_key("access", token))
    if data is None:
        return {"active": False}
    record = json.loads(data)
    return {"active": True, "sub": str(record["id"]), "username": record["username"],
            "role": record["role"], "token_type": "Bearer"}
