from pathlib import Path

import nox

nox.options.default_venv_backend = "uv"
nox.options.sessions = ["lint", "tests"]

PYPROJECT = nox.project.load_toml("pyproject.toml")
PYTHON_VERSIONS = nox.project.python_versions(PYPROJECT)


def sync(session: nox.Session, *groups: str) -> None:
    session.run_install(
        "uv",
        "sync",
        "--locked",
        "--no-default-groups",
        *(f"--group={group}" for group in groups),
        f"--python={session.virtualenv.location}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )


@nox.session(python=PYTHON_VERSIONS)
def tests(session: nox.Session) -> None:
    sync(session, "test")
    session.run("pytest", "--cov", *session.posargs)


@nox.session(python=PYTHON_VERSIONS)
def tests_lowest(session: nox.Session) -> None:
    test_deps = nox.project.dependency_groups(PYPROJECT, "test")
    session.install("--resolution=lowest-direct", "-e", ".", *test_deps)
    session.run("pytest", *session.posargs)


@nox.session
def wheel(session: nox.Session) -> None:
    dist = session.create_tmp()
    session.run("uv", "build", "--wheel", "--out-dir", dist, external=True)
    session.install(*Path(dist).glob("*.whl"), *nox.project.dependency_groups(PYPROJECT, "test"))
    session.run("pytest", *session.posargs)


@nox.session(python=False)
def audit(session: nox.Session) -> None:
    session.run("uv", "audit", "--locked")


@nox.session
def lint(session: nox.Session) -> None:
    sync(session, "lint", "test")
    session.run("ruff", "check")
    session.run("ruff", "format", "--check")
    session.run("pyrefly", "check")
    session.run("zizmor", ".github")


@nox.session(python=False)
def docs(session: nox.Session) -> None:
    session.run(
        "uv", "run", "--group", "docs", "zensical", "build", "--strict", "--clean", external=True
    )


CSS_SRC = "src/hxadmin/static/src/hxadmin.css"
CSS_OUT = "src/hxadmin/static/hxadmin.css"


@nox.session(python=False)
def css(session: nox.Session) -> None:
    session.run(
        "npm",
        "install",
        "--no-save",
        "--no-package-lock",
        "tailwindcss@4.3.3",
        "@tailwindcss/cli@4.3.3",
        external=True,
    )
    session.run(
        "npx",
        "--yes",
        "@tailwindcss/cli@4.3.3",
        "-i",
        CSS_SRC,
        "-o",
        CSS_OUT,
        "--minify",
        external=True,
    )
