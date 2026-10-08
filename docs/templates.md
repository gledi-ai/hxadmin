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
| `_macros.html` | Component re-exports, cells, row menu, filter popovers, bulk bar |
| `_palette.html` | Command palette results |

Custom templates can use the Tailwind classes compiled into `hxadmin.css`. For anything else, add your own stylesheet in `{% block head %}`.

`components/<name>.html` (`button.html`, `badge.html`, `card.html`, `menu.html`, `dialog.html`, `feedback.html`, `misc.html`, `date.html`, `icon.html`) each override independently, the same way: a file of that name in `templates_dir` replaces just that component everywhere, because the loader tries your directory first.

## Components

`templates/components/*.html` hold one Jinja macro per shared UI piece. `_macros.html` re-exports all of them, so `{% import "_macros.html" as m with context %}` gives you `m.button(...)`, `m.card(...)` and the rest in your own templates — including custom page bodies (see [Custom pages](pages.md)).

| Macro | Renders |
|---|---|
| `button`, `icon_button` | Buttons, with `variant` (`primary`, `secondary`, `ghost`, `danger`) and `size` |
| `badge` | A small pill for an enum or bool value, with a `tone` |
| `card` | A bordered surface, optionally a link (`href`) or with a header (`title`) |
| `popover`, `menu`, `menu_item`, `menu_separator`, `menu_label` | Keyboard-navigable overlays anchored to a trigger, and the pieces of a menu |
| `dialog`, `dialog_footer` | A modal with a focus trap, `Esc` to close and an overlay; its button row |
| `empty_state` | A centred "nothing here" placeholder, with an icon, title, text and action |
| `stat` | A card with a label and a large tabular value, for dashboards and custom pages |
| `alert` | An inline message with a tone |
| `tooltip`, `kbd` | A hover/focus tooltip; a keyboard-key badge |
| `date_input` | A themed date, datetime or time picker submitting ISO values; see [Forms](forms.md#dates-and-times) |

Each component file documents its full signature at the top. Every macro takes `class` (appended to its own classes) and, except `date_input`, `attrs` / `**kwargs` (extra HTML or Alpine attributes, `_` becoming `-`).

`_macros.html` also renders the admin-specific pieces, which need the request context: `cell(view, field, value, link=True)` formats one value the way lists and the detail page do (`link=False` renders relations as muted text instead of links), and `row_menu`, `filter_button`, `bulk_bar` and `export_menu` render the list's row menu, filter pills, floating selection bar and export menu.

To open the shared confirm dialog from your own markup, dispatch a `confirm` event with a `message` and either a `submit` callback or an `action` URL; `title` and `danger: true` (a red Confirm button) are optional. With `action`, Confirm submits a plain form POST to that URL, which suits any POST route of the admin: a row action, a delete, or a [custom page](pages.md#pages-that-write) route. For example, a button running the `raise_priority` row action of a `TaskView` on task 3:

```jinja
{% set url = admin.url(request, '/task/3/action/raise_priority') %}
<button type="button" @click="$dispatch('confirm', {title: 'Raise priority?', message: 'Task 3 moves up one level.', action: {{ url|tojson|forceescape }}})">Raise priority</button>
```

Row actions live at `/{identity}/{pk}/action/{name}` and bulk actions at `/{identity}/action/{name}` (with the rows as repeated `pks` form values), deletes at `/{identity}/{pk}/delete`. A plain POST to them redirects back with a toast, like a form without htmx. `tojson|forceescape` keeps the URL a valid JavaScript string inside the attribute.

## Icons

`{{ icon("name", class="size-4") }}` inlines a vendored [Lucide](https://lucide.dev) SVG, read once from disk and cached, with `stroke="currentColor"` and `aria-hidden="true"`. Names are Lucide's kebab-case names (`list-checks`, `chart-column`, ...); an unknown name raises `ValueError`. The same validation applies to `icon` on views, pages and `@admin.page(icon=...)`. `icon` is also available as `m.icon(...)` through `_macros.html`. The Lucide licence ships alongside the vendored icons.

## Tokens

Templates use only semantic tokens; raw palette colours (`gray-500`, `blue-600`, ...) exist solely inside `@theme` in `static/src/hxadmin.css`.

| Group | Tokens |
|---|---|
| Surfaces | `bg`, `surface` (cards), `surface-2` (muted / hover), `popover`, `overlay` |
| Text | `fg`, `fg-muted`, `fg-subtle` |
| Lines | `border`, `input`, `ring` |
| Accent | `accent`, `accent-fg`, `accent-soft` |
| Status | `success`, `warning`, `danger`, each with a `-soft` tint and a `-fg` |
| Radius | `radius-sm` / `radius-md` / `radius-lg` |
| Shadows | `shadow-sm` (cards), `shadow-md` (popovers), `shadow-lg` (dialogs, floating bar) |

Each token is defined once in `@theme` and overridden under `.dark`, so a template never branches on theme itself.

## Shell

The sidebar groups views and pages by `category`. It collapses to an icon rail with its toggle button or `⌘B` / `Ctrl+B`; the state is stored in `localStorage` under `hxadmin-sidebar` and applied before paint. Below the `lg` breakpoint it becomes a drawer. The brand block shows `logo_url` when set (see [Branding](getting-started.md#branding)), else the title's first letter in an accent tile.

The top bar holds the breadcrumbs (the parent pages only, since the page title names the current one), the command palette button (a search icon on small screens) and the user menu (theme choice, and Log out when `logout_url` is set).

## Command palette

`⌘K` / `Ctrl+K`, or the search button in the top bar, opens the command palette. It lists every sidebar entry under "Go to", filtered by label as you type, and, once there is a query, up to five matching rows from each of the first eight visible views with `searchable` columns, linking to their detail page (or to the filtered list when `can_view` is off). Arrows move, Enter opens, Esc closes. Results come from `/{prefix}/_palette?q=…` and render with `_palette.html`.

## Theme

The top bar toggles light, dark and system themes; the choice is stored in `localStorage` under `hxadmin-theme` and applied before paint, so there is no flash.
