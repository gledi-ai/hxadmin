from importlib.resources import files

import pytest

PACKAGE_DATA = [
    "py.typed",
    "templates/layout.html",
    "templates/list.html",
    "templates/list/_table.html",
    "templates/detail.html",
    "templates/detail/_panel.html",
    "templates/page.html",
    "static/hxadmin.css",
    "static/vendor/htmx.min.js",
    "static/vendor/alpine.min.js",
]


@pytest.mark.parametrize("path", PACKAGE_DATA)
def test_package_data_is_shipped(path: str) -> None:
    assert files("hxadmin").joinpath(path).is_file()
