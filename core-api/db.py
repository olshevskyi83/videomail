import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

DB_URL = (
    os.getenv("DATABASE_URL")              # ← як у твоєму docker-compose
    or os.getenv("DB_URL")                 # беккомпат, якщо десь лишився
    or "sqlite:////srv/videomail/videomail.db"
)

engine = create_engine(DB_URL, future=True, pool_pre_ping=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))
