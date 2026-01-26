# src/table.py
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    
    # Old bool flag (can still be used for root)
    is_admin: bool = False
    
    # NEW: Admin Key for standard users to get admin rights
    admin_key: Optional[str] = Field(default=None, nullable=True) 
    
    full_name: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    # Relationships
    logs: List["Log"] = Relationship(back_populates="user")
    face_data: Optional["FaceData"] = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

class FaceData(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    embedding_blob: bytes
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    user: Optional[User] = Relationship(back_populates="face_data")

class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(foreign_key="user.id", nullable=True)
    event_type: str
    details: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    user: Optional[User] = Relationship(back_populates="logs")

class SystemConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    system_name: str
    deployment_mode: str
    config_json: str
    is_setup_complete: bool = False