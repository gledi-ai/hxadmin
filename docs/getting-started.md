# Getting started

## Install

```bash
pip install hxadmin            # CSV export included
pip install 'hxadmin[xlsx]'    # adds Excel export (XlsxWriter)
```

hxadmin needs Python 3.13+, FastAPI and SQLAlchemy 2.0+ with an async driver (`asyncpg`, `aiosqlite`, ...).

## A minimal admin

```python
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hxadmin import HxAdmin, ModelView
from myapp.models import User

engine = create_async_engine("sqlite+aiosqlite:///app.db")
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


def current_admin_user() -> dict[str, str]:
    return {"name": "admin"}


app = FastAPI()
admin = HxAdmin(app, session=get_session, auth=current_admin_user, title="My admin")


@admin.register
class UserView(ModelView[User]):
    model = User
```

Run it with `uvicorn myapp:app` and open `/admin/`. The admin is mounted at `prefix` (default `/admin`); the dashboard lists every registered view with its row count.

`session` and `auth` are ordinary FastAPI dependencies; see [Auth and sessions](auth.md).

## Branding

Pass `logo_url` for an image in the sidebar brand block:

```python
admin = HxAdmin(
    app, session=get_session, auth=current_admin_user, title="My admin", logo_url="/static/logo.svg"
)
```

Without it, the brand block shows the title's first letter in an accent tile.

## The demo

The repository ships a small todo app that exercises every feature:

```bash
uv run python -m demo
```

Then open <http://127.0.0.1:8001/admin/>.
