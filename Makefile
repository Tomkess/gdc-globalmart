# GlobalMart's make targets, on the Services-MIC-Cloud / gd-ecommerce-demo pattern (FEAT-019).
# The gd-* targets run the pinned gdcloud toolkit; `project` / `project-check` run GlobalMart's
# own projection of the parent layout into gd_data_product/globalmart/ (ADR 011).

.PHONY: dev dev-core install adopt test lint lint-ruff lint-yaml format-yaml project project-check \
	store upload validate ci help

# How to invoke the installed CLIs. `uv run` locally; override with `make <tgt> RUN=`
# when the venv is already activated and the entry points are on PATH.
RUN ?= uv run

# Refresh the pinned toolkit's CI after installing. Set ADOPT_CI=0 to skip it.
ADOPT_CI ?= 1

# =============================================================================
# Setup
# =============================================================================

# No --upgrade, unlike MIC: gooddata-sdk is pinned exactly for byte-stable layouts (FEAT-001),
# and gdcloud moves only through its pin (auto_gdcloud_pin.yml).
dev:
	uv sync --all-extras --dev
	@if [ "$(ADOPT_CI)" = "1" ]; then $(MAKE) adopt; fi

dev-core install:
	uv sync

adopt:  ## Install the pinned toolkit's CI workflows, actions and scripts
	@$(RUN) gd-workflows adopt .

# =============================================================================
# Testing and code quality
# =============================================================================

test:
	$(RUN) pytest tests/ -q

lint: lint-ruff lint-yaml

lint-ruff:
	@$(RUN) ruff check src tests gd_plugin
	@$(RUN) mypy

# gd_data_product/ is machine-written by `project`; gd-format-yaml checks its shape.
lint-yaml:
	$(RUN) gd-format-yaml --check --data-product-all
	@$(RUN) yamllint .

format-yaml:
	$(RUN) gd-format-yaml

# =============================================================================
# The parent data product
# =============================================================================

# layouts/workspaces/globalmart/ is the authoring surface; gd_data_product/globalmart/ is
# derived from it. Regenerate after every parent change, and commit both.
project:
	$(RUN) globalmart gdcloud project

project-check:
	$(RUN) globalmart gdcloud project --check

# =============================================================================
# GoodData operations (gdcloud)
# =============================================================================

# Routine releases go through the workflows, not these. `store` exists for gdcloud's
# feature-branch flow; under Stage A a store into gd_data_product/globalmart/ is drift,
# and the projection_current check says so.
store:
	$(RUN) gd-store

upload:
	$(RUN) gd-upload

validate:
	$(RUN) gd-validate

ci:
	$(RUN) gd-ci run

help:
	@echo "Setup:      make dev | dev-core | adopt"
	@echo "Quality:    make test | lint | format-yaml"
	@echo "Parent DP:  make project | project-check"
	@echo "gdcloud:    make validate | ci | upload | store"
