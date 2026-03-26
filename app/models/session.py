from sqlalchemy import (
    func,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    JSON,
    ForeignKey,
    Enum as SQLAlchemyEnum,
    ARRAY,
    Text,
)
from sqlalchemy.sql import func
from app.database import Base
from enum import Enum
from cuid import cuid


class OrbitTicketStatus(str, Enum):
    STARTED="STARTED"
    BLOCKED="BLOCKED"
    PENDING="PENDING"
    COMPLETED="COMPLETED"
    IN_PROGRESS="IN_PROGRESS"
    
    
    


class OrbitSessions(Base):
    __tablename__ = "orbit_sessions"

    session_id = Column(String(32), primary_key=True, unique=True, default=cuid)
    ticket_id = Column(String(100), nullable=False)
    ticket_details = Column(JSON, nullable=True)
    model_used = Column(String(100), nullable=True)
    repo_name =Column(String(100), nullable=True)
    file_changes = Column(ARRAY(Text), nullable=True)
    function_changes = Column(ARRAY(Text), nullable=True)
    plan = Column(Text, nullable=True)
    reasoning = Column(Text, nullable=True)
    status = Column(String, nullable=True)
    container_name = Column(String, nullable=True)
    container_id = Column(String, nullable=True)


    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "email": self.email,
            "user_id": self.user_id,
            "company_id": self.company_id,
            "type": self.type,
            "enc_oauth_token": self.enc_oauth_token,
            "account_id": self.account_id,
            "is_active": self.is_active,
            "ticket_id": self.ticket_id,
            "ticket_details": self.ticket_details,
            "model_used": self.model_used,
            "file_changes": self.file_changes,
            "status": self.status,
            "function_changes": self.function_changes,
            "container_name": self.container_name,
            "container_id": self.container_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
