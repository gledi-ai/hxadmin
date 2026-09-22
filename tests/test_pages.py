from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

import hxadmin
from hxadmin import HxAdmin, ModelView, Page
from hxadmin.nav import NavGroup, NavItem, build_nav
from tests.conftest import AppFactory, User, allow_all
from tests.test_detail import seed
from tests.test_nav import _request

type MakeClient = Callable[[FastAPI], TestClient]

SYNC = (
    '{% extends "page.html" %}{% block body %}'
    "<p>users: {{ users }} path: {{ path }} who: {{ user.name }}</p>{% endblock %}"
)
JOB = '{% extends "page.html" %}{% block body %}job {{ job_id }} q={{ q }}{% endblock %}'


class UserView(ModelView[User]):
    model = User


def build(factory: AppFactory, tmp_path: Path) -> tuple[FastAPI, HxAdmin]:
    (tmp_path / "sync.html").write_text(SYNC)
    (tmp_path / "job.html").write_text(JOB)
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all, templates_dir=tmp_path)
    admin.register(UserView)

    @admin.page("/sync", title="Sync management", category="Ops", icon="refresh")
    async def sync_page(
        request: Request, session: Annotated[AsyncSession, Depends(factory.get_session)]
    ) -> Page:
        users = await session.scalar(select(func.count()).select_from(User))
        return Page("sync.html", {"users": users, "path": request.url.path})

    @admin.route("/jobs/{job_id}", title="Job")
    async def job(job_id: int, q: str = "") -> Page:
        return Page("job.html", {"job_id": job_id, "q": q})

    @admin.route("/api/stats")
    async def stats() -> JSONResponse:
        return JSONResponse({"ok": True})

    @admin.route("/sync/run", methods=("POST",))
    async def run(request: Request) -> RedirectResponse:
        return RedirectResponse(admin.url(request, "/sync"), status_code=303)

    @admin.page("/reports/monthly", title="Monthly")
    async def monthly() -> Page:
        return Page("page.html")

    return app, admin


def test_page_renders_in_admin_shell(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    app, _ = build(factory, tmp_path)
    with make_client(app) as client:
        response = client.get("/admin/sync")
    html = response.text
    assert response.status_code == 200
    assert "<title>Sync management · HxAdmin</title>" in html
    assert '<h1 class="mb-6 text-2xl font-semibold">Sync management</h1>' in html
    assert "users: 2 path: /admin/sync who: admin@example.com" in html
    assert 'href="/admin/sync"' in html
    assert 'href="/admin/user/"' in html


def test_route_takes_path_and_query_params(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    app, _ = build(factory, tmp_path)
    with make_client(app) as client:
        ok = client.get("/admin/jobs/7?q=x")
        bad = client.get("/admin/jobs/abc")
    assert ok.status_code == 200
    assert "job 7 q=x" in ok.text
    assert "<title>Job · HxAdmin</title>" in ok.text
    assert bad.status_code == 422


def test_pages_are_in_nav_and_routes_are_not(factory: AppFactory, tmp_path: Path) -> None:
    _, admin = build(factory, tmp_path)
    assert build_nav(admin, _request("/admin/sync")) == [
        NavGroup(
            label=None,
            items=(
                NavItem("Users", "/admin/user/", None, False),
                NavItem("Monthly", "/admin/reports/monthly", None, False),
            ),
        ),
        NavGroup(label="Ops", items=(NavItem("Sync management", "/admin/sync", "refresh", True),)),
    ]


def test_non_page_results_pass_through(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    app, _ = build(factory, tmp_path)
    with make_client(app) as client:
        stats = client.get("/admin/api/stats")
        run = client.post("/admin/sync/run", follow_redirects=False)
        wrong_method = client.get("/admin/sync/run")
    assert stats.json() == {"ok": True}
    assert run.status_code == 303
    assert run.headers["location"] == "/admin/sync"
    assert wrong_method.status_code == 405


def test_page_beats_model_routes(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    app, _ = build(factory, tmp_path)
    with make_client(app) as client:
        response = client.get("/admin/reports/monthly")
    assert response.status_code == 200
    assert '<h1 class="mb-6 text-2xl font-semibold">Monthly</h1>' in response.text


def test_pages_require_auth(factory: AppFactory, make_client: MakeClient) -> None:
    def deny() -> None:
        raise HTTPException(status_code=401)

    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=deny, login_url="/login")

    @admin.page("/sync", title="Sync")
    async def sync_page() -> Page:
        return Page("page.html")

    with make_client(app) as client:
        native = client.get("/admin/sync", follow_redirects=False)
        hx = client.get("/admin/sync", headers={"HX-Request": "true"})
    assert native.status_code == 303
    assert native.headers["location"] == "/login"
    assert hx.headers["HX-Redirect"] == "/login"


@pytest.mark.parametrize(
    "path", ["/", "", "sync", "/{x}", "/{x}/y", "/static", "/static/x", "/user", "/user/stats"]
)
def test_invalid_or_colliding_paths_are_rejected(factory: AppFactory, path: str) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    admin.register(UserView)
    with pytest.raises(ValueError, match="Page path"):
        admin.route(path)


def test_view_registered_after_page_cannot_shadow_it(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.route("/user/stats")
    async def stats() -> Page:
        return Page("page.html")

    with pytest.raises(ValueError, match="page path already uses 'user'"):
        admin.register(UserView)


def test_sidebar_page_rejects_path_params(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)
    with pytest.raises(ValueError, match=r"use admin\.route"):
        admin.page("/jobs/{job_id}", title="Jobs")


def test_sync_handler_is_rejected(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    def sync_page() -> Page:
        return Page("page.html")

    with pytest.raises(TypeError, match="must be an async function"):
        admin.page("/sync", title="Sync")(cast(Any, sync_page))


def test_page_is_exported() -> None:
    assert hxadmin.Page is Page
    assert "Page" in hxadmin.__all__


def test_json_able_results_are_serialised(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)

    @admin.route("/api/info")
    async def info() -> dict[str, Any]:
        return {"ok": True, "n": 2}

    with make_client(app) as client:
        response = client.get("/admin/api/info")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "n": 2}


def test_methods_split_across_registrations(factory: AppFactory, make_client: MakeClient) -> None:
    app = factory.app(seed=seed)
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all)
    admin.register(UserView)

    @admin.route("/sync/job")
    async def show() -> JSONResponse:
        return JSONResponse({"method": "GET"})

    @admin.route("/sync/job", methods=("POST",))
    async def run() -> JSONResponse:
        return JSONResponse({"method": "POST"})

    with make_client(app) as client:
        get = client.get("/admin/sync/job")
        post = client.post("/admin/sync/job")
        delete = client.delete("/admin/sync/job")
    assert get.json() == {"method": "GET"}
    assert post.json() == {"method": "POST"}
    assert delete.status_code == 405
    assert set(delete.headers["allow"].split(", ")) == {"GET", "HEAD", "POST"}


def test_duplicate_page_registrations_are_rejected(factory: AppFactory) -> None:
    admin = HxAdmin(factory.app(), session=factory.get_session, auth=allow_all)

    @admin.page("/sync", title="Sync")
    async def sync() -> Page:
        return Page("page.html")

    with pytest.raises(ValueError, match="already registered"):

        @admin.route("/sync")
        async def again() -> Page:
            return Page("page.html")

    with pytest.raises(ValueError, match="already in the sidebar"):

        @admin.page("/sync", title="Sync again", methods=("POST",))
        async def post() -> Page:
            return Page("page.html")


def test_handler_context_keeps_its_own_page_key(
    factory: AppFactory, make_client: MakeClient, tmp_path: Path
) -> None:
    (tmp_path / "paged.html").write_text(
        '{% extends "page.html" %}{% block body %}page={{ page }}{% endblock %}'
    )
    app = factory.app()
    admin = HxAdmin(app, session=factory.get_session, auth=allow_all, templates_dir=tmp_path)

    @admin.page("/paged", title="Paged")
    async def paged() -> Page:
        return Page("paged.html", {"page": 3})

    with make_client(app) as client:
        html = client.get("/admin/paged").text
    assert "page=3" in html
    assert "<title>Paged · HxAdmin</title>" in html
