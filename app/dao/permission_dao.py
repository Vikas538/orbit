from datetime import datetime, timezone

from sqlalchemy import select

from app.database import Database
from app.models.permission import PermissionLog, PermissionStatus

db = Database()


class PermissionDAO:
    async def create(
        self,
        permission_id: str,
        session_id: str,
        ticket_id: str,
        action: str,
        command: str,
        reason: str,
    ) -> PermissionLog:
        async with db.get_async_session() as s:
            record = PermissionLog(
                permission_id=permission_id,
                session_id=session_id,
                ticket_id=ticket_id,
                action=action,
                command=command,
                reason=reason,
                status=PermissionStatus.PENDING,
            )
            s.add(record)
            await s.commit()
            await s.refresh(record)
            return record

    async def resolve(
        self,
        permission_id: str,
        granted: bool,
        resolved_by: str = "user",
    ) -> PermissionLog | None:
        status = PermissionStatus.GRANTED if granted else PermissionStatus.DENIED
        async with db.get_async_session() as s:
            result = await s.execute(
                select(PermissionLog).where(PermissionLog.permission_id == permission_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            record.status      = status
            record.resolved_by = resolved_by
            record.resolved_at = datetime.now(timezone.utc)
            await s.commit()
            await s.refresh(record)
            return record

    async def timeout(self, permission_id: str) -> PermissionLog | None:
        async with db.get_async_session() as s:
            result = await s.execute(
                select(PermissionLog).where(PermissionLog.permission_id == permission_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            record.status      = PermissionStatus.TIMEOUT
            record.resolved_by = "timeout"
            record.resolved_at = datetime.now(timezone.utc)
            await s.commit()
            await s.refresh(record)
            return record

    async def get_by_session(self, session_id: str) -> list[PermissionLog]:
        async with db.get_async_session() as s:
            result = await s.execute(
                select(PermissionLog)
                .where(PermissionLog.session_id == session_id)
                .order_by(PermissionLog.requested_at.desc())
            )
            return list(result.scalars().all())


permission_dao = PermissionDAO()
