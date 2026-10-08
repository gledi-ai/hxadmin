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

`session` is any FastAPI dependency that yields or returns an `AsyncSession`, such as `get_session` in [Getting started](getting-started.md#a-minimal-admin). hxadmin uses one session per request, commits after a successful save, delete or action, and rolls back on errors. hxadmin re-queries after commits, so `expire_on_commit=True` sessionmakers work.

FastAPI resolves a dependency once per request, so when your `auth` (or a custom page) also depends on `get_session`, it gets the very same session hxadmin uses. Rows your `auth` loads can then be used in `on_save` and actions like any other row of the request; after its own commits and rollbacks, hxadmin reloads the user `auth` returned when it is such a row, so hooks can keep reading it. A custom page handler gets the same session too, but hxadmin does not commit for it; see [Custom pages](pages.md#pages-that-write).

## Auth

`auth` runs on every admin request. Its return value is available as `request.state.hxadmin_user` and as `user` in templates. The top bar's user menu shows `user.name` (an attribute or a mapping key) when it is set, otherwise `str(user)`, with initials derived from it. Any return value works: `None` or a bool (an `auth` that only answers "allowed") shows a generic avatar with no name.

To deny access, raise `HTTPException(401)` or `HTTPException(403)`. With `login_url` set, these send the browser to the login page (303, or `HX-Redirect` for htmx requests). Without it, they render an error page, keeping the exception's headers.

### Example: HTTP Basic against the users table

A complete `auth` for the [docs models](getting-started.md#the-models-in-these-docs) that needs nothing beyond FastAPI and the standard library. The browser asks for an e-mail and password, which are checked against `User.password_hash`. It returns the signed-in `User` row, which the other pages' examples rely on.

```python
# myapp/auth.py
import hashlib
import hmac
import os
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myapp.db import get_session
from myapp.models import User

basic = HTTPBasic(realm="Admin")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, _, digest = stored.partition("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest)


async def current_admin_user(
    credentials: Annotated[HTTPBasicCredentials, Depends(basic)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    user = await session.scalar(select(User).where(User.email == credentials.username))
    if (
        user is None
        or not user.active
        or user.password_hash is None
        or not verify_password(credentials.password, user.password_hash)
    ):
        raise HTTPException(401, "Wrong e-mail or password.", headers={"WWW-Authenticate": "Basic"})
    return user
```

```python
admin = HxAdmin(app, session=get_session, auth=current_admin_user)
```

Create the first account from a script or a shell, since the admin cannot be opened without one:

```python
async with sessionmaker() as session:
    session.add(
        User(
            name="Ada",
            email="ada@example.com",
            password_hash=hash_password("..."),
            is_superuser=True,
        )
    )
    await session.commit()
```

Notes on this example:

- The `User` row depends on `get_session`, so it belongs to the request's session (see [Sessions](#sessions)). A custom page that commits and then renders with an `expire_on_commit=True` sessionmaker must `await session.refresh(user)` itself, since hxadmin does not handle custom pages' commits.
- Every active user with a password can open the admin; `is_superuser` only matters where your views check it (see [Views](views.md#hooks) and [Actions](actions.md#permissions)). If the users table also holds customers, add an `is_staff` column and check it here.
- The `WWW-Authenticate` header makes the browser show its login prompt again after a wrong password. Do not set `login_url` with HTTP Basic: hxadmin would redirect instead of letting the browser prompt.
- Browsers keep Basic credentials until they quit, so there is no real log out; leave `logout_url` unset.
- Basic sends the password with every request: serve the admin over HTTPS only.

### Example: your app's own login

When your application already signs users in with a cookie session, `auth` reads that session and hxadmin sends signed-out visitors to your login page. With Starlette's `SessionMiddleware` (it needs `itsdangerous`):

```python
import os
from typing import Annotated

from fastapi import Depends, HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"], https_only=True)


async def current_admin_user(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> User:
    user_id = request.session.get("user_id")
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None or not user.active:
        raise HTTPException(401)
    return user


admin = HxAdmin(
    app, session=get_session, auth=current_admin_user, login_url="/login", logout_url="/logout"
)
```

The admin is mounted inside `app`, so middleware added to `app` runs for admin requests too and `request.session` works there. `/login` and `/logout` are your application's routes, outside the admin: `/login` checks the password (`verify_password` above will do) and sets `request.session["user_id"]`, and `/logout` clears it. The Log out entry in the user menu is a plain link, so `/logout` must answer `GET`.

Per view, `is_accessible(request)` and `is_visible(request)` narrow access further. Per action, `is_action_allowed(request, name)` does; see [Actions](actions.md#permissions).

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
