import logging
import os
from datetime import datetime
from typing import List, Dict
from sqlalchemy import String, Integer, DateTime, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

logger = logging.getLogger("Database")


class Base(DeclarativeBase):
    pass


class History(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(50), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_urls: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_history_context", "bot_id", "channel_id", "timestamp"),
    )


class UserNote(Base):
    __tablename__ = "user_notes"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Database:
    def __init__(self, db_name="data/bot_memory.db"):
        self.db_name = db_name
        self._ensure_data_dir()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_name}")
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession)

    def _ensure_data_dir(self):
        if not os.path.exists(os.path.dirname(self.db_name)):
            os.makedirs(os.path.dirname(self.db_name))

    async def initialize(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Database initialized at {self.db_name}")

    async def add_message(
        self,
        bot_id: str,
        channel_id: str,
        role: str,
        content: str,
        user_id: str = None,
        user_name: str = None,
        message_id: str = None,
        image_urls: List[str] = None,
    ):
        import json

        async with self.session_factory() as session:
            message = History(
                bot_id=bot_id,
                channel_id=str(channel_id),
                user_id=str(user_id) if user_id else None,
                user_name=user_name,
                message_id=str(message_id) if message_id else None,
                role=role,
                content=content,
                image_urls=json.dumps(image_urls) if image_urls else None,
            )
            session.add(message)
            await session.commit()

    async def get_context(
        self, bot_id: str, channel_id: str, limit: int = 20, bot_name: str = None
    ) -> List[Dict]:
        import json

        async with self.session_factory() as session:
            from sqlalchemy import select, desc

            result = await session.execute(
                select(History)
                .where(History.bot_id == bot_id, History.channel_id == str(channel_id))
                .order_by(desc(History.id))
                .limit(limit)
            )
            rows = result.scalars().all()

            history = []
            for row in reversed(rows):
                if row.role == "user" and row.user_name:
                    final_content = f"{row.user_name}: {row.content}"
                elif row.role == "assistant" and bot_name:
                    final_content = f"{bot_name}: {row.content}"
                else:
                    final_content = row.content

                msg = {"role": row.role, "content": final_content}

                if row.image_urls:
                    try:
                        msg["image_urls"] = json.loads(row.image_urls)
                    except Exception as e:
                        print("warning err:", e)
                        pass

                history.append(msg)

            return history

    async def update_last_user_message(
        self, bot_id: str, channel_id: str, new_content: str
    ):
        async with self.session_factory() as session:
            from sqlalchemy import select, desc

            result = await session.execute(
                select(History)
                .where(
                    History.bot_id == bot_id,
                    History.channel_id == str(channel_id),
                    History.role == "user",
                )
                .order_by(desc(History.id))
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row:
                row.content = new_content
                await session.commit()

    async def clear_history(self, bot_id: str, channel_id: str):
        async with self.session_factory() as session:
            from sqlalchemy import delete

            await session.execute(
                delete(History).where(
                    History.bot_id == bot_id, History.channel_id == str(channel_id)
                )
            )
            await session.commit()

    async def delete_message_by_discord_id(self, message_id: str):
        async with self.session_factory() as session:
            from sqlalchemy import delete

            await session.execute(
                delete(History).where(History.message_id == str(message_id))
            )
            await session.commit()

    async def get_recent_message_ids(
        self, bot_id: str, channel_id: str, limit: int = 30
    ) -> List[str]:
        async with self.session_factory() as session:
            from sqlalchemy import select, desc

            result = await session.execute(
                select(History.message_id)
                .where(
                    History.bot_id == bot_id,
                    History.channel_id == str(channel_id),
                    History.message_id.is_not(None),
                )
                .order_by(desc(History.id))
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_user_notes(self, user_id: str) -> str:
        async with self.session_factory() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(UserNote.notes).where(UserNote.user_id == str(user_id))
            )
            return result.scalar_one_or_none() or ""

    async def update_user_notes(self, user_id: str, notes: str):
        async with self.session_factory() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(UserNote).where(UserNote.user_id == str(user_id))
            )
            row = result.scalar_one_or_none()
            if row:
                row.notes = notes
                row.updated_at = datetime.now()
            else:
                row = UserNote(user_id=str(user_id), notes=notes)
                session.add(row)
            await session.commit()
