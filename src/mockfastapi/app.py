"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from mockfastapi.auth.http import router as auth_router
from mockfastapi.auth.service import AuthError
from mockfastapi.cache import get_redis
from mockfastapi.db import get_session


def create_app() -> FastAPI:
    """Create the mock service application."""
    app = FastAPI(title="MockFastAPI")

    @app.exception_handler(AuthError)
    async def auth_error(_request, error: AuthError) -> JSONResponse:
        status = 401 if error.code in {"invalid_client", "invalid_token"} else 400
        return JSONResponse({"code": error.code, "message": error.message}, status_code=status)

    app.include_router(auth_router)

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
