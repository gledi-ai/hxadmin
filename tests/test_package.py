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
    "static/vendor/lucide.json",
    "static/vendor/lucide.LICENSE",
]


@pytest.mark.parametrize("path", PACKAGE_DATA)
def test_package_data_is_shipped(path: str) -> None:
    assert files("hxadmin").joinpath(path).is_file()


def test_icons_ship_as_one_bundle_not_one_file_each() -> None:
    assert not files("hxadmin").joinpath("static/vendor/lucide").is_dir()
