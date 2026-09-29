"""Deterministic personnel and leave fixtures for local tests."""

from datetime import datetime, timezone
from decimal import Decimal

from pwdlib import PasswordHash
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.leave.models import Leave
from mockfastapi.people.models import Person


TEST_PASSWORD = "TestPass123!"
REDIS_KEY_PREFIX = "mockfastapi:"

PEOPLE = (
    (1, "alice", "Alice Chen", "Engineering", "L2", "employee"),
    (2, "bob", "Bob Wang", "Engineering", "L4", "supervisor"),
    (3, "carol", "Carol Li", "Engineering", "L3", "employee"),
    (4, "david", "David Zhang", "Engineering", "L1", "employee"),
    (5, "erin", "Erin Liu", "Sales", "L2", "employee"),
    (6, "frank", "Frank Zhao", "Sales", "L4", "supervisor"),
    (7, "grace", "Grace Wu", "Sales", "L3", "employee"),
    (8, "henry", "Henry Sun", "Sales", "L1", "employee"),
    (9, "irene", "Irene Xu", "Operations", "L2", "employee"),
    (10, "james", "James Hu", "Operations", "L4", "supervisor"),
    (11, "kate", "Kate Yang", "HR", "L4", "hr"),
    (12, "leo", "Leo Ma", "Operations", "L5", "admin"),
)

SAMPLE_START = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
SAMPLE_END = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
SAMPLE_CREATED = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
SAMPLE_DECIDED = datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc)
LEAVES = (
    (1001, 1, 2, "annual", "pending", None, None),
    (1002, 3, 2, "sick", "approved", "approved", SAMPLE_DECIDED),
    (1003, 5, 6, "personal", "rejected", "rejected", SAMPLE_DECIDED),
    (1004, 9, 11, "compensatory", "withdrawn", None, None),
)


async def seed(session: AsyncSession, *, reset: bool, redis: Redis) -> None:
    """Add missing fixtures, or replace all Mock data and app-owned tokens."""
    hasher = PasswordHash.recommended()
    async with session.begin():
        if reset:
            await session.execute(delete(Leave))
            await session.execute(delete(Person))

        for person_id, username, name, department, level, role in PEOPLE:
            if await session.get(Person, person_id) is None:
                session.add(
                    Person(
                        id=person_id,
                        username=username,
                        name=name,
                        department=department,
                        level=level,
                        role=role,
                        password_hash=hasher.hash(TEST_PASSWORD),
                    )
                )

        for leave_id, applicant_id, approver_id, leave_type, status, decision, decided_at in LEAVES:
            if await session.get(Leave, leave_id) is None:
                session.add(
                    Leave(
                        id=leave_id,
                        days=Decimal("1.00"),
                        leave_type=leave_type,
                        start_at=SAMPLE_START,
                        end_at=SAMPLE_END,
                        applicant_id=applicant_id,
                        approver_id=approver_id,
                        created_at=SAMPLE_CREATED,
                        updated_at=SAMPLE_DECIDED if decided_at else SAMPLE_CREATED,
                        decided_at=decided_at,
                        decision=decision,
                        status=status,
                        reason=f"Fixed {status} sample",
                    )
                )

    if reset:
        keys = [key async for key in redis.scan_iter(match=f"{REDIS_KEY_PREFIX}*")]
        if keys:
            await redis.delete(*keys)
