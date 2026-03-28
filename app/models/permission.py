from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.database import Base


class PermissionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED  = "DENIED"
    TIMEOUT = "TIMEOUT"


class PermissionLog(Base):
    __tablename__ = "orbit_permission_logs"

    permission_id = Column(String(64), primary_key=True)          # UUID from agent
    session_id    = Column(String(32), ForeignKey("orbit_sessions.session_id"), nullable=False)
    ticket_id     = Column(String(100), nullable=True)

    # What the agent wants to do
    action        = Column(String(100), nullable=False)            # e.g. "run_command", "git_push"
    command       = Column(Text, nullable=False)                   # exact command / operation
    reason        = Column(Text, nullable=True)                    # agent's stated justification

    status        = Column(String(20), nullable=False, default=PermissionStatus.PENDING)
    resolved_by   = Column(String(50), nullable=True)              # "user", "timeout", "auto_deny"

    requested_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at   = Column(DateTime(timezone=True), nullable=True)
