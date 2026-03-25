from sqlalchemy import select

from app.database import Database
from app.models.session import OrbitSessions

db = Database()


class SessionDAO:
    async def get_by_ticket_id(self, ticket_id: str) -> OrbitSessions | None:
        async with db.get_async_session() as session:
            result = await session.execute(
                select(OrbitSessions).where(OrbitSessions.ticket_id == ticket_id)
            )
            return result.scalar_one_or_none()

    async def create(self, ticket_id: str, **kwargs) -> OrbitSessions:
        async with db.get_async_session() as session:
            record = OrbitSessions(ticket_id=ticket_id, **kwargs)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def update(self, session_id: str, **kwargs) -> OrbitSessions | None:
        async with db.get_async_session() as session:
            result = await session.execute(
                select(OrbitSessions).where(OrbitSessions.session_id == session_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            for key, value in kwargs.items():
                setattr(record, key, value)
            await session.commit()
            await session.refresh(record)
            return record


session_dao = SessionDAO()
