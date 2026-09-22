# Lists and filters

The list page at `/{prefix}/{identity}/` searches, sorts, filters and paginates through query parameters, so every state has a URL you can bookmark or share:

| Parameter | Meaning |
|---|---|
| `q` | Search over `searchable` columns |
| `sort`, `dir` | Sort column and `asc` / `desc` |
| `page`, `size` | Page number and page size (one of `page_size_options`) |
| `f.<name>...` | Filters, below |

Invalid values fall back to the defaults. Requests with `HX-Request: true` get only the table partial.

## Filters

```python
@admin.register
class TaskView(ModelView[Task]):
    model = Task
    list_filters = ("status", "priority", "due_date", "title", "project")
```

`list_filters` names columns or many-to-one relations. The control follows the column type:

| Column type | Control | Query parameters | Matches |
|---|---|---|---|
| enum, bool | checkboxes | `f.status=todo&f.status=doing`; bool uses `true` / `false` | any checked value |
| int, float, numeric, date, datetime, time | from / to inputs | `f.priority.min=2&f.priority.max=4` | inclusive range |
| string, text, uuid | text box | `f.title=report` | case-insensitive substring |
| many-to-one relation | checkboxes of related rows | `f.project=3` (primary key; `;`-joined if composite) | any checked row |

Nullable columns and optional relations get an extra **Empty** checkbox (`f.<name>.empty=1`) that also matches rows without a value. Different filters combine with AND.

Relation filters offer the first 100 rows of the related model, through its view's `get_query` when it is registered. If the related view is not accessible to the current user, the filter is hidden. Filters on to-many relations and JSON columns are not supported and raise at registration.

The **Filters** button opens the panel; changes apply immediately. Active filters appear as chips above the table; removing a chip clears that filter. Sorting, paging, actions and export keep the active filters.
