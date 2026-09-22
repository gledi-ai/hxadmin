from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from demo.models import Base, Project, Task, TaskStatus, User
from demo.seed import seed
from hxadmin import ActionResult, Field, FormError, HxAdmin, ModelView, Page, action

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
admin = HxAdmin(
    app,
    session=get_session,
    auth=dev_user,
    title="Todo admin",
    templates_dir=Path(__file__).parent / "templates",
)


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
    icon = "folder-kanban"
    list_columns = ("name", "description", "members")
    searchable = ("name", "description")
    form_exclude = ("tasks",)


@admin.register
class TaskView(ModelView[Task]):
    model = Task
    category = "Work"
    icon = "list-checks"
    list_columns = ("title", "status", "priority", "due_date", "project", "assignee")
    searchable = ("title",)
    default_sort = ("due_date", "asc")
    page_size = 5
    page_size_options = (5, 25, 100)
    list_filters = ("status", "priority", "due_date", "title", "project", "assignee")
    export_formats = ("csv", "xlsx")

    def format_status(self, obj: Task) -> str:
        return obj.status.value.upper()

    async def on_save(
        self, request: Request, session: AsyncSession, obj: Task, *, created: bool
    ) -> None:
        obj.title = obj.title.strip()
        if obj.title.lower() == "todo":
            raise FormError("Give the task a real title.", field="title")

    @action("mark_done", label="Mark done", bulk=True, confirm="Mark the selected tasks as done?")
    async def mark_done(
        self, request: Request, session: AsyncSession, objs: Sequence[Task]
    ) -> ActionResult:
        for task in objs:
            task.status = TaskStatus.done
        return ActionResult.message(f"{len(objs)} task(s) marked done.")

    @action("raise_priority", label="Raise priority")
    async def raise_priority(
        self, request: Request, session: AsyncSession, obj: Task
    ) -> ActionResult:
        if obj.priority <= 1:
            return ActionResult.message("Already at top priority.", level="warning")
        obj.priority -= 1
        return ActionResult.message(f"Priority raised to {obj.priority}.")


@admin.page("/stats", title="Statistics", category="Reports", icon="chart-column")
async def stats(session: Annotated[AsyncSession, Depends(get_session)]) -> Page:
    rows = (await session.execute(select(Task.status, func.count()).group_by(Task.status))).all()
    counts = dict.fromkeys(TaskStatus, 0) | {row[0]: row[1] for row in rows}
    return Page("stats.html", {"counts": counts})


@admin.route("/stats/{status}", title="Tasks by status")
async def tasks_by_status(
    status: TaskStatus, session: Annotated[AsyncSession, Depends(get_session)]
) -> Page:
    stmt = select(Task).where(Task.status == status).order_by(Task.due_date, Task.id)
    tasks = (await session.scalars(stmt)).all()
    return Page("stats_status.html", {"status": status, "tasks": tasks})
