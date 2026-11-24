# hxadmin

Admin interface for FastAPI and async SQLAlchemy 2.0+, built with Jinja2, htmx, Alpine.js and Tailwind CSS.

List, detail, create, edit and delete from class attributes, with search, sort, pagination, per-column filters, row and bulk actions, custom pages, CSV import, CSV / Excel export and light / dark themes. Async only and fully typed.

## Install

```bash
pip install hxadmin            # CSV export included
pip install 'hxadmin[xlsx]'    # adds Excel export
```

## Quickstart

```python
from fastapi import FastAPI
from hxadmin import HxAdmin, ModelView

app = FastAPI()
admin = HxAdmin(app, session=get_session, auth=current_admin_user, title="My admin")


@admin.register
class UserView(ModelView[User]):
    model = User
    list_columns = ("email", "name", "active")
    searchable = ("email", "name")
    list_filters = ("active",)
    export_formats = ("csv",)
```

`session` yields an `AsyncSession`; `auth` returns the current user or raises `HTTPException(status.HTTP_401_UNAUTHORIZED)`. Open `/admin/`.

Documentation: [gledi-ai.github.io/hxadmin](https://gledi-ai.github.io/hxadmin/) (build locally with `nox -s docs`). Run `make demo` and open http://127.0.0.1:8001/admin/. Sign in as `ada@example.com` for full access or `staff@example.com` for read-only access. Both use the password `demo`. For projects built on plain Core `Table`s instead of ORM models, see `make demo/tables` (http://127.0.0.1:8002/admin/, `admin@example.com` / `demo`).

To try audit history, edit a task in the ORM demo or a stock move in the Core table demo, then open **History** on its detail page. See the [audit history guide](docs/audit.md) to enable it in your app.

## Development

```bash
uv sync            # installs the dev group (lint + test + demo + ipython)
prek install       # git hooks: ruff, pyrefly, zizmor, uv-lock, Conventional Commits
nox                # lint + tests on every supported Python
nox -s tests-3.14  # single Python version
nox -s tests_lowest  # tests against the lowest supported dependency versions
nox -s tests_latest  # tests against the newest allowed releases (weekly in CI)
nox -s wheel       # tests against the built wheel
nox -s audit       # dependency vulnerability audit
nox -s docs        # build the docs strictly into site/
nox -s css         # rebuild hxadmin.css after template changes (needs Node.js)
```

Versions come from git tags (`v0.1.0`) via uv-dynamic-versioning.
