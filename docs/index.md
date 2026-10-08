# hxadmin

Admin interface for FastAPI and async SQLAlchemy 2.0+, rendered with Jinja2, htmx, Alpine.js and Tailwind CSS.

- One `ModelView` class per model: list, detail, create, edit and delete from class attributes.
- Search, sort, pagination and per-column filters on every list.
- Row and bulk actions with a shared confirmation dialog and toasts.
- Custom pages that share the admin shell.
- CSV export built in; Excel `.xlsx` export with the `xlsx` extra.
- Light, dark and system themes.
- Async only, fully typed (`py.typed`), no WTForms, no sync engines.

```python
from fastapi import FastAPI
from hxadmin import HxAdmin, ModelView

from myapp.db import get_session  # yields an AsyncSession
from myapp.models import Task

app = FastAPI()
admin = HxAdmin(app, session=get_session, auth=current_admin_user)


@admin.register
class TaskView(ModelView[Task]):
    model = Task
    list_columns = ("title", "status", "due_date", "project", "assignee")
    searchable = ("title",)
    list_filters = ("status", "due_date", "project")
    export_formats = ("csv",)
```

`current_admin_user` is your own FastAPI dependency that returns the signed-in user or raises `HTTPException(401)`. [Getting started](getting-started.md) builds this app step by step, models included, and [Auth and sessions](auth.md) shows a complete `auth`.
