install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run pytest

clean:
	uv run python -c "import os, shutil; [shutil.rmtree(p) for p in ['dist', 'build', '.pytest_cache', '.ruff_cache'] if os.path.exists(p)]; [[shutil.rmtree(os.path.join(r, d)) for d in dirs if d == '__pycache__'] for r, dirs, files in os.walk('.')]"
