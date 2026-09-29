"""Fixed records survive repeated initialization and reset."""

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mockfastapi.config import Settings
from mockfastapi.leave.models import Leave
from mockfastapi.people.models import Person


def run_cli(command: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mockfastapi.cli", command],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_reset_restores_fixed_records(
    isolated_settings: None,
) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.redis_url)
    try:
        run_cli("reset")
        async with sessions() as session:
            initial_people = (await session.scalars(select(Person).order_by(Person.id))).all()
            initial_leaves = (await session.scalars(select(Leave).order_by(Leave.id))).all()
            fixed_person_ids = [person.id for person in initial_people]
            fixed_leave_ids = [leave.id for leave in initial_leaves]
            assert len(initial_people) == 12
            assert len({person.department for person in initial_people}) >= 3
            assert {person.role for person in initial_people} == {
                "employee", "supervisor", "hr", "admin"
            }
            assert {leave.status for leave in initial_leaves} == {
                "pending", "approved", "rejected", "withdrawn"
            }

        run_cli("seed")
        run_cli("seed")
        async with sessions() as session:
            people = (await session.scalars(select(Person).order_by(Person.id))).all()
            leaves = (await session.scalars(select(Leave).order_by(Leave.id))).all()
            assert [person.id for person in people] == fixed_person_ids
            assert [leave.id for leave in leaves] == fixed_leave_ids

            start = datetime(2026, 10, 1, tzinfo=timezone.utc)
            session.add(
                Leave(
                    id=9001,
                    days=Decimal("0.5"),
                    leave_type="annual",
                    start_at=start,
                    end_at=start + timedelta(hours=4),
                    applicant_id=fixed_person_ids[0],
                    approver_id=fixed_person_ids[1],
                    status="pending",
                    reason="Extra test request",
                )
            )
            await session.commit()

        await redis.set("mockfastapi:test-session", "value")
        await redis.set("other-app:test-session", "keep")
        run_cli("reset")
        async with sessions() as session:
            people = (await session.scalars(select(Person).order_by(Person.id))).all()
            leaves = (await session.scalars(select(Leave).order_by(Leave.id))).all()
            assert [person.id for person in people] == fixed_person_ids
            assert [leave.id for leave in leaves] == fixed_leave_ids
            assert {leave.status for leave in leaves} == {
                "pending", "approved", "rejected", "withdrawn"
            }
        assert await redis.get("mockfastapi:test-session") is None
        assert await redis.get("other-app:test-session") == b"keep"
    finally:
        await redis.delete("other-app:test-session")
        await redis.aclose()
        await engine.dispose()
