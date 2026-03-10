# /app/models.py
from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Index

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nickname: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    tg_chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    user_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # зручно мати зворотні відносини
    videos = relationship("Video", back_populates="user", cascade="all,delete-orphan")
    tickets = relationship("SupportTicket", back_populates="user", cascade="all,delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# status: review | published | deleted
# source: ui | telegram
# target: tg | inbox
class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(16), default="review", index=True)
    source: Mapped[str] = mapped_column(String(16), default="ui", index=True)
    target: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    path: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(64), default="video/webm")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    delivered_to_tg: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    user = relationship("User", back_populates="videos")

    __table_args__ = (
        Index("ix_videos_status_target", "status", "target"),
        Index("ix_videos_user_status", "user_id", "status"),
    )


class SupportTicket(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    user_key: Mapped[str] = mapped_column(String(64), index=True)
    nickname: Mapped[str] = mapped_column(String(64), index=True)

    message: Mapped[str] = mapped_column(Text)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|answered|closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    user = relationship("User", back_populates="tickets", lazy="joined")
