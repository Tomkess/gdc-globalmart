# GlobalMart's make targets (FEAT-019). The toolkit's own targets — dev, adopt, store, validate,
# ci, format, lint, tag, db, help — come from .github/gdcloud.mk, which `gd-workflows adopt`
# rewrites on every pin bump, so they never go stale here. Only GlobalMart's targets live below.

# The one data product, and the environment `make store` / `make upload` address by default.
DP ?= globalmart
GD_ENV ?= dev

include .github/gdcloud.mk

.PHONY: test quality upload

test:  ## Run the test suite
	$(RUN) pytest tests/ -q

quality:  ## ruff, mypy and yamllint over the whole repo
	$(RUN) ruff check src tests gd_plugin
	$(RUN) mypy
	$(RUN) yamllint .

# gd_data_product/globalmart/ is the parent's only authoring tree (ADR 011 Stage B): edit it, or
# `make store` from a dev workspace, then `make format` and `globalmart split`. gdcloud's own
# `make lint` (gd-format-yaml --check) is the formatting gate, the same one CI runs.

# Routine releases go through workflows 3/4/5, not this.
upload: guard-DP guard-GD_ENV  ## Deploy the committed tree to GD_ENV's master by hand
	$(RUN) gd-upload --data-product-id $(DP) --environment $(GD_ENV) --branch master
