# hxadmin

Admin interface for FastAPI and SQLAlchemy 2.0+, built with Tailwind CSS and htmx.

## Development

```bash
uv sync            # installs the dev group (lint + test + ipython)
prek install       # git hooks: ruff, pyrefly, uv-lock
nox                # lint + tests on every supported Python
nox -s tests-3.14  # single Python version
nox -s tests_lowest  # tests against the lowest supported dependency versions
nox -s wheel       # tests against the built wheel
nox -s audit       # dependency vulnerability audit
```

Versions come from git tags (`v0.1.0`) via uv-dynamic-versioning.
