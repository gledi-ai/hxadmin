# Contributing

Thanks for helping improve hxadmin. Bug reports, fixes and documentation are all welcome; for a larger feature, open an issue first so we can agree on the approach.

## Setup

You need [uv](https://docs.astral.sh/uv/). Node.js is only needed to rebuild the CSS and run the JavaScript tests.

```bash
make dev    # sync every dependency group and install the git hooks
make help   # list every task
```

## Making a change

- Write a failing test first, then the fix. Tests go through the public interface: HTTP requests against a seeded app (see `tests/conftest.py`), or a module's public functions.
- `make check` runs ruff, the format check, pyrefly and the tests. `make ci` runs what CI runs, across every supported Python and against the lowest supported dependency versions.
- Template or class changes may need `make css` to rebuild `src/hxadmin/static/hxadmin.css`; commit the result.
- Update `docs/` when behaviour changes. `make docs` builds them strictly.
- Vendored frontend libraries are pinned in `vendor.json`. Update them with `make vendor/update <package>`, never by hand.

## Commits and pull requests

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, ...); the `commit-msg` hook enforces it. `feat`, `fix`, `perf`, `refactor` and `docs` commits appear in the changelog, so write their subject for users.

Keep pull requests focused on one change, and say in the description how you verified it.

## Releasing

Maintainers tag `vX.Y.Z` on `main` after `make changelog VERSION=vX.Y.Z`. The tag's workflow tests the wheel and publishes to PyPI.
