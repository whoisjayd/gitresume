# Contributing to GitResume

Thanks for helping make GitResume easier to self-host and improve. This project is a FastAPI + Vite application with a uv-managed backend and npm-managed frontend.

## Development Setup

1. Fork and clone the repository.
2. Install backend dependencies:

   ```bash
   uv sync
   ```

3. Install frontend dependencies:

   ```bash
   npm --prefix frontend install
   ```

4. Copy local configuration and fill in secrets locally only:

   ```bash
   cp .env.example .env
   # Host-run API/worker processes need localhost; Docker Compose uses redis.
   python -c "from pathlib import Path; p=Path('.env'); p.write_text(p.read_text().replace('REDIS_URL=redis://redis:6379/0','REDIS_URL=redis://localhost:6379/0'))"
   ```

5. Start Redis when running the API/worker locally:

   ```bash
   docker run --rm -p 6379:6379 redis:7-alpine
   ```

## Running Locally

Backend API:

```bash
uv run uvicorn gitresume.main:app --host 0.0.0.0 --port 8080 --reload
```

Worker:

```bash
uv run taskiq worker gitresume.workers.broker:broker gitresume.workers.generation_tasks
```

Frontend:

```bash
npm --prefix frontend run dev
```

Docker stack:

```bash
docker compose up --build
```

## Quality Gates

Run the checks relevant to your change before opening a PR:

```bash
uv run pytest -q
uv run ruff check src tests
npm --prefix frontend run test:run
npm --prefix frontend run build
docker compose config
```

For deployment changes, also run Docker image builds when possible:

```bash
docker build --target runtime -t gitresume-api:test .
docker build -t gitresume-frontend:test frontend
```

## Code Style

- Keep backend code in `src/gitresume` and tests in `tests`.
- Keep frontend code in `frontend/src` and colocate focused component/hook tests when useful.
- Prefer small, typed functions and explicit error handling.
- Add or update tests for behavior changes.
- Avoid broad formatting-only churn in unrelated files.

## Security and Secrets

- Never commit `.env`, provider keys, OAuth secrets, tokens, or generated credentials.
- Do not pass GitHub tokens through background-job payloads or command arguments.
- Use environment variables documented in `.env.example`.
- Treat repository URLs and generated output as user-controlled input.

## Pull Requests

- Create a focused branch for each feature or bug fix.
- Describe the user-facing change and the verification commands you ran.
- Include screenshots or terminal output for UI/deployment changes when helpful.
- Link related issues when applicable.

## Reporting Issues

Use GitHub Issues for bugs and feature requests. Include reproduction steps, expected behavior, actual behavior, logs, and environment details.

## Community

Be respectful and inclusive in all interactions. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) if present.
