# Forms

Create and edit forms are derived from the mapper:

- autoincrement primary keys, foreign-key columns covered by a relationship, and columns of a type hxadmin has no input for (`LargeBinary`, `ARRAY`, `Interval`, ...) are skipped; naming such a column in `form_fields` raises at registration;
- `String(n)` columns accept at most `n` characters, and integer columns the range of their type (`SmallInteger` 16-bit, `Integer` 32-bit, `BigInteger` 64-bit);
- enum columns become selects, booleans checkboxes, dates and times the themed [date picker](#dates-and-times);
- relationships become a search-as-you-type combobox, backed by the related view's `searchable` columns (without any, it matches each row's display text, scanning the first 2,000 rows, so give large related tables `searchable` columns): a single relation looks like a select showing the current value with a clear `×`, a multiple one shows its values as removable chips;
- primary keys, including relationships whose foreign keys form the primary key, are read-only on edit.

The form is a left-aligned column up to 720px wide. Short fields (selects, numbers, checkboxes, dates and times, single relations) sit two to a row from the `sm` breakpoint; text, JSON and multiple relations take the full width.

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

`form_fields` takes names or `Field(...)` overrides for `label`, `widget`, `required`, `help_text` and `readonly`. An empty non-nullable input is left to the model default on create and reported as required on edit. `DateTime(timezone=True)` columns receive naive values from the datetime picker.

Each field shows its label (with a red `*` when required), the input, the help text and then the error. The Cancel / Save footer sticks to the bottom of the viewport on long forms; the edit page title carries the row's `#pk`.

## Dates and times

Date, datetime and time fields use a vendored [Air Datepicker](https://air-datepicker.com), themed with the admin tokens in light and dark. The visible input shows `mm/dd/yyyy` (plus `hh:mm`), while a hidden input carries the submitted ISO value: `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM` or `HH:MM`. Clearing the input with its `×` clears the value. Use it in your own templates through the `date_input` macro:

```jinja
{% import "_macros.html" as m with context %}
{{ m.date_input("published_at", "2026-09-23T14:30", kind="datetime") }}
```

`date_input(name, value=None, kind="date" | "datetime" | "time", id=None, required=False, error=False, readonly=False, form=None, class="", value_class="")`: `class` styles the visible input, `value_class` goes on the hidden one, and `form` sets the hidden input's `form=` attribute. Every change fires a bubbling `change` event on the hidden input. Inside a popover, the calendar opens within it on click or ArrowDown.

## Saving

Validation errors re-render the form in place with status 422, with each message under its field and form-level errors in an alert above the fields. On success, `on_save(request, session, obj, *, created)` runs, then hxadmin commits and redirects with a toast such as *Task "Write docs" created.*

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

The session is rolled back and the form re-renders with the message under `field`, or at the top of the form when `field` is omitted or not on the form. Integrity errors (such as a duplicate unique value) and values the database rejects also roll back and show a generic form-level error; the database's own message, which can name constraints and values, goes to the `hxadmin` logger instead. Any other exception rolls back and propagates: htmx requests get a "Something went wrong." toast, page loads the error page.

Delete lives in the detail page's `⋯` menu and in each list row's menu, and asks first in the shared confirm dialog. Deleting runs `on_delete(request, session, obj)` first; a row that other rows still reference answers 409 with "other records still refer to it" (an error toast over htmx, else the error page).
