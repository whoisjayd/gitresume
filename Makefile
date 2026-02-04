.PHONY: help dev lint format typecheck test check pre-commit hooks docker-build docker-run

help:
	@echo "Available targets:"
	@echo "  dev          - Install dependencies and pre-commit hooks"
	@echo "  lint         - Run ruff check"
	@echo "  format       - Run ruff format and fix"
	@echo "  typecheck    - Run mypy"
	@echo "  test         - Run pytest"
	@echo "  check        - Run all checks (lint, typecheck, test)"
	@echo "  pre-commit   - Run pre-commit on all files"
	@echo "  hooks        - Install pre-commit hooks"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Run Docker image (requires .env file)"

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

docker-build:
	docker build -t gitresume .

docker-run:
	docker run --rm -it --env-file .env gitresume
