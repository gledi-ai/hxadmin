# Getting started

## Install

```bash
pip install hxadmin            # CSV export included
pip install 'hxadmin[xlsx]'    # adds Excel export (XlsxWriter)
```

hxadmin needs Python 3.13+, FastAPI and SQLAlchemy 2.0+ with an async driver (`asyncpg`, `aiosqlite`, ...).

## The models in these docs

The examples throughout these docs use the same three models, a small task tracker. They are the repository's demo models plus a few columns (`active`, `is_superuser`, `password_hash`, `archived`) and a `PasswordReset` table that later examples need:

```python
# myapp/models.py
import enum
from datetime import date, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


project_members = Table(
    "project_members",
    Base.metadata,
    Column("project_id", ForeignKey("projects.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class TaskStatus(enum.StrEnum):
    todo = "todo"
    doing = "doing"
    done = "done"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    is_superuser: Mapped[bool] = mapped_column(default=False)
    password_hash: Mapped[str | None]
    projects: Mapped[list["Project"]] = relationship(
        secondary=project_members, back_populates="members"
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="assignee")

    def __str__(self) -> str:
        return self.name


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None]
    members: Mapped[list[User]] = relationship(secondary=project_members, back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")

    def __str__(self) -> str:
        return self.name


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    status: Mapped[TaskStatus] = mapped_column(default=TaskStatus.todo)
    priority: Mapped[int] = mapped_column(default=3)
    due_date: Mapped[date | None]
    archived: Mapped[bool] = mapped_column(default=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="tasks")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    assignee: Mapped[User | None] = relationship(back_populates="tasks")

    def __str__(self) -> str:
        return self.title


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

`__str__` matters: it is what hxadmin shows for a row in titles, relation cells, comboboxes and toasts. Without it a row shows as `User 3`. See `display` in [Views](views.md#hooks) to change it per view instead.

## A minimal admin

```python
# myapp/main.py
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hxadmin import HxAdmin, ModelView
from myapp.models import Base, Project, Task, User

engine = create_async_engine("sqlite+aiosqlite:///app.db")
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


def current_admin_user() -> dict[str, str]:
    return {"name": "admin"}  # lets everyone in: replace before deploying, see below


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
admin = HxAdmin(app, session=get_session, auth=current_admin_user, title="My admin")


@admin.register
class UserView(ModelView[User]):
    model = User


@admin.register
class ProjectView(ModelView[Project]):
    model = Project


@admin.register
class TaskView(ModelView[Task]):
    model = Task
```

Run it with `uvicorn myapp.main:app` and open <http://127.0.0.1:8000/admin/>. The `lifespan` only creates the tables so the example starts on an empty database; a real project runs its migrations (Alembic, ...) instead.

The admin is mounted at `prefix` (default `/admin`). The dashboard lists every registered view with its row count, grouped under a heading per `category`; a category holding a single view joins the ungrouped cards, labelled with its category, instead of heading one card.

!!! warning "The `auth` above lets anyone in"

    `current_admin_user` returns a fixed user for every request, so anyone who can reach `/admin/` can read, edit and delete every row. It is fine on your own machine. Before the admin is reachable by anyone else, replace it with a dependency that checks who is asking; [Auth and sessions](auth.md#auth) has a complete example.

`session` and `auth` are ordinary FastAPI dependencies; see [Auth and sessions](auth.md).

## Branding

Pass `logo_url` for an image in the sidebar brand block:

```python
admin = HxAdmin(
    app, session=get_session, auth=current_admin_user, title="My admin", logo_url="/static/logo.svg"
)
```

The URL is used as given, so it must be served by your app (for example with FastAPI's `StaticFiles`) or come from elsewhere. Without it, the brand block shows the title's first letter in an accent tile.

## The demo

The repository ships a small todo app that exercises every feature:

```bash
uv run python -m demo
```

Then open <http://127.0.0.1:8001/admin/>. The demo creates and seeds `demo/demo.db` on first start.
