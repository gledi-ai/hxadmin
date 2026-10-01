from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

type SessionDependency = (
    Callable[..., AsyncSession]
    | Callable[..., AsyncIterator[AsyncSession]]
    | Callable[..., Awaitable[AsyncSession]]
)
type AuthDependency = Callable[..., Any]
