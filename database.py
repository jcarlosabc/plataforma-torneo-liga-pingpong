import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
_default_db = BASE_DIR / "ping_pong.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_default_db}")

# Crear la carpeta del archivo si no existe (necesario en Railway/Docker)
if DATABASE_URL.startswith("sqlite"):
    _db_path = Path(DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", ""))
    _db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
