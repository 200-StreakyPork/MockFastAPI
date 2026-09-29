"""Leave rules shared by HTTP and MCP adapters."""

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.auth.schemas import Principal
from mockfastapi.leave.models import Leave
from mockfastapi.leave.schemas import LeaveCreate, LeaveDecision, LeavePatch
from mockfastapi.people.models import Person


class LeaveError(Exception):
    """Stable domain error for transport adapters."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _visible(actor: Principal, leave: Leave) -> bool:
    return actor.role == "admin" or actor.id in (leave.applicant_id, leave.approver_id)


async def _approver(session: AsyncSession, applicant_id: int, approver_id: int) -> None:
    person = await session.get(Person, approver_id)
    if person is None or person.role not in ("supervisor", "hr") or approver_id == applicant_id:
        raise LeaveError("invalid_input", "approver must be another supervisor or HR user", 422)


def _pending(leave: Leave) -> None:
    if leave.status != "pending":
        raise LeaveError("conflict", "only pending leave can be changed", 409)


def _stored_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def create_leave(session: AsyncSession, actor: Principal, data: LeaveCreate) -> Leave:
    try:
        await _approver(session, actor.id, data.approver_id)
        leave = Leave(**data.model_dump(), applicant_id=actor.id, status="pending")
        session.add(leave)
        await session.commit()
        await session.refresh(leave)
        return leave
    except Exception:
        await session.rollback()
        raise


async def list_leaves(
    session: AsyncSession, actor: Principal, status: str | None, limit: int, offset: int,
) -> list[Leave]:
    query = select(Leave)
    if actor.role != "admin":
        query = query.where(or_(Leave.applicant_id == actor.id, Leave.approver_id == actor.id))
    if status is not None:
        query = query.where(Leave.status == status)
    result = await session.scalars(query.order_by(Leave.id).limit(limit).offset(offset))
    return list(result.all())


async def get_leave(session: AsyncSession, actor: Principal, leave_id: int) -> Leave:
    leave = await session.get(Leave, leave_id)
    if leave is None or not _visible(actor, leave):
        raise LeaveError("not_found", "leave not found", 404)
    return leave


async def update_leave(
    session: AsyncSession, actor: Principal, leave_id: int, data: LeavePatch,
) -> Leave:
    try:
        leave = await get_leave(session, actor, leave_id)
        if actor.id != leave.applicant_id:
            raise LeaveError("forbidden", "only the applicant can update leave", 403)
        _pending(leave)
        changes = data.model_dump(exclude_unset=True)
        if any(value is None for value in changes.values()):
            raise LeaveError("invalid_input", "leave fields cannot be null", 422)
        if "approver_id" in changes:
            await _approver(session, actor.id, changes["approver_id"])
        start_at = changes.get("start_at", leave.start_at)
        end_at = changes.get("end_at", leave.end_at)
        if _stored_utc(end_at) <= _stored_utc(start_at):
            raise LeaveError("invalid_input", "end_at must be later than start_at", 422)
        for name, value in changes.items():
            setattr(leave, name, value)
        leave.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(leave)
        return leave
    except Exception:
        await session.rollback()
        raise


async def decide_leave(
    session: AsyncSession, actor: Principal, leave_id: int, data: LeaveDecision,
) -> Leave:
    try:
        leave = await get_leave(session, actor, leave_id)
        if actor.role != "admin" and actor.id != leave.approver_id:
            raise LeaveError("forbidden", "only the approver or admin can decide leave", 403)
        _pending(leave)
        leave.status = data.decision
        leave.decision = data.decision
        leave.decided_at = datetime.now(timezone.utc)
        leave.updated_at = leave.decided_at
        await session.commit()
        await session.refresh(leave)
        return leave
    except Exception:
        await session.rollback()
        raise


async def withdraw_leave(session: AsyncSession, actor: Principal, leave_id: int) -> Leave:
    try:
        leave = await get_leave(session, actor, leave_id)
        if actor.id != leave.applicant_id:
            raise LeaveError("forbidden", "only the applicant can withdraw leave", 403)
        _pending(leave)
        leave.status = "withdrawn"
        leave.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(leave)
        return leave
    except Exception:
        await session.rollback()
        raise
