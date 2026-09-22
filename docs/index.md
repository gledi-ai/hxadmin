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

app = FastAPI()
admin = HxAdmin(app, session=get_session, auth=current_admin_user)


@admin.register
class UserView(ModelView[User]):
    model = User
    list_columns = ("email", "name", "group")
    searchable = ("email", "name")
    list_filters = ("active", "group")
    export_formats = ("csv",)
```

Start with [Getting started](getting-started.md).
