# Auth and sessions

```python
admin = HxAdmin(
    app,
    session=get_session,  # dependency yielding an AsyncSession
    auth=current_admin_user,  # dependency returning the user, or raising HTTPException
    prefix="/admin",
    login_url="/login",  # optional
    logout_url="/logout",  # optional; shown in the top bar
)
```

## Sessions

`session` is any FastAPI dependency that yields or returns an `AsyncSession`. hxadmin uses one session per request, commits after a successful save, delete or action, and rolls back on errors. hxadmin re-queries after commits, so `expire_on_commit=True` sessionmakers work.

## Auth

`auth` runs on every admin request. Its return value is available as `request.state.hxadmin_user` and as `user` in templates. The top bar shows `user.name` when it exists, otherwise `str(user)`.

To deny access, raise `HTTPException(401)` or `HTTPException(403)`. With `login_url` set, these send the browser to the login page (303, or `HX-Redirect` for htmx requests). Without it, they render an error page.

Per view, `is_accessible(request)` and `is_visible(request)` narrow access further. Per action, `is_action_allowed(request, name)` does; see [Actions](actions.md).

## CSRF

hxadmin has no CSRF protection of its own. If the admin is authenticated by cookie, put it behind your session and CSRF middleware.
