# All needed tables for Sentinel Framework
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str
    password_hash: str
    is_admin: bool = False
    logs: List["Log"] = Relationship(back_populates="user")

class FaceData(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    embedding: bytes  # Store face embedding
    created_at: Optional[str]
    user: Optional[User] = Relationship(back_populates="face_data")

class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    event: str
    timestamp: str
    user: Optional[User] = Relationship(back_populates="logs")

User.face_data = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
