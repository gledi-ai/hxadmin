import enum
from datetime import date

from sqlalchemy import Column, ForeignKey, Table
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
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="tasks")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    assignee: Mapped[User | None] = relationship(back_populates="tasks")

    def __str__(self) -> str:
        return self.title
