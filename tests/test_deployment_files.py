from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_backend_dockerfile_uses_uv_src_entrypoint_and_worker_runtime_tools() -> None:
    dockerfile = read_text("Dockerfile")

    assert "ghcr.io/astral-sh/uv" in dockerfile
    assert "uv sync --frozen" in dockerfile
    assert "COPY pyproject.toml uv.lock" in dockerfile
    assert "COPY src ./src" in dockerfile
    assert "git" in dockerfile
    assert "node:24" in dockerfile
    assert "COPY --from=node-runtime /usr/local/ /usr/local/" in dockerfile
    assert "npm" in dockerfile
    assert "NPM_CONFIG_CACHE=/home/appuser/.npm" in dockerfile
    for token in ("uvicorn", "gitresume.main:app", "--host", "0.0.0.0", "--port", "8080"):
        assert token in dockerfile
    assert "app:app" not in dockerfile
    assert "requirements.txt" not in dockerfile


def test_compose_wires_api_worker_frontend_and_redis() -> None:
    compose = read_text("docker-compose.yml")

    for service in ("api:", "worker:", "frontend:", "redis:"):
        assert service in compose

    assert "REDIS_URL=redis://redis:6379/0" in compose
    assert (
        "taskiq worker gitresume.workers.broker:broker gitresume.workers.generation_tasks"
        in compose
    )
    assert "redis-data:" in compose
    assert "curl -fsS http://localhost:8080/api/health" in compose
    assert "redis-cli" in compose
    assert "ping" in compose


def test_frontend_container_serves_vite_dist_and_proxies_api_with_sse_settings() -> None:
    dockerfile = read_text("frontend/Dockerfile")
    dockerignore = read_text("frontend/.dockerignore")
    nginx = read_text("frontend/nginx.conf")

    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=builder /app/dist" in dockerfile
    assert "node_modules/" in dockerignore
    assert "dist/" in dockerignore
    assert "proxy_pass http://api:8080" in nginx
    assert "proxy_buffering off" in nginx
    assert "X-Accel-Buffering" in nginx
    assert "try_files $uri $uri/ /index.html" in nginx


def test_root_dockerignore_excludes_local_secrets_and_build_artifacts() -> None:
    dockerignore_lines = read_text(".dockerignore").splitlines()
    active_patterns = {
        line.strip()
        for line in dockerignore_lines
        if line.strip() and not line.lstrip().startswith("#")
    }

    for pattern in (
        ".git",
        ".beads/dolt",
        ".tmp",
        ".env",
        ".env.*",
        ".venv/",
        "frontend/node_modules/",
        "frontend/dist/",
    ):
        assert pattern in active_patterns

    assert "!.env.example" in active_patterns


def test_legacy_monolith_files_are_not_part_of_runtime_layout() -> None:
    for relative_path in (
        "app.py",
        "requirements.txt",
        "env.example.yaml",
        "templates",
        "static",
        "tools",
    ):
        assert not (ROOT / relative_path).exists()


def test_env_example_documents_self_hosted_runtime_settings_without_secret_values() -> None:
    env_example = read_text(".env.example")

    for key in (
        "ENVIRONMENT=production",
        "REDIS_URL=redis://redis:6379/0",
        "SESSION_SECRET_KEY=change-me",
        "FRONTEND_ORIGIN=http://localhost:5173",
        "ALLOWED_HOSTS=localhost,127.0.0.1,api",
        "GITHUB_CLIENT_ID=",
        "GITHUB_CLIENT_SECRET=",
        "GITHUB_TOKEN=",
        "LITELLM_API_KEY=",
        "OPENAI_API_KEY=",
        "ANTHROPIC_API_KEY=",
        "GEMINI_API_KEY=",
        "GROQ_API_KEY=",
    ):
        assert key in env_example

    assert "your_" not in env_example
