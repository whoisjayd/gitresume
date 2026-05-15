# GitResume

Self-hostable FastAPI + Vite application that turns GitHub repositories into resume-ready project summaries, ATS-friendly bullet points, interview prep, and exportable plain-text/LaTeX snippets using LiteLLM-compatible AI providers.

## Highlights

- **Modern self-hosting stack:** FastAPI backend in `src/gitresume`, Vite React frontend in `frontend`, Redis-backed jobs/events, and Docker Compose deployment.
- **Repository intelligence:** Secure clone/checkout, Repomix-powered packing, ranked context selection, tree-sitter analysis, dependency summaries, git-history signals, and gitingest fallback.
- **Async generation flow:** Taskiq worker executes long-running analysis/generation while the frontend follows progress over Server-Sent Events.
- **Provider-flexible AI:** Configure Gemini, OpenAI, Anthropic, Groq, or any LiteLLM-supported provider via environment variables.
- **OSS-friendly:** No checked-in secrets, uv lockfile for backend reproducibility, npm lockfile for frontend reproducibility, and containerized local production stack.

## Architecture

```text
frontend/ (Vite React SPA)
    │  /api proxy in development or nginx in Docker
    ▼
src/gitresume/main.py (FastAPI API)
    │  enqueue generation + stream status
    ▼
Redis (state, token handoff, event stream, Taskiq broker)
    │
    ▼
Taskiq worker (clone repo, analyze, call LiteLLM, persist result)
```

## Tech Stack

| Area | Technology |
| --- | --- |
| Backend | Python 3.11/3.12, FastAPI, Pydantic, Redis, Taskiq, SSE |
| Frontend | React 19, TypeScript, Vite 8 |
| AI | LiteLLM with Gemini/OpenAI/Anthropic/Groq-compatible keys |
| Repository analysis | git, Repomix via `npx repomix@1.14.0`, tree-sitter-analyzer, gitingest, NetworkX, tiktoken |
| Packaging | uv + `uv.lock`, npm + `package-lock.json` |
| Deployment | Docker, Docker Compose, nginx static frontend |

## Prerequisites

### Docker self-hosting

- Docker with Compose v2
- Provider API key for the `AI_MODEL` you choose
- Optional GitHub OAuth app credentials for private repositories

### Local development

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 24+ and npm
- Redis 7+
- git

## Quick Start with Docker Compose

1. Copy and edit environment variables:

   ```bash
   cp .env.example .env
   ```

2. Set at least:

   ```env
   SESSION_SECRET_KEY=replace-with-a-long-random-secret
   AI_MODEL=gemini/gemini-1.5-flash
   GEMINI_API_KEY=...
   ```

   For private repository access, also set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and/or `GITHUB_TOKEN`.

3. Start the stack:

   ```bash
   docker compose up --build
   ```

4. Open the frontend at <http://localhost:5173>.

Services:

- Frontend: <http://localhost:5173>
- API: <http://localhost:8080>
- Health: <http://localhost:8080/api/health>
- Redis: internal Compose network only

## Local Development

### Backend

```bash
uv sync
cp .env.example .env
# For host-run backend/worker processes, use the host-mapped Redis address.
# Docker Compose keeps REDIS_URL=redis://redis:6379/0 for in-network services.
python -c "from pathlib import Path; p=Path('.env'); p.write_text(p.read_text().replace('REDIS_URL=redis://redis:6379/0','REDIS_URL=redis://localhost:6379/0'))"
uv run uvicorn gitresume.main:app --host 0.0.0.0 --port 8080 --reload
```

The backend expects Redis at `REDIS_URL`; for local development you can run:

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

### Worker

Run the worker in a second terminal:

```bash
uv run taskiq worker gitresume.workers.broker:broker gitresume.workers.generation_tasks
```

### Frontend

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

The Vite dev server proxies `/api` to `http://localhost:8080` by default. Override with `VITE_API_PROXY_TARGET` if needed.

## Configuration

Copy `.env.example` to `.env`. Key settings:

| Variable | Purpose |
| --- | --- |
| `ENVIRONMENT` | Runtime environment label, usually `production` in Docker |
| `SESSION_SECRET_KEY` | Required session signing secret |
| `FRONTEND_ORIGIN` | Allowed browser origin for CORS |
| `ALLOWED_HOSTS` | Trusted host middleware allow-list |
| `REDIS_URL` | Redis URL for state, events, and broker |
| `CALLBACK_URL` | GitHub OAuth callback URL |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | Optional GitHub OAuth app credentials |
| `GITHUB_TOKEN` | Optional token for repository access/rate limits |
| `AI_MODEL` | LiteLLM model name, e.g. `gemini/gemini-1.5-flash` |
| `LITELLM_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY` | Provider credentials |
| `MAX_REPO_SIZE_MB`, `MAX_REPO_FILES` | Repository safety limits |
| `GENERATION_TTL_SECONDS`, `GENERATION_EVENT_MAX_LEN` | Redis state/event retention limits |

Never commit `.env` or provider secrets.

## API Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/health` | GET | Health check |
| `/api/session` | GET | Current GitHub session status |
| `/api/session/login` | GET | Start GitHub OAuth flow |
| `/api/session/callback` | GET | Complete GitHub OAuth flow |
| `/api/session/logout` | POST | Clear session |
| `/api/repositories/validate` | GET | Validate repository URL/access |
| `/api/generations` | POST | Start resume generation |
| `/api/generations/{generation_id}` | GET | Fetch generation status/result |
| `/api/generations/{generation_id}/events` | GET | Stream generation events with SSE |

## Resume Output

Generation results include:

- `project_title`
- `tech_stack`
- `bullet_points`
- `additional_notes`
- `future_plans`
- `potential_advancements`
- `interview_questions`

The frontend can copy the output as plain text or LaTeX.

## Verification

Useful commands:

```bash
uv run pytest -q
uv run ruff check src tests
npm --prefix frontend run test:run
npm --prefix frontend run build
docker compose config
docker build --target runtime -t gitresume-api:test .
docker build -t gitresume-frontend:test frontend
```

Equivalent Make targets are provided for common checks:

```bash
make test
make frontend-test
make frontend-build
make docker-config
make docker-build
```

## Repository Layout

```text
src/gitresume/              FastAPI app, API routes, services, workers, schemas
frontend/                   Vite React SPA and nginx container config
tests/                      Backend/service/deployment tests
Dockerfile                  uv-based backend/worker image
frontend/Dockerfile         Vite build + nginx static image
docker-compose.yml          api + worker + frontend + redis stack
.env.example                Self-hosting environment template
pyproject.toml / uv.lock    Backend package metadata and lockfile
```

## Security and Privacy

- Repositories are cloned into temporary worker directories for analysis.
- GitHub tokens are not sent through Taskiq payloads; worker token handoff uses Redis and one-time retrieval.
- Private clone operations use `GIT_ASKPASS` instead of embedding tokens in git command arguments.
- Docker build contexts ignore `.env`, local caches, virtualenvs, `.git`, and generated frontend artifacts.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please include tests for behavior changes and run the verification commands relevant to your change before opening a PR.

## License

This project is licensed under the [MIT License](LICENSE).
