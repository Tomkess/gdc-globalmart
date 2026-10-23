# Toolkit-owned targets; `gd-workflows adopt` overwrites this file.
# Put project settings and targets in the including Makefile.

RUN ?= uv run --no-sync
TOOLS ?= auto
ADOPT_CI ?= 1
DEV_EXTRA ?=

# The data-product recipes below need these; the including Makefile sets them
# (the scaffolded one defaults them to the project's primary data product and
# environment). Guarded rather than passed through empty: argparse would take
# the NEXT flag as the value of `--data-product-id`, so an unset variable
# surfaces as a baffling CLI error instead of a missing setting.
DP ?=
GD_ENV ?=

# Override after the include to choose another default.
.DEFAULT_GOAL := help

.PHONY: dev dev-core install link-skills adopt adopt-check \
        store validate ci tag tag-check db format lint help

# Setup

# Named extras can disappear; `--all-extras` keeps this recipe release-agnostic.
# uv has no post-install hook, so `dev` explicitly adopts the matching CI.
dev:  ## Install everything — toolkit, test tools, skills, and the toolkit's CI
	uv sync --all-extras
	@$(MAKE) link-skills
	@if [ "$(ADOPT_CI)" = "1" ]; then $(MAKE) adopt; fi
	@$(if $(DEV_EXTRA),$(MAKE) $(DEV_EXTRA),:)

dev-core:  ## Install the toolkit only — no test tools, no skills
	uv sync

install: dev-core

# Links are absolute, so create them from this project's venv.
link-skills:  ## Re-link the toolkit's skills (after a toolkit upgrade)
	@$(RUN) gd-skills link --tools "$(TOOLS)"

adopt:  ## Install the pinned toolkit's CI and make targets
	@$(RUN) gd-workflows adopt .

adopt-check:  ## Compare the installed CI with the pinned toolkit (no writes)
	@$(RUN) gd-workflows adopt . --check

# Data product operations

# No `.PHONY`: make has no pattern-rule support there, and a guard-% target
# never creates a file, so its recipe runs on every request anyway.
guard-%:
	@if [ -z "$($*)" ]; then \
		echo "make: $* is not set — add '$* ?= <value>' to your Makefile, or pass '$*=<value>'" >&2; \
		exit 1; \
	fi

store: guard-DP guard-GD_ENV  ## Pull the workspace model from the org into git
	$(RUN) gd-store --data-product-id $(DP) --environment $(GD_ENV)

validate: guard-DP  ## Offline LDM structural checks
	$(RUN) gd-validate ldm-integrity --data-product-id $(DP)

ci: guard-DP  ## Offline CI checks
	$(RUN) gd-ci run --data-product-id $(DP) --all

tag: guard-DP  ## Apply the tags declared in config.tagging.yml
	$(RUN) gd-tagging sync --data-product-id $(DP)

tag-check: guard-DP  ## Report tag drift without writing
	$(RUN) gd-tagging sync --check --data-product-id $(DP)

db: guard-DP  ## Export workspace metadata to SQLite
	$(RUN) gd-db --data-product-id $(DP) --local

format: guard-DP  ## Normalize YAML to SDK formatting
	$(RUN) gd-format-yaml --data-product-id $(DP)

lint: guard-DP  ## Check YAML formatting without writing
	$(RUN) gd-format-yaml --data-product-id $(DP) --check

# Help

# Include documented project targets too.
help:
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN{FS=":.*?## "}{printf "  make %-14s %s\n", $$1, $$2}'
