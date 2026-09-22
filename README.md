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

Forms are derived from the mapper: autoincrement primary keys and FK columns covered by a relationship are skipped, enum columns become selects, relationships become a search-as-you-type combobox (`/_lookup`). Primary keys — including relationships whose FK columns form the primary key — are read-only on edit. Configure with `form_fields` (names or `Field(...)` overrides for `label`, `widget`, `required`, `help_text`, `readonly`), `form_exclude`, `can_create`, `can_edit`, `can_delete`, and the `on_save(request, session, obj, *, created)` / `on_delete(request, session, obj)` hooks, which run before commit; any exception they raise rolls the session back. An empty non-nullable input is left to the model default on create and reported as required on edit. Validation errors re-render the form in place (422); integrity errors roll back and show a form-level error.

HxAdmin has no CSRF protection of its own; put it behind your session/CSRF middleware if the admin is cookie-authenticated. `DateTime(timezone=True)` columns receive naive values from `datetime-local` inputs.

Rebuild CSS after editing templates: `nox -s css` (needs Node.js).

### Actions

```python
from collections.abc import Sequence

from hxadmin import ActionResult, action


@admin.register
class UserAdmin(ModelView[User]):
    model = User

    @action("deactivate", bulk=True, confirm="Deactivate selected users?")
    async def deactivate(
        self, request: Request, session: AsyncSession, objs: Sequence[User]
    ) -> ActionResult:
        for user in objs:
            user.active = False
        return ActionResult.message(f"Deactivated {len(objs)} users")

    @action("export", bulk=True, method="GET")
    async def export(
        self, request: Request, session: AsyncSession, objs: Sequence[User]
    ) -> ActionResult:
        return ActionResult.response(
            Response(
                to_csv(objs),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="users.csv"'},
            )
        )

    @action("reset_password", label="Reset password")
    async def reset_password(
        self, request: Request, session: AsyncSession, obj: User
    ) -> ActionResult:
        ...
        return ActionResult.message("Reset link sent", level="info")
```

Row actions (the default) receive one object and appear on the detail page and in each list row; bulk actions receive the checked rows — always loaded through `get_query` — and appear above the list once rows are selected. `confirm` opens the shared confirmation dialog. Return `ActionResult.message(text, level="success" | "info" | "warning" | "error")` to re-render the view with a toast, `ActionResult.redirect(url)`, or `ActionResult.response(response)`. HxAdmin commits after the handler returns; any exception rolls back and shows a "<label> failed." toast (the traceback goes to the `hxadmin` logger), except `HTTPException`, which propagates. POST actions run over htmx; `method="GET"` actions are plain links and form submits, so a returned file downloads. Handlers get objects without eager-loaded relationships: `await session.refresh(obj, ["group"])` before touching one. A row action that deletes its object should return a redirect; if it returns a message, HxAdmin falls back to the list.

### Custom pages

```python
from typing import Annotated

from fastapi import Depends

from hxadmin import Page


@admin.page("/sync", title="Sync management", category="Ops", icon="refresh")
async def sync_page(session: Annotated[AsyncSession, Depends(get_session)]) -> Page:
    return Page("sync.html", {"jobs": await load_jobs(session)})


@admin.route("/sync/{job_id}", title="Sync job")
async def sync_job(job_id: int) -> Page:
    return Page("sync_job.html", {"job": await load_job(job_id)})
```

```jinja
{# sync.html, in HxAdmin(templates_dir=...) #}
{% extends "page.html" %}
{% block body %}…{% endblock %}
```

Handlers are ordinary `async` FastAPI endpoints (`Depends`, path and query parameters, `methods=("POST",)`) guarded by `auth`. Return `Page(template, context)` to render inside the admin shell — templates also get `admin`, `request`, `user`, `nav` and `page` — or any `Response` / JSON-able value. `admin.page` adds a sidebar entry under `category`; `admin.route` does not and may take path parameters. A page path may not start with a registered view identity or `static`. Custom templates can use the Tailwind classes compiled into `hxadmin.css`; add your own stylesheet in `{% block head %}` for anything else.

The dashboard shows a card with the row count (through `get_query`) for every visible view, and the top bar searches any view with `searchable` columns.

Try it all in the demo: `uv run python -m demo`, then open http://127.0.0.1:8001/admin/.

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
