"""Cookie-session sign-in for the demo, checked against `User.password_hash`."""

import hashlib
import hmac
import os
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from demo.db import get_session
from demo.models import User

DEMO_PASSWORD = "demo"  # noqa: S105


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, _, digest = stored.partition("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest)


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None:
        return None
    return user if verify_password(password, user.password_hash) else None


async def current_user(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> User:
    user_id = request.session.get("user_id")
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(401)
    return user
