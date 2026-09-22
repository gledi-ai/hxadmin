from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from demo.models import Base, Project, Task, User
from demo.seed import seed
from hxadmin import HxAdmin, ModelView

DB_PATH = Path(__file__).parent / "demo.db"
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


def dev_user() -> dict[str, str]:
    return {"name": "dev"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        await seed(session)
    yield
    await engine.dispose()


app = FastAPI(title="Todo demo", lifespan=lifespan)
admin = HxAdmin(app, session=get_session, auth=dev_user, title="Todo admin")


@admin.register
class UserView(ModelView[User]):
    model = User
    category = "People"
    icon = "users"


@admin.register
class ProjectView(ModelView[Project]):
    model = Project
    category = "Work"
    icon = "table"


@admin.register
class TaskView(ModelView[Task]):
    model = Task
    category = "Work"
