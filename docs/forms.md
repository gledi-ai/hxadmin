# Forms

Create and edit forms are derived from the mapper:

- autoincrement primary keys and foreign-key columns covered by a relationship are skipped;
- enum columns become selects, booleans checkboxes, dates and times native pickers;
- relationships become a search-as-you-type combobox, backed by the related view's `searchable` columns;
- primary keys, including relationships whose foreign keys form the primary key, are read-only on edit.

```python
from hxadmin import Field


@admin.register
class UserView(ModelView[User]):
    model = User
    form_fields = (
        Field("name", "str", help_text="Full name"),
        Field("email", "str", "E-mail", widget="email"),
        "projects",
    )
    form_exclude = ("password_hash",)
```

`form_fields` takes names or `Field(...)` overrides for `label`, `widget`, `required`, `help_text` and `readonly`. An empty non-nullable input is left to the model default on create and reported as required on edit. `DateTime(timezone=True)` columns receive naive values from `datetime-local` inputs.

## Saving

Validation errors re-render the form in place with status 422. On success, `on_save(request, session, obj, *, created)` runs, then hxadmin commits and redirects with a toast such as *Task "Write docs" created.*

Raise `FormError` from `on_save` to reject a save with a message:

```python
from hxadmin import FormError


class TaskView(ModelView[Task]):
    async def on_save(
        self, request: Request, session: AsyncSession, obj: Task, *, created: bool
    ) -> None:
        if obj.due_date is not None and obj.due_date < date.today():
            raise FormError("Due date is in the past.", field="due_date")
```

The session is rolled back and the form re-renders with the message under `field`, or at the top of the form when `field` is omitted or not on the form. Integrity errors also roll back and show a form-level error. Any other exception rolls back and propagates.

Deleting runs `on_delete(request, session, obj)` first; a row that other rows still reference answers 409.
