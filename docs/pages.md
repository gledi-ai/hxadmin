# Custom pages

Custom pages are ordinary FastAPI endpoints under the admin's prefix that render inside the admin shell. This page uses the [docs models](getting-started.md#the-models-in-these-docs) and the `get_session` dependency from [Getting started](getting-started.md#a-minimal-admin).

```python
from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hxadmin import Page
from myapp.models import Task, TaskStatus


@admin.page("/stats", title="Statistics", category="Reports", icon="chart-column")
async def stats(session: Annotated[AsyncSession, Depends(get_session)]) -> Page:
    rows = (await session.execute(select(Task.status, func.count()).group_by(Task.status))).all()
    counts = dict.fromkeys(TaskStatus, 0) | {status: count for status, count in rows}
    return Page("stats.html", {"counts": counts})


@admin.route("/stats/{status}", title="Tasks by status")
async def tasks_by_status(
    status: TaskStatus, session: Annotated[AsyncSession, Depends(get_session)]
) -> Page:
    stmt = select(Task).where(Task.status == status).order_by(Task.due_date, Task.id)
    tasks = (await session.scalars(stmt)).all()
    return Page("stats_status.html", {"status": status, "tasks": tasks})
```

The templates go in the directory passed as `HxAdmin(templates_dir=...)`, and extend `page.html`, filling `{% block body %}`:

```jinja
{# stats.html #}
{% extends "page.html" %}
{% import "_macros.html" as m with context %}
{% block body %}
<div class="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-4">
  {% for status, count in counts.items() %}
  {{ m.stat(status.value.capitalize(), count, href=admin.url(request, '/stats/' ~ status.value)) }}
  {% endfor %}
</div>
{% endblock %}
```

```jinja
{# stats_status.html #}
{% extends "page.html" %}
{% block body %}
<ul class="divide-y divide-border rounded-lg border border-border bg-surface">
  {% for task in tasks %}
  <li class="px-3 py-2 text-sm">
    <a href="{{ admin.url(request, '/task/' ~ task.id) }}" class="text-accent hover:underline">{{ task.title }}</a>
  </li>
  {% else %}
  <li class="px-3 py-2 text-sm text-fg-muted">No tasks.</li>
  {% endfor %}
</ul>
{% endblock %}
```

The repository's demo has this exact pair of pages (`demo/app.py`, `demo/templates/`).

Handlers are ordinary `async` FastAPI endpoints (`Depends`, path and query parameters, `methods=("POST",)`), guarded by `auth`. A path parameter with a type, like `status: TaskStatus`, is validated by FastAPI: `/stats/nope` answers 422. Return `Page(template, context)` to render inside the admin shell, or any `Response` or JSON-able value.

Templates also get `admin`, `request`, `user`, `nav` and `admin_page` (also as `page` unless your context sets its own). Build links with `admin.url(request, path)`, which adds the admin's prefix, rather than hard-coding `/admin`.

`admin.page` adds a sidebar entry under `category`; `admin.route` does not, and it may take path parameters. A page path may not start with a registered view identity or `static`: `/task/report` would raise at registration, because `/task/...` belongs to `TaskView`.

## Pages that write

hxadmin does not commit for custom pages: changes a handler leaves uncommitted are discarded when the session closes at the end of the request. A POST handler commits itself and then redirects, so reloading the page does not submit again:

```python
from fastapi import Request
from sqlalchemy import update
from starlette.responses import Response


@admin.page("/maintenance", title="Maintenance", category="Reports", icon="archive")
async def maintenance(session: Annotated[AsyncSession, Depends(get_session)]) -> Page:
    done = await session.scalar(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.done, ~Task.archived)
    )
    return Page("maintenance.html", {"done": done or 0})


@admin.route("/maintenance", methods=("POST",))
async def archive_done(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> Response:
    await session.execute(
        update(Task).where(Task.status == TaskStatus.done, ~Task.archived).values(archived=True)
    )
    await session.commit()
    return admin.redirect(request, admin.url(request, "/maintenance"))
```

```jinja
{# maintenance.html #}
{% extends "page.html" %}
{% import "_macros.html" as m with context %}
{% block body %}
<form method="post" class="flex items-center gap-4">
  <p class="text-sm">{{ done }} done task(s) not archived yet.</p>
  {{ m.button("Archive them", variant="primary", type="submit", disabled=not done) }}
</form>
{% endblock %}
```

`admin.redirect` answers a plain form post with a 303 and an htmx request with `HX-Redirect`, the same way hxadmin's own forms do. The same path can carry a GET page and a POST route, as here; registering the same method twice raises.

Writes to custom pages get the same [cross-site protection](auth.md#cross-site-requests) as the rest of the admin, so the form above needs no CSRF token. A plain form post leaves htmx out entirely; for an htmx form (`hx-post`), return a partial or `admin.redirect`.

## Components

A page body is regular admin-shell content, so it can use the component macros — `stat`, `card`, `badge`, `button`, `empty_state` and the rest — the same way a built-in template does; see [Templates and theming](templates.md#components).
