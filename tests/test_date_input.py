import datetime
import decimal
import uuid
from collections.abc import Callable

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
