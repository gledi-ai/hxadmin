# Templates and theming

## Overriding templates

Pass `templates_dir` to search your own directory before the built-in templates:

```python
admin = HxAdmin(app, session=get_session, auth=current_admin_user, templates_dir="templates/admin")
```

A file with the same name as a built-in template replaces it:

| Template | Renders |
|---|---|
| `layout.html` | Shell: sidebar, top bar, toasts, confirmation dialog |
| `dashboard.html` | Dashboard cards |
| `list.html`, `list/_toolbar.html`, `list/_table.html`, `list/_pagination.html` | List page, search and filters, table, footer |
| `detail.html`, `detail/_panel.html` | Detail page |
| `form.html`, `form/_fields.html`, `form/_field.html` | Create and edit forms |
| `page.html` | Base for custom pages (`{% block body %}`) |
| `error.html` | Error pages |
| `_macros.html` | Icons, cells, buttons, filter controls |

Custom templates can use the Tailwind classes compiled into `hxadmin.css`. For anything else, add your own stylesheet in `{% block head %}`.

## Theme

The top bar toggles light, dark and system themes; the choice is stored in `localStorage` under `hxadmin-theme`. Templates use semantic colour tokens (`bg-surface`, `bg-surface-2`, `bg-surface-3`, `text-fg`, `text-fg-muted`, `border-edge`, `text-accent`, `bg-accent`, `text-danger`, ...) defined once for light and once for dark.
