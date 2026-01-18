# SQLAlchemy/SQLModel configuration

from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./sentinel.db"
engine = create_engine(DATABASE_URL, echo=True)

def init_db():
    SQLModel.metadata.create_all(engine)

# Example usage:
# with Session(engine) as session:
#     ...
