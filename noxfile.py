import base64
import hashlib
import io
import json
import re
import tarfile
import urllib.request
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

import nox

nox.options.default_venv_backend = "uv"
nox.options.sessions = ["lint", "tests"]

PYPROJECT = nox.project.load_toml("pyproject.toml")
PYTHON_VERSIONS = nox.project.python_versions(PYPROJECT)


def pytest_args(session: nox.Session) -> list[str]:
    """The session's posargs, or the whole suite across all CPUs when none are given."""
    return session.posargs or ["-n", "auto"]


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
    session.run("pytest", "--cov", *pytest_args(session))


@nox.session(python=PYTHON_VERSIONS)
def tests_lowest(session: nox.Session) -> None:
    test_deps = nox.project.dependency_groups(PYPROJECT, "test")
    session.install("--resolution=lowest-direct", "-e", ".", *test_deps)
    session.run("pytest", *pytest_args(session))


@nox.session
def wheel(session: nox.Session) -> None:
    dist = session.create_tmp()
    session.run("uv", "build", "--wheel", "--out-dir", dist, external=True)
    session.install(*Path(dist).glob("*.whl"), *nox.project.dependency_groups(PYPROJECT, "test"))
    session.run("pytest", *pytest_args(session))


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
    tailwind = _manifest()["tailwindcss"]["version"]
    session.run(
        "npm",
        "install",
        "--no-save",
        "--no-package-lock",
        f"tailwindcss@{tailwind}",
        f"@tailwindcss/cli@{tailwind}",
        external=True,
    )
    session.run(
        "npx",
        "--yes",
        f"@tailwindcss/cli@{tailwind}",
        "-i",
        CSS_SRC,
        "-o",
        CSS_OUT,
        "--minify",
        external=True,
    )


VENDOR_MANIFEST = Path("vendor.json")
VENDOR_DIR = Path("src/hxadmin/static/vendor")


def _manifest() -> dict:
    return json.loads(VENDOR_MANIFEST.read_text())


def _npm(package: str, version: str = "") -> dict:
    url = f"https://registry.npmjs.org/{package}" + (f"/{version}" if version else "")
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def _release(version: str) -> tuple[int, ...] | None:
    if re.fullmatch(r"\d+\.\d+\.\d+", version):
        return tuple(int(part) for part in version.split("."))
    return None


def _newest(versions: list[str], major: int | None = None) -> str:
    releases = [(r, v) for v in versions if (r := _release(v)) and major in (None, r[0])]
    return max(releases)[1]


@nox.session(python=False)
def vendor(session: nox.Session) -> None:
    for package, entry in _manifest().items():
        session.log(f"{package:<20} {entry['version']}")


@nox.session(python=False)
def vendor_outdated(session: nox.Session) -> None:
    session.log(f"{'package':<20} {'vendored':<10} {'same major':<12} newest")
    for package, entry in _manifest().items():
        current = entry["version"]
        versions = list(_npm(package)["versions"])
        same_major = _newest(versions, _release(current)[0])
        newest = _newest(versions)
        flag = "" if same_major == newest == current else "  <- update available"
        session.log(f"{package:<20} {current:<10} {same_major:<12} {newest}{flag}")


@nox.session(python=False)
def vendor_update(session: nox.Session) -> None:
    """Update vendored packages: `nox -s vendor_update -- htmx.org alpinejs@3.18.0`.

    Without `@version`, takes the newest release in the vendored major version.
    """
    if not session.posargs:
        session.error("usage: nox -s vendor_update -- <package>[@<version>] ...")
    manifest = _manifest()
    for spec in session.posargs:
        package, _, version = spec.rpartition("@") if spec.rfind("@") > 0 else (spec, "", "")
        if package not in manifest:
            session.error(f"{package} is not in {VENDOR_MANIFEST}")
        entry = manifest[package]
        current = entry["version"]
        if not version:
            version = _newest(list(_npm(package)["versions"]), _release(current)[0])
        if version == current:
            session.log(f"{package} is already at {current}")
            continue
        meta = _npm(package, version)
        if entry.get("files"):
            _vendor_files(session, meta, entry["files"])
        if notice := entry.get("notice"):
            path, template = VENDOR_DIR / notice[0], notice[1]
            text, old = path.read_text(), template.format(version=current)
            if old not in text:
                session.error(f"{path} does not mention {old!r}")
            path.write_text(text.replace(old, template.format(version=version)))
        entry["version"] = version
        VENDOR_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
        session.log(f"{package}: {current} -> {version}")
        if package == "tailwindcss":
            session.log("run `make css` to rebuild hxadmin.css with the new Tailwind")


def _vendor_files(session: nox.Session, meta: dict, files: dict[str, str]) -> None:
    url = meta["dist"]["tarball"]
    if not url.startswith("https://registry.npmjs.org/"):
        session.error(f"unexpected tarball URL {url}")
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        tarball = response.read()
    algorithm, _, digest = meta["dist"]["integrity"].partition("-")
    if base64.b64encode(hashlib.new(algorithm, tarball).digest()).decode() != digest:
        session.error(f"integrity check failed for {url}")
    with tarfile.open(fileobj=io.BytesIO(tarball)) as tar:
        members = {m.name.removeprefix("package/"): m for m in tar.getmembers() if m.isfile()}

        def read(name: str) -> bytes:
            data = tar.extractfile(members[name]).read()
            return data if data.endswith(b"\n") else data + b"\n"

        for source, dest in files.items():
            if dest.endswith("/"):
                directory = VENDOR_DIR / dest
                pattern = PurePosixPath(source)
                for old in directory.glob(pattern.name):
                    old.unlink()
                for name in sorted(members):
                    if PurePosixPath(name).parent == pattern.parent and fnmatch(
                        PurePosixPath(name).name, pattern.name
                    ):
                        (directory / PurePosixPath(name).name).write_bytes(read(name))
            else:
                (VENDOR_DIR / dest).write_bytes(read(source))


@nox.session(python=False)
def changelog(session: nox.Session) -> None:
    session.run(
        "uvx", "git-cliff@2.14.2", "--output", "CHANGELOG.md", *session.posargs, external=True
    )
