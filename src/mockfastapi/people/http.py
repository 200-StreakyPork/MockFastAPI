"""Authenticated personnel directory routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.auth.http import _bearer, redis_client
from mockfastapi.auth.schemas import Principal
from mockfastapi.auth.service import principal_for_access
from mockfastapi.db import get_session
from mockfastapi.people.schemas import PersonOut
from mockfastapi.people.service import get_person, list_people


router = APIRouter()


async def access_principal(request: Request, redis=Depends(redis_client)) -> Principal:
    """Resolve the business API's Bearer token without OAuth client credentials."""
    return await principal_for_access(redis, _bearer(request))


@router.get("/people", response_model=list[PersonOut])
async def people(
    _actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
) -> list[PersonOut]:
    return await list_people(session, limit=limit, offset=offset)


@router.get("/people/{person_id}", response_model=PersonOut)
async def person(
    person_id: int,
    _actor: Principal = Depends(access_principal),
    session: AsyncSession = Depends(get_session),
) -> PersonOut:
    found = await get_person(session, person_id)
    if found is None:
        raise HTTPException(status_code=404, detail="person not found")
    return found
