from typing import Any, ClassVar

from starlette.requests import Request


class ModelView[T]:
    """Configuration for one SQLAlchemy model in the admin."""

    model: type[T]
    name: ClassVar[str]
    name_plural: ClassVar[str]
    identity: ClassVar[str]
    category: ClassVar[str | None] = None
    icon: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "model" not in cls.__dict__ and not hasattr(cls, "model"):
            raise TypeError(f"{cls.__name__} must define `model`")
        if "model" in cls.__dict__:
            model_name: str = cls.model.__name__
            cls.name = cls.__dict__.get("name", model_name)
            cls.name_plural = cls.__dict__.get("name_plural", f"{cls.name}s")
            cls.identity = cls.__dict__.get("identity", model_name.lower())
        else:
            cls.name = cls.__dict__.get("name", cls.name)
            cls.name_plural = cls.__dict__.get("name_plural", cls.name_plural)
            cls.identity = cls.__dict__.get("identity", cls.identity)

    def is_visible(self, request: Request) -> bool:
        return True

    def is_accessible(self, request: Request) -> bool:
        return True
