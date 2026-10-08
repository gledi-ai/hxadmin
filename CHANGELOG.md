# Changelog

All notable changes to this project are documented in this file.

## [0.1.1] - 2026-10-08

### Bug fixes

- Keep the auth user loaded after rollbacks and action refreshes

### Documentation

- Make examples complete and runnable

## [0.1.0] - 2026-10-08

### Features

- Add ModelView base and test scaffolding
- Mount HxAdmin sub-app with dashboard and layout
- Redirect unauthenticated admin requests to login_url
- Build sidebar navigation from registered views
- Vendor htmx, alpine and compiled tailwind assets
- Add demo todo app for manual testing
- Derive Field and RelationField from SQLAlchemy mappers
- Resolve list, detail, sort and pk config on ModelView
- Add list query params, search, sort, pagination and fetch_one
- Add searchable, sortable, paginated model list page
- Add model detail page with lazy related-collection tabs
- Carry default, unique, autoincrement, choices and widget on fields
- Resolve form fields and build pydantic schemas per view
- Parse, validate and apply form values; narrow fetch_one eager loads
- Add create, edit and delete with inline validation errors
- Add relation combobox backed by _lookup search
- Add toasts via HX-Trigger and a one-shot flash cookie
- Declare row and bulk actions with @action on ModelView
- Add row and bulk action endpoints with toast responses
- Render row actions, bulk selection bar and htmx confirm modal
- Add admin.page and admin.route custom pages in the admin shell
- Show row counts on the dashboard and add top-bar global search
- Declare list filters and apply them from f.* query params
- Add the list filter panel and removable filter chips
- Write CSV and XLSX exports with typed cells behind the xlsx extra
- Export the list as shown or the selection from the list page
- Toast after create, edit and delete; let on_save raise FormError
- Gate actions with is_action_allowed; show row controls without hover
- Semantic design tokens and inline Lucide icons
- Component macro library with popover, menu and dialog behaviour
- Command palette route and results partial
- Redesigned shell with collapsible rail sidebar and user menu
- Dashboard cards, empty-state error page and stat-based demo stats
- Merge the dashboard, error page and docs redesign
- Redesign list filters as per-field popovers with OOB summaries
- Add ModelView.badges for tone-mapped enum/bool cells
- Float the bulk-selection bar over the list and share its Alpine scope
- Redesign list table with a row-action menu and mobile card view
- Redesign detail page header with actions menu and badges
- Redesign form layout, confirm dialog and toasts
- Add a themed date/datetime/time picker component
- Merge the detail, form, dialog, toast and date picker redesign
- Support plain Core tables mapped with __table__
- Add a demo built only on plain Core tables
- Refuse cross-origin writes from browsers

### Bug fixes

- Resolve admin links from request root_path, not mount prefix
- Install tailwindcss before compiling in nox css session
- Enforce can_view on related rows and keep list state across swaps
- Scope relation lookups on save through the target view and harden forms
- Roll back half-applied edits on unknown selection; keep identifying relations read-only on edit
- Honour model defaults on create, require non-nullable values on edit, roll back failed hooks
- Toast HTTP errors on htmx requests and redirect to login only for auth failures
- Serialise JSON-able page results, allow split-method page routes, reject duplicate pages
- Send Allow on action 405s and keep HTTPException headers in error responses
- Keep a handler's own page context key; expose the registration as admin_page
- Truncate long flash messages so the cookie is not dropped
- Return native list actions to the list with its search, sort and page
- Count dashboard rows in one query and isolate views whose counts fail
- Re-render the detail heading and buttons with the panel after an action
- Drop filter and pk values outside the 64-bit integer range
- Read only visible filters, and none on the related tab
- Reject reverse one-to-one relations as list filters
- Write NaN and infinite numbers as Excel errors in XLSX exports
- Keep range bounds and pks that Postgres would reject out of the query
- Keep range bounds in the form their inputs write
- Compute toast labels where lazy loads work
- Return to the list as shown after delete and detail-less save
- Show the active filter count on the Filters toggle
- Move sidebar toggle to icon button and restore full breadcrumbs
- Force the date picker's built-in locale to English
- Disable htmx settle so swapped popovers keep their Alpine state
- Render list relation cells as muted text and link only the primary column
- Use the themed date picker in date, datetime and time range filters
- Load the date picker stylesheet before the theme so its overrides apply
- Size list columns to content so the primary column takes the remaining width
- Show the list row count and stop repeating the page title in breadcrumbs
- Align the list toolbar on one 32px row and scroll filters on mobile
- Inset icon-less action items so menu labels line up
- Make the select-all checkbox select every row and show its indeterminate state
- Highlight selected list rows and cards
- Make form inputs 36px high and align the sticky footer with the form
- Listen for htmx 4 event names so the palette, bulk bar and date picker react to swaps
- Load palette results when it opens and anchor it near the top
- Give the error page a clear heading, explanation and way back
- Drop the date picker's white pointer arrow and tighten its offset
- Reach the palette on mobile and hide the filter row's scrollbar
- Stack the detail header on mobile so the title is not truncated
- Give form selects the same chevron and padding as the comboboxes
- Close the mobile drawer with an X instead of the desktop rail toggle
- Keep list pagination on one row on mobile
- Render the user menu for any auth return value
- Keep the theme menu when auth returns no user
- Stop palette typing from re-querying the list behind it
- Clear only the chosen filter, not filters sharing its prefix
- Reset the toolbar form from the empty state's Reset filters
- Submit typed dates and stop date-only values shifting a day
- Stop nesting a neutral badge round the detail header badges
- Give the mobile card row menus their own ids
- Show closed nav groups' items in the rail and hide them pre-paint
- Set the palette's aria-activedescendant when results load
- Reject badges values a column cannot hold
- Remove the phase 5 macros and helpers nothing uses
- Leave inaccessible views out of the sidebar and palette
- Quote the date input's x-data like every other JSON attribute
- Announce error toasts as alerts, link related tabs, show Ctrl off Mac
- Drop empty params from toolbar requests and pushed URLs
- Draw checkboxes and radios with the theme tokens
- Keep the table header visible while the rows scroll
- Match the spec's page title size, pager label and form alignment
- Lay the detail body out as a two-column description list
- Put short form fields two to a row
- Stop heading a single dashboard card with its category
- Keep the rail's brand row aligned with the 56px top bar
- Tidy the mobile list toolbar, selection and bulk bar
- Open filter calendars beside their popover, not over it
- Show the pointer cursor on buttons, links and menu items
- Write the palette shortcut as Ctrl+K like Ctrl+B
- Disable autoflush inside forms.apply
- Harden list ordering, lookups, form bounds and database error handling

### Refactoring

- Make ModelView and register generic, inherit view naming
- Move primary-key helpers to a leaf module; add demo __str__
- One relation scope resolver, built once per relation filter
- Group one-model dashboard categories in Python
- Resolve form widgets and widths in Python
- Keep the date input formats in one map
- Render both select-all boxes from one macro
- Split the list reset into two named helpers

### Documentation

- Add HxAdmin usage to README
- Configure demo views and document list/detail options
- Configure demo forms and document form options
- Add Task.priority to the demo to exercise defaulted non-nullable columns
- Demo actions and custom pages; document them in the README
- GET actions must be read-only
- Add user docs built with Zensical and slim the README
- Demo filters, built-in export and FormError
- Relation option order, bound normalisation and Excel limits
- Describe the redesigned list, detail, forms, shell and components
- Mention the list row count, row highlight and breadcrumb rule
- Describe the list selection and mobile toolbar as shipped
- Turn the besidePanel comment into JSDoc

<!-- generated by git-cliff -->
