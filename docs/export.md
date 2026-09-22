# Export

```python
@admin.register
class TaskView(ModelView[Task]):
    model = Task
    export_formats = ("csv", "xlsx")  # default (): no export
    export_columns = ()  # default: list_columns
    export_max_rows = 10_000  # default; None removes the limit
```

CSV needs nothing extra. Excel export needs XlsxWriter:

```bash
pip install 'hxadmin[xlsx]'
```

Listing `"xlsx"` without it installed raises `ImportError` when the view is registered.

## What is exported

The list footer links to `/{prefix}/{identity}/_export/csv` (and `xlsx`) with the current search, filters and sort, and the export contains every matching row across all pages. With rows checked, the selection bar offers an export of just those rows. Rows always come through `get_query`.

When more rows match than `export_max_rows`, no file is produced: the browser returns to the list with a warning toast.

## Cells

The header row has the field labels. A column with a `format_<name>` method exports its output; otherwise:

| Value | CSV | XLSX |
|---|---|---|
| empty | empty | blank cell |
| bool | `true` / `false` | boolean |
| number | as written | number; NaN is `#NUM!`, infinity `#DIV/0!` |
| date, datetime, time | ISO 8601 | date cell; aware datetimes converted to UTC |
| enum | its value | text |
| many-to-one relation | the related row's `display()` | text |
| to-many relation | number of rows | number |
| JSON | JSON text | text |

CSV files are UTF-8 with a byte-order mark so Excel detects the encoding. Text cells starting with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'` so spreadsheet programs do not run them as formulas; XLSX cells are always written as text, never as formulas.

Excel's own limits apply to XLSX files: a cell holds at most 32,767 characters (longer text is cut), dates before 1900 are not real dates to Excel, and a sheet has at most 1,048,576 rows.

Files are named `{identity}-{YYYYMMDD-HHMMSS}.{csv|xlsx}` (UTC).
