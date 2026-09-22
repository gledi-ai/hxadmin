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
    "static/vendor/alpine-anchor.min.js",
    "static/vendor/alpine-focus.min.js",
    "static/vendor/alpine-plugins.LICENSE",
    "static/vendor/lucide/LICENSE",
    "static/vendor/lucide/house.svg",
]


@pytest.mark.parametrize("path", PACKAGE_DATA)
def test_package_data_is_shipped(path: str) -> None:
    assert files("hxadmin").joinpath(path).is_file()
