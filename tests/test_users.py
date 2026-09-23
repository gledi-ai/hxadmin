import pytest

from hxadmin.users import user_initials, user_label


class _Obj:
    def __init__(self, **attrs: object) -> None:
        self.__dict__.update(attrs)

    def __str__(self) -> str:
        return "obj"


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        (None, ""),
        (True, ""),
        (False, ""),
        ({"name": "Ada"}, "Ada"),
        ({"id": 1}, "{'id': 1}"),
        (_Obj(name="Grace"), "Grace"),
        (_Obj(name=None), "obj"),
        (_Obj(name=""), "obj"),
        (_Obj(email="x@y.z"), "obj"),
        (42, "42"),
        ("dev", "dev"),
    ],
)
def test_user_label(user: object, expected: str) -> None:
    assert user_label(user) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("", ""),
        ("Grace Hopper", "GH"),
        ("Grace Brewster Hopper", "GB"),
        ("admin@example.com", "A"),
        ("john.doe@example.com", "JD"),
        ("42", "4"),
        ("{'id': 1}", "I1"),
    ],
)
def test_user_initials(label: str, expected: str) -> None:
    assert user_initials(label) == expected
