.DEFAULT_GOAL := help

SHELL := /bin/bash

UV := $(shell which uv 2>/dev/null || echo "uv")
UVX := $(shell which uvx 2>/dev/null || echo "uvx")
NOX := $(UVX) nox

PY := $(CURDIR)/.venv/bin/python

ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))

XDIST := $(if $(ARGS),,-n auto)


##@ General

.PHONY: help print-% versions
.SILENT: help print-% versions

help: ## Show this help
	grep -E '^[a-zA-Z_/%. -]+:.*?## .*$$|^##@' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} {target=$$1; gsub(/ +/, " | ", target); printf "  \033[36m%-22s\033[0m %s\n", target, $$2}'

print-%: ## Print any variable (e.g. make print-UV)
	echo '$*=$($*)'

versions: ## Show uv, python, node and hxadmin versions
	echo "uv:      $$($(UV) --version 2>/dev/null || echo 'not installed')"
	echo "python:  $$($(PY) --version 2>/dev/null || echo 'not found')"
	echo "node:    $$(node --version 2>/dev/null || echo 'not installed (needed by make css and the JS tests)')"
	echo "hxadmin: $$($(PY) -c 'import hxadmin; print(hxadmin.__version__)' 2>/dev/null || echo 'not found')"


##@ Environment

.PHONY: lock relock sync sync/dry outdated tree why dev dev/up

lock: ## Lock dependencies, upgrading to the highest versions
	$(UV) lock --upgrade

relock: ## Re-lock dependencies without upgrading
	$(UV) lock

sync: ## Sync the environment from the lockfile (all extras + all groups)
	$(UV) sync --locked --all-extras --all-groups

sync/dry: ## Dry-run of sync
	$(UV) sync --locked --all-extras --all-groups --dry-run

outdated: ## List outdated dependencies
	$(UV) pip list --outdated

tree: ## Show the dependency tree
	$(UV) tree

why: ## Show why a package is installed (make why starlette)
	$(if $(ARGS),,$(error usage: make why <package>))
	$(UV) tree --invert $(addprefix --package ,$(ARGS))

dev: relock sync hooks/install ## Set up the development environment (relock + sync + git hooks)

dev/up: lock sync ## Set up the development environment, WARNING: upgrades dependencies (lock + sync)


##@ Build

.PHONY: build css clean

build: ## Build the sdist and wheel
	$(UV) build

css: ## Rebuild src/hxadmin/static/hxadmin.css with Tailwind (needs node)
	$(NOX) -s css

clean: ## Remove build artifacts and caches
	rm -rf dist/ build/ site/ htmlcov/
	rm -rf .pytest_cache/ .ruff_cache/ .nox/ .coverage coverage*.xml junit*.xml
	find . -path ./.venv -prune -o -type d -name '*.egg-info' -print -exec rm -rf {} +
	find . -path ./.venv -prune -o -type d -name __pycache__ -print -exec rm -rf {} +


##@ Frontend

.PHONY: vendor vendor/outdated vendor/update

vendor: ## Show the vendored frontend library versions (vendor.json)
	$(NOX) -s vendor

vendor/outdated: ## Check npm for newer frontend library versions
	$(NOX) -s vendor_outdated

vendor/update: ## Update vendored libraries (make vendor/update htmx.org alpinejs@3.18.0)
	$(if $(ARGS),,$(error usage: make vendor/update <package>[@version] ...))
	$(NOX) -s vendor_update -- $(ARGS)


##@ Run

.PHONY: demo demo-tables

demo: ## Run the demo app with reload on http://127.0.0.1:8001/admin/
	$(UV) run --locked --group demo python -m demo

demo-tables: ## Run the plain-Table demo with reload on http://127.0.0.1:8002/admin/
	$(UV) run --locked --group demo python -m demo_tables


##@ Testing

.PHONY: test cov test/cov cov/report test/matrix test/lowest test/latest test/wheel

test: ## Run tests on the current interpreter, in parallel unless paths are given (make test tests/test_list.py)
	$(UV) run --locked pytest $(XDIST) $(ARGS)

cov test/cov: ## Run tests with coverage (terminal + missing lines)
	$(UV) run --locked pytest $(XDIST) --cov=hxadmin --cov-report=term-missing $(ARGS)

cov/report: ## Run tests with coverage and write xml + html + junit reports
	$(UV) run --locked pytest $(XDIST) --cov=hxadmin --cov-report=term-missing --cov-report=xml --cov-report=html --junitxml=junit.xml $(ARGS)

test/matrix: ## Run tests on every supported Python (3.13, 3.14) via nox
	$(NOX) -s tests

test/lowest: ## Run tests against the lowest allowed direct dependencies via nox
	$(NOX) -s tests_lowest

test/latest: ## Run tests against the newest allowed dependency releases, ignoring the lockfile, via nox
	$(NOX) -s tests_latest

test/wheel: ## Build the wheel and run the tests against it via nox
	$(NOX) -s wheel


##@ Lint & format

.PHONY: lint lint/check lint/fix fmt fmt/check fmt/fix typecheck audit check ci

lint lint/check: ## Check for lint issues (ruff check)
	$(UV) run --locked ruff check

lint/fix: ## Fix lint issues (ruff check --fix), WARNING: modifies source files
	$(UV) run --locked ruff check --fix

fmt fmt/check: ## Check formatting (ruff format --check)
	$(UV) run --locked ruff format --check

fmt/fix: ## Format code (ruff format), WARNING: modifies source files
	$(UV) run --locked ruff format

typecheck: ## Type-check (pyrefly)
	$(UV) run --locked pyrefly check

audit: ## Audit locked dependencies for known vulnerabilities
	$(NOX) -s audit

check: lint/check fmt/check typecheck test ## Run lint, format check, type check and tests (current interpreter)

ci: ## Run what CI runs (nox: lint, wheel, audit, tests, tests_lowest)
	$(NOX) -s lint wheel audit tests tests_lowest


##@ Docs

.PHONY: docs docs/serve

docs: ## Build the docs strictly into site/
	$(NOX) -s docs

docs/serve: ## Serve the docs with live reload
	$(UV) run --locked --group docs zensical serve


##@ Release

.PHONY: changelog tag

changelog: ## Regenerate CHANGELOG.md; VERSION=vX.Y.Z files unreleased commits under that version
	$(NOX) -s changelog $(if $(VERSION),-- --tag $(VERSION))

tag: ## Create annotated tag VERSION=vX.Y.Z carrying its release notes (push it to release)
	$(if $(VERSION),,$(error usage: make tag VERSION=vX.Y.Z))
	git diff --quiet HEAD || { echo "commit your changes first" >&2; exit 1; }
	git tag -a $(VERSION) -m "$(VERSION)" -m "$$($(UVX) git-cliff@2.14.2 --unreleased --tag $(VERSION) --strip all)"
	@echo "tagged $(VERSION); release with: git push origin $(VERSION)"


##@ Git hooks

.PHONY: hooks hooks/install

hooks/install: ## Install the pre-commit and commit-msg git hooks
	$(UVX) prek install --install-hooks

hooks: ## Run the pre-commit hooks on all files
	$(UVX) prek run --all-files


# Extra goals are arguments for the first one (make test tests/test_list.py); never build them.
ifneq ($(ARGS),)
.PHONY: $(ARGS)
$(ARGS):
	@:
endif
