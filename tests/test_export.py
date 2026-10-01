import datetime
import decimal
import io
import math
import uuid
import zipfile
from typing import Any
from xml.etree import ElementTree

import pytest
from fastapi import FastAPI
from sqlalchemy import JSON, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hxadmin import HxAdmin, ModelView
from hxadmin.export import cell_value, check_export_formats, csv_bytes, sheet_name, xlsx_bytes
from tests.conftest import AppFactory, Post, PostStatus, Tag, User, allow_all

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

type Cell = tuple[str | None, str, bool, bool]


def read_sheet(data: bytes) -> tuple[str, dict[str, Cell], str]:
    """Sheet name, cells by reference as (type, value, styled, formula), and raw sheet XML."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        strings = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        raw = archive.read("xl/worksheets/sheet1.xml").decode()
    shared = [item.findtext(f"{_NS}t", default="") for item in strings.iter(f"{_NS}si")]
    cells: dict[str, Cell] = {}
    for cell in ElementTree.fromstring(raw).iter(f"{_NS}c"):
        kind = cell.get("t")
        value = cell.findtext(f"{_NS}v", default="")
        text = shared[int(value)] if kind == "s" else value
        formula = cell.find(f"{_NS}f") is not None
        cells[cell.get("r", "")] = (kind, text, cell.get("s") is not None, formula)
    sheet = next(workbook.iter(f"{_NS}sheet"))
    return sheet.get("name", ""), cells, raw


class DocBase(DeclarativeBase):
    pass


class Doc(DocBase):
    __tablename__ = "docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    uid: Mapped[uuid.UUID]
    price: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2))
    at: Mapped[datetime.time]
    ok: Mapped[bool]
    note: Mapped[str | None]


def admin() -> HxAdmin:
    return HxAdmin(FastAPI(), session=AppFactory().get_session, auth=allow_all)


def test_known_formats_pass_and_unknown_fail() -> None:
    check_export_formats("V", ("csv", "xlsx"))
    with pytest.raises(ValueError, match="V: unknown export format 'pdf'"):
        check_export_formats("V", ("pdf",))


def test_xlsx_without_xlsxwriter_fails_at_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hxadmin.export.find_spec", lambda name: None)

    class XlsxUsers(ModelView[User]):
        model = User
        export_formats = ("xlsx",)

    class CsvUsers(ModelView[User]):
        model = User
        export_formats = ("csv",)

    with pytest.raises(ImportError, match=r"pip install 'hxadmin\[xlsx\]'"):
        admin().register(XlsxUsers)
    admin().register(CsvUsers)


def test_export_columns_default_to_list_columns() -> None:
    class Posts(ModelView[Post]):
        model = Post
        list_columns = ("title", "author")

    class Picked(Posts):
        export_columns = ("title", "tags")

    class Broken(Posts):
        export_columns = ("nope",)

    assert [f.name for f in Posts().export_fields] == ["title", "author"]
    assert [f.name for f in Picked().export_fields] == ["title", "tags"]
    with pytest.raises(ValueError, match="unknown field 'nope'"):
        Broken()


def test_cell_values_are_typed_or_formatted() -> None:
    hx = admin()

    @hx.register
    class PostView(ModelView[Post]):
        model = Post
        export_columns = ("title", "status", "score", "published_at", "author", "tags")

        def format_score(self, obj: Post) -> str:
            return f"{obj.score:.1f} pts"

    view = hx.views["post"]
    when = datetime.datetime.fromisoformat("2026-01-02T03:04:05")
    post = Post(
        title="Hello",
        status=PostStatus.published,
        score=2.0,
        published_at=when,
        author=User(email="ada@x.io"),
        tags=[Tag(name="a"), Tag(name="b")],
    )
    values = [cell_value(hx, view, f, post) for f in view.export_fields]
    assert values == ["Hello", "published", "2.0 pts", when, "ada@x.io", 2]


def test_cell_values_for_json_uuid_decimal_time_bool_and_none() -> None:
    hx = admin()

    @hx.register
    class DocView(ModelView[Doc]):
        model = Doc

    view = hx.views["doc"]
    doc = Doc(
        id=1,
        data={"é": [1]},
        uid=uuid.UUID(int=1),
        price=decimal.Decimal("1.50"),
        at=datetime.time(9, 30),
        ok=False,
        note=None,
    )
    assert [cell_value(hx, view, f, doc) for f in view.export_fields] == [
        1,
        '{"é": [1]}',
        "00000000-0000-0000-0000-000000000001",
        decimal.Decimal("1.50"),
        datetime.time(9, 30),
        False,
        None,
    ]


def test_csv_neutralises_formulas_and_writes_plain_text() -> None:
    data = csv_bytes(
        ["Name", "Value"],
        [
            ["=SUM(A1)", -3],
            ["+x", None],
            ["a,b", True],
            ["-1", datetime.date(2026, 1, 2)],
            ["@x\tb", decimal.Decimal("1.50")],
        ],
    )
    assert data.startswith(b"\xef\xbb\xbf")
    assert data.decode("utf-8-sig") == (
        "Name,Value\r\n'=SUM(A1),-3\r\n'+x,\r\n\"a,b\",true\r\n'-1,2026-01-02\r\n'@x\tb,1.50\r\n"
    )


def test_sheet_names_are_made_valid() -> None:
    assert sheet_name("Posts: all/*") == "Posts  all"
    assert sheet_name("x" * 40) == "x" * 31
    assert sheet_name("///") == "Sheet1"


def test_xlsx_writes_native_cell_types() -> None:
    aware = datetime.datetime(
        2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
    )
    headers = ["Title", "Done", "N", "Day", "At", "Price", "Empty"]
    row = ["=1+1", True, 3, datetime.date(2026, 1, 2), aware, decimal.Decimal("1.5"), None]
    name, cells, raw = read_sheet(xlsx_bytes("Posts", headers, [row]))
    assert name == "Posts"
    assert cells["A1"] == ("s", "Title", True, False)
    assert cells["A2"] == ("s", "=1+1", False, False)
    assert cells["B2"] == ("b", "1", False, False)
    assert cells["C2"] == (None, "3", False, False)
    assert cells["D2"] == (None, "46024", True, False)
    kind, value, styled, _ = cells["E2"]
    assert (kind, styled) == (None, True)
    assert float(value) == pytest.approx(46024 + (1 * 3600 + 4 * 60 + 5) / 86400)
    assert cells["F2"] == (None, "1.5", False, False)
    assert "G2" not in cells
    assert '<autoFilter ref="A1:G2"/>' in raw
    assert 'ySplit="1"' in raw


def test_xlsx_writes_non_finite_numbers_as_errors() -> None:
    row = [math.nan, math.inf, -math.inf, decimal.Decimal("NaN")]
    _, cells, _ = read_sheet(xlsx_bytes("Data", ["A", "B", "C", "D"], [row]))
    assert cells["A2"] == ("e", "#NUM!", False, True)
    assert cells["B2"] == ("e", "#DIV/0!", False, True)
    assert cells["C2"] == ("e", "#DIV/0!", False, True)
    assert cells["D2"] == ("e", "#NUM!", False, True)
