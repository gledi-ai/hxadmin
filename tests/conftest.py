import datetime as dt
import decimal
import enum
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import BytecodeCache, Environment
from jinja2.bccache import Bucket
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    StaticPool,
    String,
    Table,
    Text,
    event,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from hxadmin import HxAdmin

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
    email: Mapped[str] = mapped_column(unique=True)
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

    def __str__(self) -> str:
        return self.title


class Vote(Base):
    __tablename__ = "votes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    value: Mapped[int] = mapped_column(default=1)
    user: Mapped[User] = relationship()
    post: Mapped[Post] = relationship()


class Reading(Base):
    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(SmallInteger)
    amount: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    day: Mapped[dt.date]
    at: Mapped[dt.time]
    taken_at: Mapped[dt.datetime]
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ref: Mapped[uuid.UUID]


invoices = Table(
    "invoices",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("customer", String, nullable=False),
    Column("total", Integer, nullable=False),
    Column("paid", Boolean, nullable=False, default=False),
)


class Invoice(Base):
    __table__ = invoices


rates = Table(
    "rates",
    Base.metadata,
    Column("code", String, nullable=False, unique=True),
    Column("value", Integer, nullable=False),
)


class Rate(Base):
    __table__ = rates
    __mapper_args__ = {"primary_key": [rates.c.code]}  # noqa: RUF012


def make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


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
        async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
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


class MemoryBytecodeCache(BytecodeCache):
    """Compiled templates shared by every test's environment; keyed by name, path and source."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def load_bytecode(self, bucket: Bucket) -> None:
        if (data := self.store.get(bucket.key)) is not None:
            bucket.bytecode_from_string(data)

    def dump_bytecode(self, bucket: Bucket) -> None:
        self.store[bucket.key] = bucket.bytecode_to_string()


@pytest.fixture(scope="session", autouse=True)
def shared_template_bytecode() -> Iterator[None]:
    cache = MemoryBytecodeCache()
    make_environment = HxAdmin._make_environment

    def cached(self: HxAdmin, templates_dir: Any) -> Environment:
        env = make_environment(self, templates_dir)
        env.bytecode_cache = cache
        return env

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(HxAdmin, "_make_environment", cached)
        yield


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
