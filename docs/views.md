# Views

A `ModelView[T]` subclass configures one SQLAlchemy model. Register it with `@admin.register`; configuration errors (unknown column names, unsortable default sort, unfilterable filters, unknown export formats) raise at registration.

```python
@admin.register
class TaskView(ModelView[Task]):
    model = Task
    name = "Task"  # default: the model class name
    name_plural = "Tasks"  # default: name + "s"
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

Every enum column renders as a badge; `badges` declares which tone each value gets. Undeclared enum values fall back to a neutral badge. Bool columns render as plain text unless declared here.

```python
class TaskView(ModelView[Task]):
    model = Task
    badges = {
        "status": {"done": "success", "doing": "accent", "todo": "neutral"},
        "archived": {"true": "neutral"},
    }
```

Keys are column names; inner keys are the enum's `.value` strings, or `"true"` / `"false"` for a bool column. Tones are `"neutral" | "accent" | "success" | "warning" | "danger"`. An unknown column name or an unknown tone raises `ValueError` at registration.

## Hooks

| Method | Purpose |
|---|---|
| `get_query(request)` | Base `select()` for every list, detail, action and export; scope rows here |
| `format_<column>(obj)` | Display override for one column, used in lists, detail and export |
| `display(obj)` | Label of a row (default: `str(obj)` if the model defines `__str__`) |
| `on_save(request, session, obj, *, created)` | Runs before commit on create and edit |
| `on_delete(request, session, obj)` | Runs before delete |
| `is_visible(request)` | Show the view in the sidebar and dashboard |
| `is_accessible(request)` | Allow access at all (403 otherwise) |
| `is_action_allowed(request, name)` | Allow one action; see [Actions](actions.md) |

```python
class TaskView(ModelView[Task]):
    def get_query(self, request: Request) -> Select[tuple[Task]]:
        return super().get_query(request).where(Task.archived.is_(False))

    def format_status(self, obj: Task) -> str:
        return obj.status.value.upper()
```

Relationships used in lists and detail are eager-loaded. Anything a template or `format_` method touches beyond those must be loaded by `get_query`, because async SQLAlchemy cannot lazy-load.
