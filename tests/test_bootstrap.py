import httpx
import pytest


@pytest.mark.asyncio
async def test_readiness_reports_mysql_and_redis(isolated_settings: None) -> None:
    from mockfastapi.app import create_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mysql": "ready", "redis": "ready"}


@pytest.mark.asyncio
async def test_readiness_reports_unavailable_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dependency outage must produce a stable readiness response."""
    monkeypatch.setenv("DATABASE_URL", "mysql+asyncmy://root@127.0.0.1:1/mockfastapi_test")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/15")

    from mockfastapi.app import create_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "mysql": "unavailable",
        "redis": "unavailable",
    }
