import datetime
import decimal
import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Reading, allow_all

type MakeClient = Callable[[FastAPI], TestClient]

CREATE_DATA = {
    "count": "3",
    "amount": "12.50",
    "day": "2026-09-23",
    "at": "14:30",
    "taken_at": "2026-09-23T14:30",
    "synced_at": "2026-09-23T14:30",
    "ref": "12345678-1234-5678-1234-567812345678",
}


async def seed(session: AsyncSession) -> None:
    session.add(
        Reading(
            count=1,
            amount=decimal.Decimal("1.00"),
            day=datetime.date.fromisoformat("2026-01-01"),
            at=datetime.time.fromisoformat("09:00"),
            taken_at=datetime.datetime.fromisoformat("2026-01-01T09:00"),
            synced_at=datetime.datetime.fromisoformat("2026-01-01T09:00+00:00"),
            ref=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        )
    )


def build(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class ReadingView(ModelView[Reading]):
        model = Reading

    return app


def test_new_form_renders_a_date_input_per_kind(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/reading/new").text
    assert """x-data='dateInput("date", "")'""" in html
    assert """x-data='dateInput("time", "")'""" in html
    assert html.count("""x-data='dateInput("datetime", "")'""") == 2
    assert '<input type="hidden" name="day" value="" :value="value"' in html
    assert '<input type="hidden" name="at" value="" :value="value"' in html
    assert '<input type="hidden" name="taken_at" value="" :value="value"' in html
    assert '<input type="hidden" name="synced_at" value="" :value="value"' in html


def test_edit_form_prefills_the_hidden_iso_value_per_kind(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/reading/1/edit").text
    assert """x-data='dateInput("date", "2026-01-01")'""" in html
    assert """x-data='dateInput("time", "09:00:00")'""" in html
    assert """x-data='dateInput("datetime", "2026-01-01T09:00")'""" in html


def test_form_pages_include_the_vendored_picker_assets(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/reading/new").text
    assert "/static/vendor/air-datepicker.min.js" in html
    assert "/static/vendor/air-datepicker.css" in html
    assert 'Alpine.data("dateInput"' in html


def test_create_round_trips_iso_date_values(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/reading/new", data=CREATE_DATA, follow_redirects=False)
        assert response.status_code == 303
        detail = client.get(response.headers["location"]).text
    assert "2026-09-23" in detail
    assert "14:30" in detail


def test_clearing_the_date_submits_empty(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/reading/new", data={**CREATE_DATA, "day": ""}, follow_redirects=False
        )
    assert response.status_code == 422


def test_theme_overrides_load_after_the_picker_stylesheet(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/reading/new").text
    assert html.index("/static/vendor/air-datepicker.css") < html.index("/static/hxadmin.css")


def test_picker_hides_its_pointer_and_sits_4px_below_the_input() -> None:
    from pathlib import Path

    import hxadmin

    root = Path(hxadmin.__file__).parent
    css = (root / "static" / "src" / "hxadmin.css").read_text()
    assert ".air-datepicker--pointer {\n  display: none;\n}" in css
    assert "offset: 4," in (root / "templates" / "layout.html").read_text()


DATES_JS = re.compile(r"window\.hxadminDates = \(function \(\) \{.*?\n    \}\)\(\);", re.DOTALL)

DATES_PROBE = """
const d = window.hxadminDates;
const show = (date) => (date ? d.toIso("datetime", date) : null);
console.log(JSON.stringify({
  isoDate: show(d.parseIso("date", "2026-09-23")),
  isoDatetime: show(d.parseIso("datetime", "2026-09-23T14:30")),
  isoTime: d.toIso("time", d.parseIso("time", "09:05")),
  isoBad: show(d.parseIso("date", "2026-02-30")),
  typedDate: show(d.parseTyped("date", "12/25/2026")),
  typedDatetime: show(d.parseTyped("datetime", "1/5/2026 7:45")),
  typedDatetimeNoTime: show(d.parseTyped("datetime", "01/05/2026")),
  typedTime: d.toIso("time", d.parseTyped("time", "7:45")),
  typedBadDay: show(d.parseTyped("date", "02/30/2026")),
  typedBadText: show(d.parseTyped("date", "tomorrow")),
  typedTimeInDate: show(d.parseTyped("date", "12/25/2026 10:00")),
  typedBadTime: show(d.parseTyped("time", "25:00")),
  roundTrip: d.toIso("date", d.parseIso("date", "2026-01-01")),
}));
"""


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="needs node")
def test_date_helpers_parse_local_dates_and_typed_input(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/reading/new").text
    match = DATES_JS.search(html)
    assert match is not None
    script = "var window = {};\n" + match.group(0) + DATES_PROBE
    out = subprocess.run(
        [str(NODE), "-e", script],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "TZ": "America/New_York"},
    ).stdout
    assert json.loads(out) == {
        "isoDate": "2026-09-23T00:00",
        "isoDatetime": "2026-09-23T14:30",
        "isoTime": "09:05",
        "isoBad": None,
        "typedDate": "2026-12-25T00:00",
        "typedDatetime": "2026-01-05T07:45",
        "typedDatetimeNoTime": "2026-01-05T00:00",
        "typedTime": "07:45",
        "typedBadDay": None,
        "typedBadText": None,
        "typedTimeInDate": None,
        "typedBadTime": None,
        "roundTrip": "2026-01-01",
    }


def test_typed_dates_are_committed_on_change(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/reading/new").text
    assert '@change="commit()"' in html
    assert "dates.parseTyped(kind, text)" in html
    assert "new Date(iso)" not in html
