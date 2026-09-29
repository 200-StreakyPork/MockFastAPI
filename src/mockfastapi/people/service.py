"""Personnel lookups shared by HTTP and MCP."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mockfastapi.people.models import Person


async def list_people(session: AsyncSession, *, limit: int, offset: int) -> list[Person]:
    result = await session.scalars(select(Person).order_by(Person.id).limit(limit).offset(offset))
    return list(result.all())


async def get_person(session: AsyncSession, person_id: int) -> Person | None:
    return await session.get(Person, person_id)
