# GitResume

![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111827)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

GitResume turns a GitHub repository into a resume-ready project narrative: project summaries, ATS-friendly bullet points, interview prep, and copyable plain-text or LaTeX snippets. The current app is a FastAPI + Vite dashboard platform with Redis-backed jobs, LiteLLM model selection, hosted/self-hosted modes, and BYOK controls.

- **Docs:** [Docs](/docs), [Overview](docs/overview.mdx), [Quickstart](docs/quickstart.mdx), [Hosted mode](docs/hosted.mdx), [Self-hosted mode](docs/self-hosted.mdx), [Dashboard](docs/dashboard.mdx), [BYOK](docs/byok.mdx), [Model catalog](docs/models.mdx), [OAuth providers](docs/oauth-providers.mdx), [Deployment](docs/deployment.mdx), [Security](docs/security.mdx)
- **Source:** [GitHub repository](https://github.com/WhoIsJayD/gitresume)
- **Configuration:** [.env.example](.env.example), [docker-compose.yml](docker-compose.yml)

## Rebuild story

GitResume started as a simpler repository-to-resume generator. The rebuild turns it into an operable dashboard: a FastAPI API in `src/gitresume`, a React 19/Vite frontend in `frontend`, a Redis-backed Taskiq worker path for long-running repository analysis, and a deployment shape that can run privately or as a hosted dashboard.

The goal of the migration is practical control. Operators can self-host with global settings and server-owned keys. Hosted deployments can require GitHub login before saved BYOK settings are managed. Users can still pass an ephemeral provider key for a single generation without storing it permanently.

## Product snapshot

| Capability | What ships now |
| --- | --- |
| Repository intelligence | Secure clone/checkout, Repomix packing, ranked context selection, tree-sitter analysis, dependency summaries, git-history signals, and gitingest fallback |
| Async generation | `POST /api/generations` enqueues Taskiq work; `/api/generations/{generation_id}/events` streams Server-Sent Events |
| Dashboard | App mode, GitHub session, model browser, generation form, result panel, progress timeline, default model, and saved provider-key metadata |
| AI providers | LiteLLM-compatible Gemini, OpenAI, Anthropic, Groq, and other API-key models exposed by the catalog |
| BYOK | Ephemeral per-generation `providerApiKey` plus opt-in encrypted saved keys with round-robin rotation |
| OAuth | GitHub login is implemented for sessions; OAuth model execution entries are visible but unavailable until execution is implemented |

## Hosted vs self-hosted feature matrix

| Area | Self-hosted (`APP_MODE=self_hosted`) | Hosted (`APP_MODE=hosted`) |
| --- | --- | --- |
| Default mode | Yes | No |
| Settings scope | Global dashboard settings | Per authenticated GitHub user |
| Saved BYOK access | Global when `ALLOW_SAVED_BYOK=true` and encryption is configured | Requires GitHub login and the same saved-BYOK configuration |
| Ephemeral BYOK | Supported per generation | Supported per generation |
| GitHub OAuth | Optional for private repository/user flows | Required for saved dashboard settings |
| Hosted URL | Your deployment URL | Deployment-specific; wire it to the same app and OAuth callback |

## Architecture

```text
frontend/ (Vite React dashboard)
    │  /api proxy in Vite dev server or nginx container
    ▼
src/gitresume/main.py (FastAPI API)
    │  sessions, model catalog, settings, generation enqueue, SSE
    ▼
Redis (generation state, events, one-time tokens, saved settings, Taskiq broker)
    │
    ▼
Taskiq worker (clone repo, analyze context, call LiteLLM, persist result)
```

## Dashboard

The dashboard is the primary UI. It links to `/docs` and the [GitHub repository](https://github.com/WhoIsJayD/gitresume), displays current app mode, loads GitHub session state, shows LiteLLM model catalog entries, manages settings, and starts generations.

Key API routes:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/session` | Current GitHub session and app mode |
| `GET /api/session/login?next=/dashboard` | Start GitHub OAuth login |
| `GET /api/models` | List text/chat/responses catalog entries |
| `GET /api/settings` | Read default model, saved-key metadata, and disabled status |
| `PUT /api/settings/default-model` | Save the default model when settings are enabled |
| `POST /api/settings/provider-keys` | Save encrypted provider key metadata and secret |
| `POST /api/generations` | Start a generation job |

Read more in [Dashboard](docs/dashboard.mdx).

## BYOK

GitResume supports two provider-key paths:

1. **Ephemeral BYOK:** send `providerApiKey` with a generation request. The API stores it one-time in Redis and the worker pops it for that job.
2. **Saved BYOK:** set `ALLOW_SAVED_BYOK=true` and `SETTINGS_ENCRYPTION_KEY` to allow encrypted saved provider keys. A Fernet key generated by `cryptography.fernet.Fernet.generate_key()` is preferred; long passphrases are supported as a compatibility fallback.

Saved key metadata is returned to the dashboard. Secrets are encrypted at rest and never returned in settings responses, SSE events, generation state, or retry state. Multiple compatible saved keys rotate round-robin per provider/model through Redis.

Read more in [BYOK](docs/byok.mdx).

## Model catalog

`GET /api/models` exposes LiteLLM text-capable entries with provider, mode, display name, auth type, availability, status, and context-window metadata when available. Available chat models can be selected in the dashboard.

OAuth/responses entries such as GitHub Copilot and ChatGPT Codex are intentionally visible with status text, but they are unavailable until OAuth model execution and Responses API execution are implemented. The dashboard should not present them as selectable generation models.

Read more in [Model catalog](docs/models.mdx) and [OAuth providers](docs/oauth-providers.mdx).

## Quick start

### Docker Compose

```bash
cp .env.example .env
```

Set these values before starting Compose. `SESSION_SECRET_KEY` must be a long non-placeholder value because `.env.example` uses `ENVIRONMENT=production`, and production startup rejects placeholder or short session secrets.

```env
SESSION_SECRET_KEY=replace-with-a-long-random-secret
AI_MODEL=gemini/gemini-1.5-flash
GEMINI_API_KEY=<provider key>
```

Then start the stack:

```bash
docker compose up --build
```

Open `http://localhost:5173`. The API health endpoint is `http://localhost:8080/api/health`.

### Local development

```bash
docker run --rm -p 6379:6379 redis:7-alpine
uv sync
cp .env.example .env
python -c "from pathlib import Path; p=Path('.env'); s=p.read_text(); s=s.replace('ENVIRONMENT=production','ENVIRONMENT=development'); s=s.replace('REDIS_URL=redis://redis:6379/0','REDIS_URL=redis://localhost:6379/0'); p.write_text(s)"
uv run uvicorn gitresume.main:app --host 0.0.0.0 --port 8080 --reload
```

Run the worker in a second terminal:

```bash
uv run taskiq worker gitresume.workers.broker:broker gitresume.workers.generation_tasks
```

Run the frontend in a third terminal:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

For the full setup path, see [Quickstart](docs/quickstart.mdx).

## Configuration

Copy [.env.example](.env.example) to `.env`. Important settings include:

| Variable | Purpose |
| --- | --- |
| `APP_MODE` | `self_hosted` or `hosted`; defaults to `self_hosted` |
| `SESSION_SECRET_KEY` | Required session signing secret; use a long random value outside local tests |
| `SESSION_COOKIE_HTTPS_ONLY` | Optional override; production defaults to HTTPS-only when unset |
| `SESSION_COOKIE_SAME_SITE` | Session cookie SameSite mode: `lax`, `strict`, or `none` |
| `SESSION_COOKIE_MAX_AGE_SECONDS` | Session lifetime in seconds |
| `REDIS_URL` | Redis URL for state, events, token handoff, saved settings, and broker |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `CALLBACK_URL` | GitHub OAuth session login |
| `GITHUB_TOKEN` | Optional server token for repository access/rate limits |
| `ALLOW_SAVED_BYOK` | Enables encrypted saved provider keys when true |
| `SETTINGS_ENCRYPTION_KEY` | Fernet key or long passphrase used to encrypt saved BYOK secrets |
| `AI_MODEL` | Default LiteLLM model |
| `LITELLM_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY` | Provider credentials |

Never commit `.env` or provider secrets.

## Deployment

The production-like local stack is [docker-compose.yml](docker-compose.yml): API, worker, frontend, and Redis. The backend image uses uv and includes runtime tools needed by repository analysis. The frontend image builds Vite output and serves it through nginx with API/SSE proxy settings.

Read more in [Deployment](docs/deployment.mdx).

## Verification

Useful checks for this repository:

```bash
uv run pytest -q
uv run ruff check src tests
npm --prefix frontend run test:run
npm --prefix frontend run build
docker compose config
docker build --target runtime -t gitresume-api:test .
docker build -t gitresume-frontend:test frontend
```

Equivalent Make targets exist for common checks:

```bash
make test
make frontend-test
make frontend-build
make docker-config
make docker-build
```

## Repository layout

```text
src/gitresume/              FastAPI app, API routes, services, workers, schemas
frontend/                   Vite React dashboard and nginx container config
docs/                       Mintlify MDX documentation pages
tests/                      Backend/service/deployment tests
Dockerfile                  uv-based backend/worker image
frontend/Dockerfile         Vite build + nginx static image
docker-compose.yml          api + worker + frontend + redis stack
.env.example                Runtime configuration template
pyproject.toml / uv.lock    Backend package metadata and lockfile
```

## Security and privacy

- Repositories are cloned into temporary worker directories for analysis.
- GitHub tokens are not sent through Taskiq payloads; worker token handoff uses Redis and one-time retrieval.
- Ephemeral provider keys are stored one-time in Redis and popped by the worker.
- Saved provider-key secrets are encrypted at rest and never returned by API responses.
- Private clone operations use `GIT_ASKPASS` instead of embedding tokens in git command arguments.
- Worker failures use generic public messages and safe logging.
- Docker build contexts ignore `.env`, local caches, virtualenvs, `.git`, and generated frontend artifacts.

Read more in [Security](docs/security.mdx).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please include tests for behavior changes and run the verification commands relevant to your change before opening a PR.

## License

This project is licensed under the [MIT License](LICENSE).
