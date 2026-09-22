# hxadmin

Admin interface for FastAPI and SQLAlchemy 2.0+, built with Tailwind CSS and htmx.

## Usage

```python
from fastapi import FastAPI
from hxadmin import Field, HxAdmin, ModelView

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
    form_exclude = ("password_hash",)

    def format_name(self, obj: User) -> str:  # per-column display override
        return obj.name.title()
```

`session` yields an `AsyncSession`; `auth` returns the current user or raises `HTTPException(401)`. Both are ordinary FastAPI dependencies.

Lists support `?q=`, `?sort=&dir=`, `?page=&size=`; requests with `HX-Request: true` get only the table partial. Detail pages show scalar columns and single relations inline and load collection relations lazily in tabs. Override `get_query(request)` to scope rows.

Forms are derived from the mapper: autoincrement primary keys and FK columns covered by a relationship are skipped, enum columns become selects, relationships become a search-as-you-type combobox (`/_lookup`). Primary keys — including relationships whose FK columns form the primary key — are read-only on edit. Configure with `form_fields` (names or `Field(...)` overrides for `label`, `widget`, `required`, `help_text`, `readonly`), `form_exclude`, `can_create`, `can_edit`, `can_delete`, and the `on_save(request, session, obj, *, created)` / `on_delete(request, session, obj)` hooks, which run before commit. Validation errors re-render the form in place (422); integrity errors roll back and show a form-level error.

HxAdmin has no CSRF protection of its own; put it behind your session/CSRF middleware if the admin is cookie-authenticated. `DateTime(timezone=True)` columns receive naive values from `datetime-local` inputs.

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
