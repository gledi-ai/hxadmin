import csv
import datetime
import decimal
import enum
import io
import json
import re
from collections.abc import Sequence
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import anyio.to_thread
from starlette.responses import Response

from hxadmin.fields import Field, RelationField

if TYPE_CHECKING:
    from hxadmin.admin import HxAdmin
    from hxadmin.views import ModelView

type ExportFormat = Literal["csv", "xlsx"]

EXPORT_FORMATS: tuple[ExportFormat, ...] = ("csv", "xlsx")
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_SHEET_NAME_INVALID = re.compile(r"[\[\]:*?/\\]")

type Temporal = datetime.datetime | datetime.date | datetime.time


def check_export_formats(owner: str, formats: Sequence[str]) -> None:
    """Reject unknown formats, and `xlsx` without XlsxWriter, at registration."""
    for fmt in formats:
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"{owner}: unknown export format {fmt!r}")
    if "xlsx" in formats and find_spec("xlsxwriter") is None:
        raise ImportError(
            f"{owner}: export format 'xlsx' needs XlsxWriter: pip install 'hxadmin[xlsx]'"
        )


def cell_value(
    admin: "HxAdmin", view: "ModelView[Any]", field: Field | RelationField, obj: Any
) -> Any:
    """The plain value exported for `field` of `obj`: `format_<name>` output or a typed value."""
    value = view.cell(obj, field.name)
    if field.name in view.formatted or value is None:
        return value
    if isinstance(field, RelationField):
        return len(value) if field.multiple else admin.display(value)
    if field.kind == "json":
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, bool | int | float | decimal.Decimal | datetime.date | datetime.time):
        return value
    return str(value)


def _csv_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime.date | datetime.time):
        return value.isoformat()
    text = str(value)
    if isinstance(value, str) and text.startswith(_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def csv_bytes(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> bytes:
    """UTF-8 (with BOM) CSV of `headers` and `rows`, formula-looking strings neutralised."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([_csv_text(h) for h in headers])
    writer.writerows([_csv_text(v) for v in row] for row in rows)
    return ("﻿" + buffer.getvalue()).encode()


class _Format(Protocol):
    pass


class _Worksheet(Protocol):
    def write_string(
        self, row: int, col: int, string: str, cell_format: _Format | None = None, /
    ) -> int: ...
    def write_number(
        self, row: int, col: int, number: float, cell_format: _Format | None = None, /
    ) -> int: ...
    def write_boolean(
        self, row: int, col: int, boolean: bool, cell_format: _Format | None = None, /
    ) -> int: ...
    def write_datetime(
        self, row: int, col: int, date: Temporal, cell_format: _Format | None = None, /
    ) -> int: ...
    def freeze_panes(self, row: int, col: int, /) -> int: ...
    def autofilter(
        self, first_row: int, first_col: int, last_row: int, last_col: int, /
    ) -> int: ...


class _Workbook(Protocol):
    def add_worksheet(self, name: str | None = None, /) -> _Worksheet: ...
    def add_format(self, properties: dict[str, Any] | None = None, /) -> _Format: ...
    def close(self) -> None: ...


def _naive(value: Temporal) -> Temporal:
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        return value.astimezone(datetime.UTC).replace(tzinfo=None)
    if isinstance(value, datetime.time) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def sheet_name(title: str) -> str:
    """`title` made valid as an Excel sheet name (no `[]:*?/\\`, at most 31 characters)."""
    return _SHEET_NAME_INVALID.sub(" ", title).strip()[:31] or "Sheet1"


def xlsx_bytes(title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> bytes:
    """An XLSX workbook with one sheet: bold frozen header row, autofilter, typed cells."""
    from xlsxwriter import Workbook

    buffer = io.BytesIO()
    workbook = cast(_Workbook, Workbook(buffer, {"in_memory": True}))
    sheet = workbook.add_worksheet(sheet_name(title))
    bold = workbook.add_format({"bold": True})
    formats = {
        datetime.datetime: workbook.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"}),
        datetime.date: workbook.add_format({"num_format": "yyyy-mm-dd"}),
        datetime.time: workbook.add_format({"num_format": "hh:mm:ss"}),
    }
    for col, header in enumerate(headers):
        sheet.write_string(0, col, header, bold)
    for r, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            if value is None:
                continue
            if isinstance(value, bool):
                sheet.write_boolean(r, col, value)
            elif isinstance(value, int | float | decimal.Decimal):
                sheet.write_number(r, col, float(value))
            elif isinstance(value, datetime.datetime | datetime.date | datetime.time):
                sheet.write_datetime(r, col, _naive(value), formats[type(value)])
            else:
                sheet.write_string(r, col, str(value))
    sheet.freeze_panes(1, 0)
    if headers:
        sheet.autofilter(0, 0, len(rows), len(headers) - 1)
    workbook.close()
    return buffer.getvalue()


async def export_response(
    admin: "HxAdmin", view: "ModelView[Any]", fmt: str, rows: Sequence[Any]
) -> Response:
    """A download of `rows` in `fmt` (`csv` or `xlsx`) with the view's export columns."""
    fields = view.export_fields
    headers = [f.label for f in fields]
    table = [[cell_value(admin, view, f, row) for f in fields] for row in rows]
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    if fmt == "xlsx":
        body = await anyio.to_thread.run_sync(xlsx_bytes, view.name_plural, headers, table)
        media_type = XLSX_MEDIA_TYPE
    else:
        body = csv_bytes(headers, table)
        media_type = "text/csv; charset=utf-8"
    disposition = f'attachment; filename="{view.identity}-{stamp}.{fmt}"'
    return Response(body, media_type=media_type, headers={"Content-Disposition": disposition})
