"""Authenticated leave workflow routes."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.auth.schemas import Principal
from mockfastapi.db import get_session
from mockfastapi.leave.schemas import LeaveCreate, LeaveDecision, LeaveOut, LeavePatch
from mockfastapi.leave.service import (
    create_leave, decide_leave, get_leave, list_leaves, update_leave, withdraw_leave,
)
from mockfastapi.people.http import access_principal


router = APIRouter()
LeaveStatus = Literal["pending", "approved", "rejected", "withdrawn"]


@router.post("/leaves", response_model=LeaveOut, status_code=201)
async def create(
    data: LeaveCreate,
    actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
) -> LeaveOut:
    return await create_leave(session, actor, data)


@router.get("/leaves", response_model=list[LeaveOut])
async def leaves(
    actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
    status: LeaveStatus | None = None,
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
) -> list[LeaveOut]:
    return await list_leaves(session, actor, status, limit, offset)


@router.get("/leaves/{leave_id}", response_model=LeaveOut)
async def detail(
    leave_id: int,
    actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
) -> LeaveOut:
    return await get_leave(session, actor, leave_id)


@router.patch("/leaves/{leave_id}", response_model=LeaveOut)
async def patch(
    leave_id: int,
    data: LeavePatch,
    actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
) -> LeaveOut:
    return await update_leave(session, actor, leave_id, data)


@router.post("/leaves/{leave_id}/decision", response_model=LeaveOut)
async def decision(
    leave_id: int,
    data: LeaveDecision,
    actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
) -> LeaveOut:
    return await decide_leave(session, actor, leave_id, data)


@router.post("/leaves/{leave_id}/withdraw", response_model=LeaveOut)
async def withdraw(
    leave_id: int,
    actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
) -> LeaveOut:
    return await withdraw_leave(session, actor, leave_id)
