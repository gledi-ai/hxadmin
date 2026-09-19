from importlib.resources import files

import pytest

PACKAGE_DATA = ["py.typed"]


@pytest.mark.parametrize("path", PACKAGE_DATA)
def test_package_data_is_shipped(path: str) -> None:
    assert files("hxadmin").joinpath(path).is_file()
