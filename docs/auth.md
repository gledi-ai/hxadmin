# Auth and sessions

```python
admin = HxAdmin(
    app,
    session=get_session,  # dependency yielding an AsyncSession
    auth=current_admin_user,  # dependency returning the user, or raising HTTPException
    prefix="/admin",
    login_url="/login",  # optional
    logout_url="/logout",  # optional; shown in the top bar
    trusted_origins=(),  # optional; other origins allowed to send writes
)
```

## Sessions

`session` is any FastAPI dependency that yields or returns an `AsyncSession`. hxadmin uses one session per request, commits after a successful save, delete or action, and rolls back on errors. hxadmin re-queries after commits, so `expire_on_commit=True` sessionmakers work.

## Auth

`auth` runs on every admin request. Its return value is available as `request.state.hxadmin_user` and as `user` in templates. The top bar's user menu shows `user.name` (an attribute or a mapping key) when it is set, otherwise `str(user)`, with initials derived from it. Any return value works: `None` or a bool (an `auth` that only answers "allowed") shows a generic avatar with no name.

To deny access, raise `HTTPException(401)` or `HTTPException(403)`. With `login_url` set, these send the browser to the login page (303, or `HX-Redirect` for htmx requests). Without it, they render an error page.

Per view, `is_accessible(request)` and `is_visible(request)` narrow access further. Per action, `is_action_allowed(request, name)` does; see [Actions](actions.md).

## Cross-site requests

hxadmin refuses state-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) that a browser sends from another origin, so another site cannot make a signed-in admin's browser create, edit, delete or run an action. This covers every admin route, custom pages included, whatever your `auth` uses (cookies included), and needs no tokens in your templates.

- Browsers send `Sec-Fetch-Site`; a write passes when it is `same-origin` (or `none`, a request the user started directly). `same-site` is refused too, so a sibling subdomain cannot write.
- Browsers too old for `Sec-Fetch-Site` send `Origin`, which must match the request's `Host`.
- Requests with neither header do not come from a browser (scripts, tests, server-to-server calls) and pass; `auth` still applies.
- `GET`, `HEAD` and `OPTIONS` always pass, which is why `method="GET"` actions must not change data (see [Actions](actions.md)).

A refused request gets a 403 ("Cross-origin request blocked.": an error page, or an error toast for htmx) and a warning on the `hxadmin` logger naming the method, path, `Origin` and `Sec-Fetch-Site`.

To accept writes from another origin you control, such as a separate frontend, list it:

```python
admin = HxAdmin(app, ..., trusted_origins=["https://ops.example.com"])
```

Each entry is a bare origin, `scheme://host[:port]`, with no path; anything else raises `ValueError`.

Behind a reverse proxy, browsers that only send `Origin` need the proxy to pass the public `Host` header through (e.g. nginx `proxy_set_header Host $host;`). Current browsers send `Sec-Fetch-Site`, which does not depend on the proxy.
