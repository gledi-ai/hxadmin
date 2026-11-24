import csv
import io
from base64 import b64decode
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request

from hxadmin.fields import Field
from hxadmin.forms import FormErrors, csv_column_raw, validate

if TYPE_CHECKING:
    from hxadmin.views import ModelView

MAX_ROWS = 500
MAX_BYTES = 1024 * 1024
MAX_ENCODED_BYTES = 4 * ((MAX_BYTES + 2) // 3)
SIZE_ERROR = "Choose a CSV file that is 1 MiB or smaller."


class CsvImportError(ValueError):
    pass


@dataclass(slots=True)
class CsvRow:
    line: int
    cells: list[str]
    values: dict[str, Any]
    errors: FormErrors


def template_bytes(columns: Sequence[str]) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerow(columns)
    return buffer.getvalue().encode("utf-8-sig")


async def import_payload(request: Request, *, confirm: bool) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "multipart/form-data":
        raise CsvImportError("Choose a CSV file to import.")

    limit = (MAX_ENCODED_BYTES if confirm else MAX_BYTES) + 4096

    async def bounded_stream() -> AsyncGenerator[bytes]:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise CsvImportError(SIZE_ERROR)
            yield chunk

    parser = MultiPartParser(
        request.headers,
        bounded_stream(),
        max_files=0 if confirm else 1,
        max_fields=1 if confirm else 0,
        max_part_size=MAX_ENCODED_BYTES,
    )
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        raise CsvImportError("The upload could not be read.") from exc
    try:
        payload = form.get("csv")
        if confirm and isinstance(payload, str):
            try:
                data = b64decode(payload, validate=True)
            except ValueError as exc:
                raise CsvImportError("Upload the file again to preview it.") from exc
        elif not confirm and isinstance(payload, UploadFile):
            data = await payload.read(MAX_BYTES + 1)
        else:
            raise CsvImportError("Choose a CSV file to import.")
    finally:
        await form.close()

    if len(data) > MAX_BYTES:
        raise CsvImportError(SIZE_ERROR)
    return data


def _validate_row(
    view: "ModelView[Any]", columns: list[str], cells: list[str], line: int
) -> CsvRow:
    if len(cells) != len(columns):
        return CsvRow(line, cells, {}, FormErrors(form=f"Expected {len(columns)} columns."))
    raw: dict[str, Any] = {}
    by_name = dict(zip(columns, cells, strict=True))
    for field in view.import_fields:
        if field.name not in by_name:
            continue
        cell = by_name[field.name]
        if isinstance(field, Field):
            csv_column_raw(field, cell, raw)
        elif cell:
            raw[field.name] = cell
    values, errors = validate(view.create_schema, raw)
    return CsvRow(line, cells, values, errors)


def parse_import(view: "ModelView[Any]", data: bytes) -> tuple[list[str], list[CsvRow]]:
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvImportError("Save the CSV file as UTF-8 and upload it again.") from exc
    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    try:
        columns = next(reader, [])
        if not columns:
            raise CsvImportError("The CSV file needs a header row.")
        if len(set(columns)) != len(columns):
            raise CsvImportError("The header contains duplicate columns.")
        if set(columns).difference(view.import_columns):
            raise CsvImportError(
                "The header contains unknown columns. Use the template's field names."
            )
        required = [
            name
            for name, info in view.create_schema.model_fields.items()
            if info.is_required() and name not in columns
        ]
        if required:
            raise CsvImportError(f"Missing required columns: {', '.join(required)}.")

        rows: list[CsvRow] = []
        while True:
            line = reader.line_num + 1
            cells = next(reader, None)
            if cells is None:
                break
            if not cells:
                continue
            if len(rows) >= MAX_ROWS:
                raise CsvImportError(f"Import up to {MAX_ROWS} records at a time.")
            rows.append(_validate_row(view, columns, cells, line))
    except csv.Error as exc:
        raise CsvImportError(f"The CSV could not be read near line {reader.line_num}.") from exc
    if not rows:
        raise CsvImportError("Add at least one record below the header.")
    return columns, rows
