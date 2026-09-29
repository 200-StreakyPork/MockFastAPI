"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from mockfastapi.auth.http import router as auth_router
from mockfastapi.auth.service import AuthError
from mockfastapi.cache import get_redis
from mockfastapi.db import get_session
from mockfastapi.leave.http import router as leave_router
from mockfastapi.leave.service import LeaveError
from mockfastapi.mcp_server import create_mcp_server
from mockfastapi.people.http import router as people_router


def create_app() -> FastAPI:
    """Create the mock service application."""
    mcp = create_mcp_server()
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="MockFastAPI", lifespan=lifespan)

    @app.exception_handler(AuthError)
    async def auth_error(request, error: AuthError) -> JSONResponse:
        status = 401 if error.code in {"invalid_client", "invalid_token"} else 400
        body = {"code": error.code, "message": error.message}
        headers = {}
        if request.url.path.startswith("/oauth/"):
            body.update(error=error.code, error_description=error.message)
            if error.code == "invalid_client":
                headers["WWW-Authenticate"] = 'Basic realm="mockfastapi"'
        return JSONResponse(body, status_code=status, headers=headers)

    @app.exception_handler(LeaveError)
    async def leave_error(_request, error: LeaveError) -> JSONResponse:
        return JSONResponse(
            {"code": error.code, "message": error.message}, status_code=error.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, error: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
            for item in error.errors()
        ]
        return JSONResponse(
            {"code": "invalid_input", "message": "Invalid request", "details": details},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request, error: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found",
                409: "conflict", 422: "invalid_input"}.get(error.status_code, "http_error")
        return JSONResponse(
            {"code": code, "message": str(error.detail)}, status_code=error.status_code,
        )

    app.include_router(auth_router)
    app.include_router(people_router)
    app.include_router(leave_router)

    def openapi() -> dict:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {}).setdefault("securitySchemes", {}).update({
            "OAuthClientBasic": {"type": "http", "scheme": "basic"},
            "AccessTokenBearer": {"type": "http", "scheme": "bearer"},
        })
        token_json = {
            "oneOf": [
                {"type": "object", "required": ["grant_type", "username", "password"],
                 "example": {"grant_type": "password", "username": "alice", "password": "TestPass123!"},
                 "properties": {"grant_type": {"type": "string", "const": "password"},
                                "username": {"type": "string"},
                                "password": {"type": "string", "format": "password"}}},
                {"type": "object", "required": ["grant_type", "refresh_token"],
                 "example": {"grant_type": "refresh_token", "refresh_token": "your-refresh-token"},
                 "properties": {"grant_type": {"type": "string", "const": "refresh_token"},
                                "refresh_token": {"type": "string"}}},
            ]
        }
        for path, body in {
            "/oauth/token": token_json,
            "/oauth/revoke": {"type": "object", "required": ["token"],
                              "properties": {"token": {"type": "string"}},
                              "example": {"token": "your-token"}},
            "/oauth/introspect": {"type": "object", "required": ["token"],
                                  "properties": {"token": {"type": "string"}},
                                  "example": {"token": "your-access-token"}},
        }.items():
            operation = schema["paths"][path]["post"]
            operation["security"] = [{"OAuthClientBasic": []}]
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": body}},
            }
        for path, methods in schema["paths"].items():
            if path.startswith(("/auth/", "/people", "/leaves")):
                for operation in methods.values():
                    operation["security"] = [{"AccessTokenBearer": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        mysql_ready = False
        redis_ready = False
        session_iterator = get_session()
        try:
            session = await anext(session_iterator)
            await session.execute(text("SELECT 1"))
            mysql_ready = True
        except Exception:
            mysql_ready = False
        finally:
            await session_iterator.aclose()

        redis = get_redis()
        try:
            await redis.ping()
            redis_ready = True
        except Exception:
            redis_ready = False
        finally:
            await redis.aclose()

        if mysql_ready and redis_ready:
            return JSONResponse({"status": "ready", "mysql": "ready", "redis": "ready"})

        return JSONResponse(
            {"status": "not_ready", "mysql": "unavailable", "redis": "unavailable"},
            status_code=503,
        )

    app.mount("/", mcp_app)
    return app
