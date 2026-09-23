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

Range bounds are written back the way their inputs write them (`2026-02-01` on a datetime becomes `2026-02-01T00:00`). A bound with a UTC offset on a column without time zone is converted to UTC. Values no database could compare, such as non-finite numbers, are ignored.

Nullable columns and optional relations get an extra **Empty** checkbox (`f.<name>.empty=1`) that also matches rows without a value. Different filters combine with AND.

Relation filters offer the first 100 rows of the related model, through its view's `get_query` when it is registered, in that query's own order and then by primary key. If the related view is not accessible to the current user, the filter is hidden. Matching a checked row compares primary keys only; it narrows rows the list already shows and does not apply the related view's `get_query` again. Filters on to-many relations, on the side of a one-to-one without the foreign key, and on JSON columns are not supported and raise at registration.

Each visible filter gets its own toolbar button: a dashed outline with a `+` icon and the label when inactive, a solid button with a summary of the active value when it has one — up to two values as badges (otherwise "N selected"), a range as "≥ 2", "≤ 5" or "2–5", and text as the quoted value, with "Empty" appended when set. Clicking a button opens its popover — a search box and checkbox list for choice and relation filters, from/to inputs for ranges, a single input for text — and changes apply immediately. A "Reset" ghost button appears once any filter is active. Sorting, paging, actions, export and returning to the list after a delete keep the active filters.

## Row menu

Every row has a `⋯` button in its last column, always visible, opening a menu with View, Edit, the row's permitted actions, a separator, then Delete in danger colour. Destructive items open the shared confirm dialog.

## Bulk actions

Checking one or more rows shows a floating bar centred at the bottom of the viewport: the selection count, the bulk actions as buttons, an Export menu for the selection when export is enabled, and a `✕` to clear the selection. It never shifts the page layout, and the header's select-all checkbox shows an indeterminate state when some but not all visible rows are checked.
