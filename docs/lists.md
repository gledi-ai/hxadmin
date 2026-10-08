# Lists and filters

The list page at `/{prefix}/{identity}/` searches, sorts, filters and paginates through query parameters, so every state has a URL you can bookmark or share:

| Parameter | Meaning |
|---|---|
| `q` | Search over `searchable` columns |
| `sort`, `dir` | Sort column and `asc` / `desc`; ties, and lists with no sort, are ordered by primary key |
| `page`, `size` | Page number and page size (one of `page_size_options`) |
| `f.<name>...` | Filters, below |

Invalid values fall back to the defaults. Requests with `HX-Request: true` get only the table partial, plus out-of-band updates for the filter summaries, the Reset button and the export links, so an open filter popover stays open while the table refreshes.

## Table

The header shows the plural name with the row count ("Tasks · 6", updated as you search and filter) and the New button. The table sits in a bordered card that scrolls within the viewport, with a sticky header. Columns size to their content; the primary column takes the remaining width and is the only link, to the detail page (when `can_view`). The primary column is the first text or many-to-one relation column of `list_columns` that is not the primary key, or the first column when there is none: with `list_columns = ("id", "title", "status")` it is `title`. To make a column the link, list a text column first or reorder them. Relations render as plain muted text, enums and declared bools as badges (see [Badges](views.md#badges)), other bools as a check or cross icon, and missing values as `—`. Numbers are right-aligned with tabular figures. Checked rows are highlighted.

With no rows, the table is replaced by an empty state: "No tasks yet" with a "New task" button, or "No tasks match these filters" with a "Reset filters" button when a search or filter is active.

Below the `sm` breakpoint, rows render as stacked cards instead: a checkbox, the primary column as the title, the next three list columns as `label: value` pairs, and the row menu. The search box shares the first toolbar row with Export, the filter buttons scroll horizontally on the row below, and a Select all checkbox sits above the cards.

## Filters

```python
@admin.register
class TaskView(ModelView[Task]):
    model = Task
    list_filters = ("status", "priority", "due_date", "title", "project", "assignee")
```

With the [docs models](getting-started.md#the-models-in-these-docs), this gives `status` checkboxes (todo, doing, done), a `priority` and a `due_date` range, a "Contains…" box for `title`, and checkboxes of projects and users. `due_date` and `assignee` are nullable, so they also get **Empty**: "tasks without a due date" is `?f.due_date.empty=1`, and "unassigned or assigned to user 1" is `?f.assignee=1&f.assignee.empty=1`.

`list_filters` names columns or many-to-one relations. The control follows the column type:

| Column type | Control | Query parameters | Matches |
|---|---|---|---|
| enum, bool | checkboxes | `f.status=todo&f.status=doing`; bool uses `true` / `false` | any checked value |
| int, float, numeric, date, datetime, time | from / to inputs | `f.priority.min=2&f.priority.max=4` | inclusive range |
| string, text, uuid, other types | text box | `f.title=report` | case-insensitive substring of the value cast to text |
| many-to-one relation | checkboxes of related rows | `f.project=3` (primary key; `;`-joined if composite) | any checked row |

Range bounds are written back the way their inputs write them (`2026-02-01` on a datetime becomes `2026-02-01T00:00`). A bound with a UTC offset on a column without time zone is converted to UTC. Values no database could compare, such as non-finite numbers, are ignored.

Nullable columns and optional relations get an extra **Empty** checkbox (`f.<name>.empty=1`) that also matches rows without a value. Different filters combine with AND.

Relation filters offer the first 100 rows of the related model, through its view's `get_query` when it is registered, in that query's own order and then by primary key. If the related view is not accessible to the current user, the filter is hidden. Matching a checked row compares primary keys only; it narrows rows the list already shows and does not apply the related view's `get_query` again. Filters on to-many relations, on the side of a one-to-one without the foreign key, and on JSON columns are not supported and raise at registration.

Each visible filter gets its own pill in the toolbar: dashed with a `+` icon and the label when inactive, solid with the label and a summary of the active value when it has one. The summary shows up to two values as badges (otherwise "N selected"), a range as `≥2`, `≤5` or `2–5`, and text as the quoted value, with "Empty" appended when set.

Clicking a pill opens its popover, and changes apply immediately:

- choice and relation filters: a search box that narrows the options, a checkbox list, then Empty and Clear;
- numeric ranges: From and To number inputs;
- date, datetime and time ranges: From and To [date pickers](forms.md#dates-and-times), which submit ISO values (`2026-09-23`, `2026-09-23T14:30`, `14:30`) under the same `f.<name>.min` / `.max` names;
- text: one "Contains…" input.

A Reset button appears once any filter is active. Sorting, paging, actions, export and returning to the list after a delete keep the active filters.

## Row menu

Every row has a `⋯` button in its last column, always visible, opening a menu with View (when `can_view`), Edit (when `can_edit`), the row's permitted actions, a separator, then Delete in danger colour (when `can_delete`). Delete and actions with `confirm` open the shared confirm dialog; choosing any item closes the menu. The menu is keyboard-navigable: arrows move, Home and End jump, Esc closes and returns focus to the button.

## Bulk actions

Checking one or more rows shows a floating bar centred at the bottom of the viewport: the selection count, the bulk actions as buttons, an Export menu for the selected rows when export is enabled, and a `✕` to clear the selection. It floats over the page without shifting the layout, and the select-all checkbox shows an indeterminate state when some but not all visible rows are checked. The selection covers the rows on screen: sorting, paging, filtering or a bulk action re-renders the table and clears it.
