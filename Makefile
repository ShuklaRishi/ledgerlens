# `make help` lists targets.
COMPOSE ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose)

.DEFAULT_GOAL := help
.PHONY: help install fetch-data up down reset db-check psql seed ask api ui eval-v1 eval-v2 compare rescore test lint fmt

Q ?= What was revenue by store last month?

help: ## list targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-11s %s\n", $$1, $$2}'

install: ## install Python deps into .venv
	uv sync

fetch-data: ## download pinned Pagila SQL (checksum-verified)
	@./db/fetch_pagila.sh

up: fetch-data ## start Postgres 16 + pgvector (loads Pagila on first start) and Phoenix
	$(COMPOSE) up -d --wait db phoenix

down: ## stop Postgres and Phoenix (keeps data)
	$(COMPOSE) down

reset: ## drop the DB and trace volumes, reload Pagila from scratch
	$(COMPOSE) down -v
	$(MAKE) up

db-check: ## verify Pagila is loaded and agent_ro cannot write
	uv run ledgerlens db-check

psql: ## psql shell as the read-only agent role
	$(COMPOSE) exec db psql -U agent_ro -d pagila

seed: ## embed metric definitions + schema docs into pgvector (local model, no API calls)
	uv run ledgerlens seed

ask: ## ask a question: make ask Q="Which film categories earned the most last month?"
	uv run ledgerlens ask "$(Q)"

api: ## FastAPI with reload on http://localhost:8000 (docs at /docs)
	uv run uvicorn ledgerlens.main:app --reload

ui: ## Streamlit chat for business users on http://localhost:8501 (needs `make api` running)
	uv run --extra ui streamlit run ui/app.py

eval-v1: ## golden set against v1 (every failure mode on); ~20 cases, ~55 model calls
	uv run python -m evals.run --version v1 $(if $(CASES),--cases $(CASES))

eval-v2: ## golden set against v2 (fixed); CASES=a,b runs a subset
	uv run python -m evals.run --version v2 $(if $(CASES),--cases $(CASES))

compare: ## compare the latest v1 and v2 eval reports (regressions first)
	uv run python -m evals.compare --latest v1 v2

rescore: ## re-score saved eval reports from their run records, no model calls (REPORTS=a.json b.json)
	$(if $(REPORTS),,$(error set REPORTS to one or more evals/reports/*.json))
	uv run python -m evals.rescore $(REPORTS)

test: ## unit + integration tests (integration skips when the DB is down)
	uv run pytest -q

lint: ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## auto-fix lint + format
	uv run ruff check --fix .
	uv run ruff format .
