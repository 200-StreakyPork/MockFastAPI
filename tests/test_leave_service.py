"""Leave workflow rules against the isolated database fixtures."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import subprocess
import sys

import pytest

from mockfastapi.auth.schemas import Principal
from mockfastapi.db import get_session
from mockfastapi.leave.schemas import LeaveCreate, LeaveDecision, LeaveOut, LeavePatch
from mockfastapi.leave.service import (
    LeaveError,
    create_leave,
    decide_leave,
    get_leave,
    list_leaves,
    update_leave,
    withdraw_leave,
)


ALICE = Principal(id=1, username="alice", role="employee")
BOB = Principal(id=2, username="bob", role="supervisor")
CAROL = Principal(id=3, username="carol", role="employee")
DAVID = Principal(id=4, username="david", role="employee")
LEO = Principal(id=12, username="leo", role="admin")
START = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
END = START + timedelta(days=2)


def reset_fixtures() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mockfastapi.cli", "reset"],
        env=os.environ.copy(), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_create_modify_and_approve(isolated_settings: None) -> None:
    """Applicant owns changes while the designated supervisor approves them."""
    reset_fixtures()
    sessions = get_session()
    try:
        session = await anext(sessions)
        leave = await create_leave(session, ALICE, LeaveCreate(
            days=Decimal("2"), leave_type="annual", start_at=START,
            end_at=END, approver_id=BOB.id, reason="Travel",
        ))
        assert leave.applicant_id == ALICE.id
        assert leave.status == "pending"
        assert leave.days == Decimal("2.00")
        leave_id = leave.id
        session.expire(leave)
        shifted = START + timedelta(days=1)
        await update_leave(session, ALICE, leave_id, LeavePatch(
            reason="Family travel", start_at=shifted,
        ))
        await decide_leave(session, BOB, leave_id, LeaveDecision(decision="approved"))
        saved = await get_leave(session, ALICE, leave_id)
        assert (saved.status, saved.decision, saved.reason) == (
            "approved", "approved", "Family travel",
        )
        assert LeaveOut.model_validate(saved).start_at == shifted
        assert saved.decided_at is not None
        output = LeaveOut.model_validate(saved)
        assert output.start_at.tzinfo == timezone.utc
        assert output.created_at.tzinfo == timezone.utc
        assert output.decided_at is not None and output.decided_at.tzinfo == timezone.utc
        with pytest.raises(LeaveError) as error:
            await update_leave(session, ALICE, leave_id, LeavePatch(reason="Too late"))
        assert error.value.code == "conflict"
    finally:
        await sessions.aclose()


@pytest.mark.asyncio
async def test_visibility_and_approver_acl(isolated_settings: None) -> None:
    """Only applicant, designated approver and admin can read a request."""
    reset_fixtures()
    sessions = get_session()
    try:
        session = await anext(sessions)
        assert [leave.id for leave in await list_leaves(session, ALICE, None, 20, 0)] == [1001]
        assert [leave.id for leave in await list_leaves(session, BOB, None, 20, 0)] == [1001, 1002]
        assert [leave.id for leave in await list_leaves(session, LEO, "pending", 20, 0)] == [1001]
        assert (await get_leave(session, BOB, 1001)).id == 1001
        with pytest.raises(LeaveError) as invisible:
            await get_leave(session, DAVID, 1001)
        assert invisible.value.code == "not_found"
        with pytest.raises(LeaveError) as forbidden:
            await decide_leave(session, ALICE, 1001, LeaveDecision(decision="approved"))
        assert forbidden.value.code == "forbidden"
        with pytest.raises(LeaveError) as bad_approver:
            await create_leave(session, ALICE, LeaveCreate(
                days=Decimal("1"), leave_type="annual", start_at=START,
                end_at=END, approver_id=CAROL.id, reason="Travel",
            ))
        assert bad_approver.value.code == "invalid_input"
        assert (await decide_leave(session, LEO, 1001, LeaveDecision(decision="rejected"))).status == "rejected"
    finally:
        await sessions.aclose()


@pytest.mark.asyncio
async def test_withdraw_pending_leave(isolated_settings: None) -> None:
    """The applicant can withdraw an undecided request."""
    reset_fixtures()
    sessions = get_session()
    try:
        session = await anext(sessions)
        leave = await withdraw_leave(session, ALICE, 1001)
        assert leave.status == "withdrawn"
        assert (await get_leave(session, ALICE, 1001)).status == "withdrawn"
        with pytest.raises(LeaveError) as forbidden:
            await withdraw_leave(session, BOB, 1001)
        assert forbidden.value.code == "forbidden"
    finally:
        await sessions.aclose()
