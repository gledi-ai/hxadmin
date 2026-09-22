from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import ForeignKey
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


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


def make_engine() -> AsyncEngine:
    return create_async_engine("sqlite+aiosqlite:///:memory:")


class AppFactory:
    def __init__(self) -> None:
        self.engine = make_engine()
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    def app(self) -> FastAPI:
        engine = self.engine

        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            yield
            await engine.dispose()

        return FastAPI(lifespan=lifespan)


def allow_all() -> dict[str, str]:
    return {"name": "admin@example.com"}


@pytest.fixture
def factory() -> AppFactory:
    return AppFactory()


@pytest.fixture
def make_client() -> Callable[[FastAPI], TestClient]:
    def _make(app: FastAPI) -> TestClient:
        return TestClient(app)

    return _make
