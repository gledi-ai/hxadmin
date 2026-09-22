# hxadmin

Admin interface for FastAPI and async SQLAlchemy 2.0+, built with Jinja2, htmx, Alpine.js and Tailwind CSS.

List, detail, create, edit and delete from class attributes, with search, sort, pagination, per-column filters, row and bulk actions, custom pages, CSV / Excel export and light / dark themes. Async only and fully typed.

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
    list_columns = ("email", "name", "group")
    searchable = ("email", "name")
    list_filters = ("active", "group")
    export_formats = ("csv", "xlsx")
```

`session` yields an `AsyncSession`; `auth` returns the current user or raises `HTTPException(401)`. Open `/admin/`.

Documentation: [`docs/`](docs/index.md) (build locally with `nox -s docs`). Try everything in the demo: `uv run python -m demo`, then open http://127.0.0.1:8001/admin/.

## Development

```bash
uv sync            # installs the dev group (lint + test + ipython)
prek install       # git hooks: ruff, pyrefly, uv-lock
nox                # lint + tests on every supported Python
nox -s tests-3.14  # single Python version
nox -s tests_lowest  # tests against the lowest supported dependency versions
nox -s wheel       # tests against the built wheel
nox -s audit       # dependency vulnerability audit
nox -s docs        # build the docs strictly into site/
nox -s css         # rebuild hxadmin.css after template changes (needs Node.js)
```

Versions come from git tags (`v0.1.0`) via uv-dynamic-versioning.
