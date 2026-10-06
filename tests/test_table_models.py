import re
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from hxadmin import HxAdmin, ModelView
from tests.conftest import AppFactory, Invoice, Rate, allow_all
from tests.test_list import table_section

type MakeClient = Callable[[FastAPI], TestClient]


async def seed(session: AsyncSession) -> None:
    session.add_all(
        [
            Invoice(customer="acme", total=300, paid=True),
            Invoice(customer="globex", total=100, paid=False),
            Invoice(customer="acme west", total=200, paid=False),
            Rate(code="eur", value=110),
            Rate(code="gbp", value=125),
        ]
    )


def build(factory: AppFactory) -> FastAPI:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.register
    class InvoiceView(ModelView[Invoice]):
        model = Invoice
        searchable = ("customer",)
        list_filters = ("paid",)

    @admin.register
    class RateView(ModelView[Rate]):
        model = Rate

    return app


def customers(html: str) -> list[str]:
    cell = r"<td[^>]*>\s*(?:<a [^>]*>)?\s*([a-z][a-z ]*?)\s*(?:</a>)?\s*</td>"
    return re.findall(cell, table_section(html))


def test_table_model_lists_rows(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.get("/admin/invoice/")
    assert response.status_code == 200
    assert customers(response.text) == ["acme", "globex", "acme west"]


def test_table_model_search(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/invoice/?q=acme").text
    assert customers(html) == ["acme", "acme west"]


def test_table_model_sort(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        ascending = client.get("/admin/invoice/?sort=total&dir=asc").text
        descending = client.get("/admin/invoice/?sort=total&dir=desc").text
    assert customers(ascending) == ["globex", "acme west", "acme"]
    assert customers(descending) == ["acme", "acme west", "globex"]


def test_table_model_filter(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        html = client.get("/admin/invoice/?f.paid=false").text
    assert customers(html) == ["globex", "acme west"]


def test_table_model_create(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/invoice/new",
            data={"customer": "initech", "total": "50", "paid": "on"},
            follow_redirects=False,
        )
        listing = client.get("/admin/invoice/").text
    assert response.status_code == 303
    assert customers(listing) == ["acme", "globex", "acme west", "initech"]


def test_table_model_edit(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/invoice/2/edit",
            data={"customer": "globex corp", "total": "100", "paid": ""},
            follow_redirects=False,
        )
        listing = client.get("/admin/invoice/").text
    assert response.status_code == 303
    assert customers(listing) == ["acme", "globex corp", "acme west"]


def test_table_model_delete(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/invoice/1/delete", follow_redirects=False)
        listing = client.get("/admin/invoice/").text
    assert response.status_code == 303
    assert customers(listing) == ["globex", "acme west"]


def test_mapper_primary_key_is_not_editable(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        detail = client.get("/admin/rate/eur")
        edit_form = client.get("/admin/rate/eur/edit").text
    assert detail.status_code == 200
    assert 'name="value"' in edit_form
    assert 'name="code"' not in edit_form


def test_mapper_primary_key_create(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        create_form = client.get("/admin/rate/new").text
        response = client.post(
            "/admin/rate/new", data={"code": "usd", "value": "100"}, follow_redirects=False
        )
        detail = client.get("/admin/rate/usd")
    assert 'name="code"' in create_form
    assert response.status_code == 303
    assert detail.status_code == 200


def test_mapper_primary_key_edit(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post(
            "/admin/rate/eur/edit", data={"value": "111"}, follow_redirects=False
        )
        detail = client.get("/admin/rate/eur").text
    assert response.status_code == 303
    assert ">111<" in detail


def test_mapper_primary_key_delete(factory: AppFactory, make_client: MakeClient) -> None:
    with make_client(build(factory)) as client:
        response = client.post("/admin/rate/gbp/delete", follow_redirects=False)
        gone = client.get("/admin/rate/gbp")
    assert response.status_code == 303
    assert gone.status_code == 404


def test_first_text_column_takes_the_remaining_width(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        table = table_section(client.get("/admin/invoice/").text)
    headers = re.findall(r'<th class="px-3 py-2 font-medium([^"]*)"', table)
    assert len(headers) == 4
    assert " w-px whitespace-nowrap" in headers[0]
    assert "w-px" not in headers[1]
    assert all(" w-px whitespace-nowrap" in extra for extra in headers[2:])


def test_filler_column_takes_the_width_when_no_text_column(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        table = table_section(client.get("/admin/rate/").text)
    head = table[: table.index("</thead>")]
    headers = re.findall(r'<th class="px-3 py-2 font-medium([^"]*)"', head)
    assert all(" w-px whitespace-nowrap" in extra for extra in headers)
    assert head.count('aria-hidden="true" class="p-0"') == 1
    assert table.count('<td aria-hidden="true" class="p-0"></td>') == 2


def test_row_link_sits_on_the_first_text_column(
    factory: AppFactory, make_client: MakeClient
) -> None:
    with make_client(build(factory)) as client:
        table = table_section(client.get("/admin/invoice/").text)
    links = re.findall(r'<a href="/admin/invoice/(\d+)"[^>]*>\s*([^<]*?)\s*</a>', table)
    assert links == [("1", "acme"), ("2", "globex"), ("3", "acme west")]
