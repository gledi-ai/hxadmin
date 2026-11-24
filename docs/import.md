# CSV import

Set `import_columns` to add **Import CSV** to a model's list page.

```python
@admin.register
class TaskView(ModelView[Task]):
    model = Task
    import_columns = ("title", "project", "status", "due_date", "assignee")
```

Use writable create field names and include every required create field. The template uses the configured order, and an upload may reorder the columns or omit optional ones. Uploads require a header and accept up to 500 records and 1 MiB of UTF-8 CSV per file. Use the downloadable template for the import headers. [Exports](export.md) can contain formatted values and relationship labels.

Use the stored value for enums (for example, `todo`), `true` or `false` for booleans, and ISO 8601 for dates and times. Leave optional cells blank for the usual create defaults or nulls. A many-to-one field takes the related record's primary key. For a composite key, join its components with `;` in mapper primary-key order. The related view's access rules and query scope apply.

**Preview import** shows the submitted values, CSV line numbers, and field or relationship errors without saving. **Import records** checks the data again and creates all rows in a single transaction. Save hooks and database constraints can reject a row during confirmation, in which case the batch rolls back. Each record uses `on_save(..., created=True)` and gets a history entry when [audit history](audit.md) is enabled. Leave transaction control to hxadmin inside the hook.

Import is create-only. Access follows the view's normal [create permission](views.md#permissions-per-operation).
