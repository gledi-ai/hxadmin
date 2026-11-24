# Audit history

hxadmin can record changes made through built-in create, edit, and delete forms and through custom actions that opt in. Enable auditing per view by selecting the columns to track. Each record's **History** tab shows who changed it, when, and which values changed.

## Set up the table

Define the table in a module that both your app and migration tooling import. Use the metadata for the database that holds the audited models. This example uses an ORM base, and an app using Core tables can pass its `MetaData` directly.

```python
# myapp/models/audit.py
from hxadmin import define_audit_table

from myapp.models.base import Base

audit_table = define_audit_table(Base.metadata)
```

`define_audit_table` adds the `hxadmin_audit` definition and its record lookup index to your metadata. The helper accepts keyword arguments `name` and `schema` when you need a different table location.

Generate or write a migration that creates the table and its index, review it, and apply it before deploying code that enables auditing. If you generate migrations from metadata, import the module above before comparing metadata against the database. hxadmin issues no schema changes at startup. Your app owns migration deployment, backups, and retention. Keep historical migrations fixed when upgrading hxadmin.

If your audit table predates custom action auditing, add a nullable `action_name` text column to it before upgrading hxadmin. Existing entries keep a `NULL` action name and display their original operation.

## Enable a view

```python
from hxadmin import HxAdmin, ModelView

from myapp.models import Task
from myapp.models.audit import audit_table

admin = HxAdmin(
    app,
    session=get_session,
    auth=current_admin_user,
    audit_table=audit_table,
    audit_actor=lambda user: str(user.id),
)


@admin.register
class TaskView(ModelView[Task]):
    model = Task
    audit_fields = ("status", "assignee_id")
```

`audit_actor` is a synchronous callback that receives the value returned by `auth`. Return a stable, non-empty string. For auth that returns a dictionary, use a key from that dictionary, such as `lambda user: user["email"]`. Use one audit table for all audited views on that database. The audit insert uses the same session and transaction as the model change.

Use mapped column names in `audit_fields`. For relationship assignments, select the underlying foreign-key column, such as `assignee_id`. Relationship collections and unsupported column types, such as binary columns, cannot be audited. Choose fields whose historical values are safe for authorized readers to see. An audited column can appear in history even if you omit it from `detail_columns`.

Removing a field from `audit_fields` stops tracking it and hides its values from the tab. Existing entries still contain the values in the database until you remove them there.

## What gets recorded

An entry stores a UTC timestamp, actor ID, view identity, record key, operation (`create`, `update`, or `delete`), and a JSON object of field changes. For example, updating `status` can produce:

```json
{"status": {"before": "open", "after": "done"}}
```

Create entries use `null` for each `before` value and delete entries use `null` for each `after` value. Updates include only changed audited fields. Saving with no changes to those fields adds no entry. Dates, times, UUIDs, and decimals are stored as strings.

For edits, hxadmin compares the values read before applying the form with the values persisted after `on_save` and flush. Audit entries roll back with failed writes. Leave the final commit to hxadmin in `on_save` and `on_delete` so both writes remain in one transaction. If your models use version checks to reject concurrent edits, those checks also apply to audited saves.

Custom pages, direct database writes, cascaded changes to other records, and changes that predate activation are outside this feature.

## Audit a custom action

Add `audit=True` to a POST action on a view that declares `audit_fields`:

```python
@action("raise_priority", label="Raise priority", audit=True)
async def raise_priority(self, request: Request, session: AsyncSession, obj: Task) -> ActionResult:
    if obj.priority > 1:
        obj.priority -= 1
    return ActionResult.message(f"Priority is {obj.priority}.")
```

Include `priority` in the view's `audit_fields` for this action. The same flag works with `bulk=True`. hxadmin compares the configured columns before and after the handler and writes one update entry for each changed target row. The entry includes the action name and the History tab shows its label. A no-op produces zero entries.

The handler can flush changes, and hxadmin commits them with the audit entries. Leave transaction commits and savepoint commits to hxadmin when auditing an action. The target rows must keep their identity and primary keys. This captures updates to the row or rows the handler receives. Additional rows created, updated, or deleted by the handler are outside its audit scope.

## Access and retention

The History tab requires the normal detail permission and a record visible through `get_query`. Override `is_history_allowed(request)` to restrict access further. The same checks apply to requests for older entries.

The audit table has no foreign keys to the actor or record. Deleting a record preserves its entries for inspection through your database tooling. The detail tab is available while the record exists. Keep view identities and primary keys stable. hxadmin separates uses of a key when it records the new create or prior delete, so avoid reusing keys outside hxadmin where neither event would be recorded.

## Try it in the demos

- Run `make demo`, sign in as `ada@example.com` with password `demo`, and use **Raise priority** on a task with priority above `1`. Open the task detail and select **History**. The ORM demo records the user's ID and action name. The **Mark done** bulk action also records status changes.
- Run `make demo/tables`, sign in as `admin@example.com` with password `demo`, and edit the quantity on a stock move. Open its detail and select **History**. The Core table demo records the signed-in email.

Both demos create the table through their existing local database setup. The seed data has no audit entries, so make an edit through the form to see one.
