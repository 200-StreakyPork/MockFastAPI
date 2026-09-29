"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from mockfastapi.auth.http import router as auth_router
from mockfastapi.auth.service import AuthError
from mockfastapi.cache import get_redis
from mockfastapi.db import get_session
from mockfastapi.leave.http import router as leave_router
from mockfastapi.leave.service import LeaveError
from mockfastapi.people.http import router as people_router


def create_app() -> FastAPI:
    """Create the mock service application."""
    app = FastAPI(title="MockFastAPI")

    @app.exception_handler(AuthError)
    async def auth_error(_request, error: AuthError) -> JSONResponse:
        status = 401 if error.code in {"invalid_client", "invalid_token"} else 400
        return JSONResponse({"code": error.code, "message": error.message}, status_code=status)

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

    return app
