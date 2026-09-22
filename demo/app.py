from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from demo.models import Base, Project, Task, User
from demo.seed import seed
from hxadmin import Field, HxAdmin, ModelView

DB_PATH = Path(__file__).parent / "demo.db"
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}")
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


def dev_user() -> dict[str, str]:
    return {"name": "dev"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
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
    list_columns = ("name", "email", "projects")
    searchable = ("name", "email")
    default_sort = ("name", "asc")
    form_fields = (
        Field("name", "str", help_text="Full name"),
        Field("email", "str", "E-mail", widget="email"),
        "projects",
    )


@admin.register
class ProjectView(ModelView[Project]):
    model = Project
    category = "Work"
    icon = "table"
    list_columns = ("name", "description", "members")
    searchable = ("name", "description")
    form_exclude = ("tasks",)


@admin.register
class TaskView(ModelView[Task]):
    model = Task
    category = "Work"
    list_columns = ("title", "status", "due_date", "project", "assignee")
    searchable = ("title",)
    default_sort = ("due_date", "asc")
    page_size = 5
    page_size_options = (5, 25, 100)

    def format_status(self, obj: Task) -> str:
        return obj.status.value.upper()

    async def on_save(
        self, request: Request, session: AsyncSession, obj: Task, *, created: bool
    ) -> None:
        obj.title = obj.title.strip()
