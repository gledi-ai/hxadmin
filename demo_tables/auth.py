"""Cookie-session sign-in for the demo, against one fixed account (there is no users table)."""

import hmac

from fastapi import HTTPException, status
from starlette.requests import Request

DEMO_EMAIL = "admin@example.com"
DEMO_PASSWORD = "demo"  # noqa: S105
DEMO_USER = {"name": "Admin", "email": DEMO_EMAIL}


def authenticate(email: str, password: str) -> bool:
    email_ok = hmac.compare_digest(email.encode(), DEMO_EMAIL.encode())
    password_ok = hmac.compare_digest(password.encode(), DEMO_PASSWORD.encode())
    return email_ok and password_ok


def current_user(request: Request) -> dict[str, str]:
    if request.session.get("user") != DEMO_EMAIL:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return DEMO_USER
