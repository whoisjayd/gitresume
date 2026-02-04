.PHONY: help dev lint format typecheck test check pre-commit hooks

help:
	@echo "Available targets:"
	@echo "  dev         - Install dependencies and pre-commit hooks"
	@echo "  lint        - Run ruff check"
	@echo "  format      - Run ruff format and fix"
	@echo "  typecheck   - Run mypy"
	@echo "  test        - Run pytest"
	@echo "  check       - Run all checks (lint, typecheck, test)"
	@echo "  pre-commit  - Run pre-commit on all files"
	@echo "  hooks       - Install pre-commit hooks"

dev:
	uv sync
	uv run pre-commit install

lint:
	uv run ruff check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy src

test:
	uv run pytest

check: lint typecheck test

pre-commit:
	uv run pre-commit run --all-files

hooks:
	uv run pre-commit install
