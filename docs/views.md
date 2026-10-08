# Views

A `ModelView[T]` subclass configures one SQLAlchemy model. Register it with `@admin.register`; configuration errors (unknown column names, unsortable default sort, unfilterable filters, unknown export formats) raise at registration.

```python
@admin.register
class TaskView(ModelView[Task]):
    model = Task
    name = "Task"  # default: the model class name
    name_plural = "Tasks"  # default: name + "s", so set it for "Category" -> "Categories"
    identity = "task"  # URL segment; default: model name, lower-case
    category = "Work"  # sidebar group
    icon = "table"  # any Lucide icon name; unknown names raise ValueError at registration
```

## Options

| Attribute | Default | Meaning |
|---|---|---|
| `list_columns` | all columns | Columns and relations shown in the list |
| `detail_columns` | all columns and relations | Fields on the detail page |
| `searchable` | `()` | Columns searched by `?q=` (case-insensitive substring) |
| `sortable` | every column in `list_columns` | Columns with sortable headers |
| `default_sort` | `None` | `("column", "asc" \| "desc")` |
| `page_size` / `page_size_options` | `25` / `(25, 50, 100)` | Pagination |
| `list_filters` | `()` | Filter panel; see [Lists and filters](lists.md) |
| `form_fields` / `form_exclude` | derived / `()` | See [Forms](forms.md) |
| `export_formats` / `export_columns` / `export_max_rows` | `()` / list columns / `10_000` | See [Export](export.md) |
| `can_view` / `can_create` / `can_edit` / `can_delete` | `True` | Enable pages and buttons |

## Badges

Every enum column renders as a badge, in lists, on the detail page and in the detail header; `badges` declares which tone each value gets. Undeclared enum values fall back to a neutral badge. Bool columns render as a check or cross icon unless declared here, in which case they become "Yes" / "No" badges.

```python
class TaskView(ModelView[Task]):
    model = Task
    badges = {
        "status": {"done": "success", "doing": "accent", "todo": "neutral"},
        "archived": {"true": "neutral"},
    }
```

Keys are column names; inner keys are the enum's `.value` strings, or `"true"` / `"false"` for a bool column. Tones are `"neutral" | "accent" | "success" | "warning" | "danger"`. An unknown column name, a value the column cannot hold (such as `"Done"` for `"done"`) or an unknown tone raises `ValueError` at registration.

## Detail page

The detail page at `/{prefix}/{identity}/{pk}` shows a back link to the list, the row's `display` as the title with up to two enum badges, and the actions on the right: the row actions as buttons when there are at most two and none needs confirmation (otherwise they move into the `⋯` menu), Edit, and a `⋯` menu holding Delete. The body is a card holding a description list, two columns wide from the `md` breakpoint with each label above its value: the columns first, then the to-one relations in their own group. Long text and JSON span both columns. Values use the same cell formatting as the list; relations link to the related row. When `detail_columns` is empty, foreign-key columns whose relation is also shown are hidden. To-many relations appear as tabs below, each loading its list when first shown.

## Hooks

| Method | Purpose |
|---|---|
| `get_query(request)` | Base `select()` for every list, detail, action and export; scope rows here |
| `format_<column>(obj)` | Display override for one column, used in lists, detail and export |
| `display(obj)` | Label of a row (default: `str(obj)` if the model defines `__str__`) |
| `on_save(request, session, obj, *, created)` | Runs before commit on create and edit; see [Forms](forms.md#saving) |
| `on_delete(request, session, obj)` | Runs before delete |
| `is_visible(request)` | Show the view in the sidebar, dashboard and command palette |
| `is_accessible(request)` | Allow access at all (403 otherwise); an inaccessible view is also left out of the sidebar, dashboard and palette |
| `is_action_allowed(request, name)` | Allow one action; see [Actions](actions.md#permissions) |

`request.state.hxadmin_user` is whatever your `auth` dependency returned, so the hooks can decide per user. The examples below assume the `auth` from [Auth and sessions](auth.md#auth), which returns the signed-in `User` row.

### Scoping rows with `get_query`

```python
from sqlalchemy import Select
from starlette.requests import Request


@admin.register
class TaskView(ModelView[Task]):
    model = Task

    def get_query(self, request: Request) -> Select[Task]:
        stmt = super().get_query(request).where(Task.archived.is_(False))
        user = request.state.hxadmin_user
        if not user.is_superuser:
            stmt = stmt.where(Task.assignee_id == user.id)
        return stmt
```

Everything that reads rows goes through `get_query`: the list and its count, the detail page, edit and delete, row and bulk actions, export, the dashboard count, the command palette, and the relation comboboxes and filters of other views that point at `Task`. A row outside the query answers 404, so a user cannot reach it by guessing its URL either.

`get_query` scopes reads, not writes: a non-superuser can still create a task assigned to someone else, after which it disappears from their list. Guard that in `on_save` with a `FormError` if it matters.

Keep `get_query` a plain `select(...)` of the model, narrowed with `where` (and `options` or `join` as needed). hxadmin adds its own search, filters, order and pagination on top. An `order_by` in it orders the list while no column is sorted (with the primary key as tie-breaker); sorting a column, or a `default_sort`, replaces it.

### Formatting a column

```python
class TaskView(ModelView[Task]):
    model = Task

    def format_due_date(self, obj: Task) -> str:
        return obj.due_date.strftime("%d %b %Y") if obj.due_date else "No due date"
```

The returned value is shown as text (HTML-escaped) in the list, the detail page and exports, in place of hxadmin's own rendering. A formatted enum or bool column therefore loses its badge or icon, and a formatted relation its link, so prefer `badges` for those. Exports get the formatted text too, so a formatted date column exports as text rather than as a date cell.

### Access per view

```python
@admin.register
class UserView(ModelView[User]):
    model = User

    def is_accessible(self, request: Request) -> bool:
        return request.state.hxadmin_user.is_superuser
```

`is_accessible` is enforced: every route of the view answers 403 for other users, and relations pointing at `User` from other views are locked (see [Lists and filters](lists.md#filters) and [Forms](forms.md)). `is_visible` only hides the view from the sidebar, dashboard and palette; its URLs keep working. Use `is_visible` for views that are reachable through links but too noisy for the sidebar, and `is_accessible` for anything that is a permission.

### Async and relations

Relationships used in lists and detail are eager-loaded. Anything a template or `format_` method touches beyond those must be loaded by `get_query`, because async SQLAlchemy cannot lazy-load: touching an unloaded relationship raises `MissingGreenlet`. For example, to show the project's name next to the title in a list that does not have a `project` column:

```python
from sqlalchemy.orm import selectinload


class TaskView(ModelView[Task]):
    model = Task
    list_columns = ("title", "status")

    def get_query(self, request: Request) -> Select[Task]:
        return super().get_query(request).options(selectinload(Task.project))

    def format_title(self, obj: Task) -> str:
        return f"{obj.title} ({obj.project.name})"
```

`format_` and `display` are plain synchronous methods, so they cannot run queries themselves.
