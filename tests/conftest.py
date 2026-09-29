import os

import pytest


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point readiness checks at a dedicated test schema and Redis database."""
    monkeypatch.setenv("DATABASE_URL", os.getenv("TEST_DATABASE_URL", "mysql+asyncmy://root@127.0.0.1:3306/mockfastapi_test"))
    monkeypatch.setenv("REDIS_URL", os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/15"))
