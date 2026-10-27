from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, ClassVar

from fastapi import Depends, FastAPI, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from demos.orm.auth import DEMO_PASSWORD, authenticate, current_user
from demos.orm.db import engine, get_session, sessionmaker
from demos.orm.models import Base, Project, Task, TaskStatus, User
from demos.orm.seed import seed
from hxadmin import ActionResult, BadgeTone, Field, FormError, HxAdmin, ModelView, Page, action


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        await seed(session)
    yield
    await engine.dispose()


app = FastAPI(title="Todo demo", lifespan=lifespan)
# Both demos run on 127.0.0.1, and cookies ignore the port, so each needs its own cookie name.
app.add_middleware(
    SessionMiddleware,
    secret_key="demo-only-not-a-secret",  # noqa: S106
    session_cookie="hxadmin_demo_session",
    https_only=False,
)
admin = HxAdmin(
    app,
    session=get_session,
    auth=current_user,
    title="Todo admin",
    login_url="/login",
    logout_url="/logout",
    templates_dir=Path(__file__).parent / "templates",
)
LOGIN_NOTE = f"Demo accounts: ada@, grace@ or linus@example.com, password {DEMO_PASSWORD!r}."


@app.get("/login", response_model=None)
async def login_form(request: Request) -> HTMLResponse | RedirectResponse:
    if "user_id" in request.session:
        return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
    return admin.render_login(request, note=LOGIN_NOTE)


@app.post("/login", response_model=None)
async def login(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    email = str(form.get("username", "")).strip()
    user = await authenticate(session, email, str(form.get("password", "")))
    if user is None:
        return admin.render_login(
            request,
            error="Wrong e-mail or password.",
            username=email,
            note=LOGIN_NOTE,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@admin.register
class UserView(ModelView[User]):
    model = User
    category = "People"
    icon = "users"
    list_columns = ("name", "email", "projects")
    detail_columns = ("name", "email", "projects", "tasks")
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
    badges: ClassVar[Mapping[str, Mapping[str, BadgeTone]]] = {
        "status": {"todo": "neutral", "doing": "accent", "done": "success"}
    }

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
