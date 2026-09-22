import enum
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, ForeignKey, StaticPool, Table, Text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

type Seeder = Callable[[AsyncSession], Awaitable[None]]


class Base(DeclarativeBase):
    pass


class PostStatus(enum.StrEnum):
    draft = "draft"
    published = "published"


post_tags = Table(
    "post_tags",
    Base.metadata,
    Column("post_id", ForeignKey("posts.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    users: Mapped[list["User"]] = relationship(back_populates="group")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"))
    group: Mapped[Group | None] = relationship(back_populates="users")
    posts: Mapped[list["Post"]] = relationship(back_populates="author")

    def __str__(self) -> str:
        return self.email


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    posts: Mapped[list["Post"]] = relationship(secondary=post_tags, back_populates="tags")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[PostStatus] = mapped_column(default=PostStatus.draft)
    score: Mapped[float] = mapped_column(default=0.0)
    published_at: Mapped[datetime | None]
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")
    tags: Mapped[list[Tag]] = relationship(secondary=post_tags, back_populates="posts")


class Vote(Base):
    __tablename__ = "votes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    value: Mapped[int] = mapped_column(default=1)
    user: Mapped[User] = relationship()
    post: Mapped[Post] = relationship()


def make_engine() -> AsyncEngine:
    return create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)


class AppFactory:
    def __init__(self) -> None:
        self.engine = make_engine()
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    def app(self, seed: Seeder | None = None) -> FastAPI:
        engine = self.engine
        sessionmaker = self.sessionmaker

        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            if seed is not None:
                async with sessionmaker() as session:
                    await seed(session)
                    await session.commit()
            yield
            await engine.dispose()

        return FastAPI(lifespan=lifespan)


def allow_all() -> dict[str, str]:
    return {"name": "admin@example.com"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def factory() -> AppFactory:
    return AppFactory()


@pytest.fixture
async def session(factory: AppFactory) -> AsyncIterator[AsyncSession]:
    async with factory.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory.sessionmaker() as session:
        yield session
    await factory.engine.dispose()


@pytest.fixture
def make_client() -> Callable[[FastAPI], TestClient]:
    def _make(app: FastAPI) -> TestClient:
        return TestClient(app)

    return _make
