import anyio
import python_multipart
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]


class UserIn(BaseModel):
    email: str


def test_supported_dependency_versions_work_together() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(email=UserIn(email="a@example.com").email))
        session.commit()
        assert session.scalars(select(User.email)).one() == "a@example.com"
    engine.dispose()
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    assert TestClient(app).get("/ping").json() == {"ok": True}
    assert anyio.__name__
    assert python_multipart.__name__
