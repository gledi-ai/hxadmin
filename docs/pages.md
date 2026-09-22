# Custom pages

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

Handlers are ordinary `async` FastAPI endpoints (`Depends`, path and query parameters, `methods=("POST",)`), guarded by `auth`. Return `Page(template, context)` to render inside the admin shell, or any `Response` or JSON-able value.

Templates also get `admin`, `request`, `user`, `nav` and `admin_page` (also as `page` unless your context sets its own).

`admin.page` adds a sidebar entry under `category`; `admin.route` does not, and it may take path parameters. A page path may not start with a registered view identity or `static`.
