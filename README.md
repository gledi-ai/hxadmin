# hxadmin

Admin interface for FastAPI and SQLAlchemy 2.0+, built with Tailwind CSS and htmx.

## Usage

```python
from fastapi import FastAPI
from hxadmin import HxAdmin, ModelView

app = FastAPI()
admin = HxAdmin(app, session=get_session, auth=current_admin_user, title="My Admin")


@admin.register
class UserView(ModelView[User]):
    model = User
    category = "Auth"
    list_columns = ("email", "name", "group")  # default: all columns
    detail_columns = ()  # default: all columns and relationships
    searchable = ("email", "name")
    sortable = ()  # default: every column in list_columns
    default_sort = ("email", "asc")
    page_size = 25
    page_size_options = (25, 50, 100)

    def format_name(self, obj: User) -> str:  # per-column display override
        return obj.name.title()
```

`session` yields an `AsyncSession`; `auth` returns the current user or raises `HTTPException(401)`. Both are ordinary FastAPI dependencies.

Lists support `?q=`, `?sort=&dir=`, `?page=&size=`; requests with `HX-Request: true` get only the table partial. Detail pages show scalar columns and single relations inline and load collection relations lazily in tabs. Override `get_query(request)` to scope rows.

Rebuild CSS after editing templates: `nox -s css` (needs Node.js).

## Development

```bash
uv sync            # installs the dev group (lint + test + ipython)
prek install       # git hooks: ruff, pyrefly, uv-lock
nox                # lint + tests on every supported Python
nox -s tests-3.14  # single Python version
nox -s tests_lowest  # tests against the lowest supported dependency versions
nox -s wheel       # tests against the built wheel
nox -s audit       # dependency vulnerability audit
```

Versions come from git tags (`v0.1.0`) via uv-dynamic-versioning.
