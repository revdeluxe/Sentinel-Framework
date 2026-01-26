# src/database.py
from sqlmodel import SQLModel, create_engine, Session
import os

# Ensure the database file is created in the root 'sentinel' directory, not inside src
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "sentinel.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False is needed for FastAPI multithreading with SQLite
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def init_db():
    SQLModel.metadata.create_all(engine)
    
def get_session():
    with Session(engine) as session:
        yield session