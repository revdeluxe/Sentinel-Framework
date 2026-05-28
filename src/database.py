# src/database.py
import json
import os
from types import SimpleNamespace

import numpy as np
import sqlite_vec
from sqlalchemy import event, text
from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine, Session, select

from src.table import FACE_EMBEDDING_DIMENSION, FaceData, User

# Ensure the database file is created in the root 'sentinel' directory, not inside src
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "sentinel.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False is needed for FastAPI multithreading with SQLite
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def load_sqlite_vec(dbapi_connection, connection_record):
    try:
        dbapi_connection.enable_load_extension(True)
        sqlite_vec.load(dbapi_connection)
        dbapi_connection.enable_load_extension(False)
    except Exception as exc:
        print(f"[DB] sqlite-vec load skipped: {exc}")

def init_db():
    SQLModel.metadata.create_all(engine)

    inspector = inspect(engine)
    user_columns = {column_info["name"] for column_info in inspector.get_columns("user")}
    if "email" not in user_columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE user ADD COLUMN email TEXT")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS face_vectors USING vec0(embedding float[{FACE_EMBEDDING_DIMENSION}])"
        )
    
def get_session():
    with Session(engine) as session:
        yield session


def store_face_embedding(session: Session, face_data_id: int, embedding):
    embedding_array = np.asarray(embedding, dtype=np.float32).reshape(-1).tolist()
    session.exec(
        text("INSERT OR REPLACE INTO face_vectors(rowid, embedding) VALUES (:rowid, :embedding)"),
        params={"rowid": face_data_id, "embedding": json.dumps(embedding_array)},
    )


def enroll_face_embedding(session: Session, user_id: int, embedding):
    existing_face = session.exec(
        select(FaceData).where(FaceData.user_id == user_id)
    ).first()

    if existing_face:
        session.exec(text("DELETE FROM face_vectors WHERE rowid = :rowid"), params={"rowid": existing_face.id})
        session.delete(existing_face)
        session.flush()

    embedding_array = np.asarray(embedding, dtype=np.float32).reshape(-1)
    face_data = FaceData(user_id=user_id, embedding_blob=embedding_array.tobytes())
    session.add(face_data)
    session.flush()

    store_face_embedding(session, face_data.id, embedding_array)
    session.flush()
    return face_data


def find_best_face_match(embedding):
    embedding_array = np.asarray(embedding, dtype=np.float32).reshape(-1).tolist()

    with Session(engine) as session:
        try:
            result = session.exec(
                text(
                    """
                    SELECT
                        face_vectors.rowid AS face_data_id,
                        face_data.user_id AS user_id,
                        user.username AS username,
                        user.full_name AS full_name,
                        distance
                    FROM face_vectors
                    JOIN face_data ON face_data.id = face_vectors.rowid
                    JOIN user ON user.id = face_data.user_id
                    WHERE face_vectors.embedding MATCH :embedding
                    ORDER BY distance
                    LIMIT 1
                    """
                ),
                params={"embedding": json.dumps(embedding_array)},
            ).first()

            if result is not None:
                return result
        except Exception as exc:
            print(f"[DB] Vector search unavailable, using Python fallback: {exc}")

        face_rows = session.exec(
            select(FaceData, User).join(User, User.id == FaceData.user_id)
        ).all()

    if not face_rows:
        return None

    query_vector = np.asarray(embedding_array, dtype=np.float32)
    best_match = None
    best_distance = None

    for face_data, user in face_rows:
        stored_vector = np.frombuffer(face_data.embedding_blob, dtype=np.float32)
        if stored_vector.size != query_vector.size:
            continue

        distance = float(np.linalg.norm(query_vector - stored_vector))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_match = SimpleNamespace(
                face_data_id=face_data.id,
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                distance=distance,
            )

    return best_match