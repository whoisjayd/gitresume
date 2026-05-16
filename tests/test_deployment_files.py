import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOC_PAGES = (
    "docs/overview.mdx",
    "docs/quickstart.mdx",
    "docs/hosted.mdx",
    "docs/self-hosted.mdx",
    "docs/dashboard.mdx",
    "docs/byok.mdx",
    "docs/models.mdx",
    "docs/oauth-providers.mdx",
    "docs/deployment.mdx",
    "docs/security.mdx",
)


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
    assert "litellm-oauth-tokens:" in compose
    assert "/home/appuser/.config/litellm" in compose
    assert "curl -fsS http://localhost:8080/api/health" in compose
    assert "healthcheck:\n      disable: true" in compose
    assert "wget -qO- http://127.0.0.1/health" in compose
    assert "redis-cli" in compose
    assert "ping" in compose


def test_frontend_container_serves_vite_dist_and_proxies_api_with_sse_settings() -> None:
    dockerfile = read_text("frontend/Dockerfile")
    dockerignore = read_text("frontend/.dockerignore")
    nginx = read_text("frontend/nginx.conf")

    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=builder /app/dist" in dockerfile
    assert "wget -qO- http://127.0.0.1/health" in dockerfile
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
        "APP_MODE=self_hosted",
        "REDIS_URL=redis://redis:6379/0",
        "SESSION_SECRET_KEY=change-me",
        "SESSION_COOKIE_HTTPS_ONLY=",
        "SESSION_COOKIE_SAME_SITE=lax",
        "SESSION_COOKIE_MAX_AGE_SECONDS=1209600",
        "FRONTEND_ORIGIN=http://localhost:5173",
        "ALLOWED_HOSTS=localhost,127.0.0.1,api",
        "GITHUB_CLIENT_ID=",
        "GITHUB_CLIENT_SECRET=",
        "GITHUB_TOKEN=",
        "ALLOW_SAVED_BYOK=false",
        "SETTINGS_ENCRYPTION_KEY=",
        "LITELLM_API_KEY=",
        "OPENAI_API_KEY=",
        "ANTHROPIC_API_KEY=",
        "GEMINI_API_KEY=",
        "GROQ_API_KEY=",
        "OPENROUTER_API_KEY=",
    ):
        assert key in env_example

    for empty_secret in (
        "GITHUB_CLIENT_ID=",
        "GITHUB_CLIENT_SECRET=",
        "GITHUB_TOKEN=",
        "SETTINGS_ENCRYPTION_KEY=",
        "LITELLM_API_KEY=",
        "OPENAI_API_KEY=",
        "ANTHROPIC_API_KEY=",
        "GEMINI_API_KEY=",
        "GROQ_API_KEY=",
        "OPENROUTER_API_KEY=",
    ):
        assert empty_secret in env_example
    for accidental_secret_marker in ("sk-", "ghp_", "github_pat_", "xoxb-"):
        assert accidental_secret_marker not in env_example


def test_mintlify_docs_config_references_required_pages() -> None:
    docs_json_path = ROOT / "docs" / "docs.json"
    assert docs_json_path.exists()

    docs_config = json.loads(docs_json_path.read_text(encoding="utf-8"))
    serialized_config = json.dumps(docs_config)
    for page in DOC_PAGES:
        assert page.removeprefix("docs/") in serialized_config


def test_mintlify_docs_pages_exist() -> None:
    for page in DOC_PAGES:
        assert (ROOT / page).is_file()


def test_readme_tells_hosted_dashboard_byok_model_story_with_internal_links() -> None:
    readme = read_text("README.md")

    assert re.search(r"!\[[^\]]+\]\(https://img\.shields\.io/", readme)
    for heading in (
        "## Rebuild story",
        "## Hosted vs self-hosted feature matrix",
        "## Dashboard",
        "## BYOK",
        "## Model catalog",
    ):
        assert heading in readme

    for link in (
        "[Docs](/docs)",
        "[GitHub repository](https://github.com/WhoIsJayD/gitresume)",
        "[.env.example](.env.example)",
        "[docker-compose.yml](docker-compose.yml)",
        "[Overview](docs/overview.mdx)",
        "[Quickstart](docs/quickstart.mdx)",
        "[Hosted mode](docs/hosted.mdx)",
        "[Self-hosted mode](docs/self-hosted.mdx)",
        "[Dashboard](docs/dashboard.mdx)",
        "[BYOK](docs/byok.mdx)",
        "[Model catalog](docs/models.mdx)",
        "[OAuth providers](docs/oauth-providers.mdx)",
        "[Deployment](docs/deployment.mdx)",
        "[Security](docs/security.mdx)",
    ):
        assert link in readme

    for relative_link in re.findall(r"\[[^\]]+\]\((?!https?://|#|/)([^)]+)\)", readme):
        target = relative_link.split("#", 1)[0]
        assert (ROOT / target).exists(), f"README link target does not exist: {target}"


def test_readme_docker_quickstart_sets_required_secret_before_compose() -> None:
    readme = read_text("README.md")

    copy_index = readme.index("cp .env.example .env")
    secret_index = readme.index("SESSION_SECRET_KEY=replace-with-a-long-random-secret")
    compose_index = readme.index("docker compose up --build")

    assert copy_index < secret_index < compose_index
    assert "long non-placeholder" in readme
    assert "before starting Compose" in readme


def test_local_development_docs_avoid_production_placeholder_secret_startup() -> None:
    readme = read_text("README.md")
    quickstart = read_text("docs/quickstart.mdx")
    contributing = read_text("CONTRIBUTING.md")

    for content, heading in (
        (readme, "### Local development"),
        (quickstart, "## Local development"),
        (contributing, "## Development Setup"),
    ):
        assert heading in content
        local_dev_section = content.split(heading, maxsplit=1)[1]
        assert "ENVIRONMENT=development" in local_dev_section
        assert "REDIS_URL=redis://localhost:6379/0" in local_dev_section
        assert local_dev_section.index("ENVIRONMENT=development") < local_dev_section.index(
            "uv run uvicorn"
        )


def test_operator_docs_include_generation_validation_and_analysis_examples() -> None:
    readme = read_text("README.md")
    dashboard = read_text("docs/dashboard.mdx")
    security = read_text("docs/security.mdx")

    examples = readme + dashboard
    for token in (
        "curl -G http://localhost:8080/api/repositories/validate",
        "curl -X POST http://localhost:8080/api/repositories/validate",
        '"repoUrl": "https://github.com/WhoIsJayD/gitresume"',
        '"githubToken": "<github token>"',
        "GitHub tokens must be sent in the POST body",
        "curl -X POST http://localhost:8080/api/generations",
        '"providerApiKey": "<ephemeral provider key>"',
        '"providerKeyId": "<saved-key-id>"',
        '"analysisAuthor": "octocat"',
        '"analysisDays": 180',
    ):
        assert token in examples

    for token in (
        "classifying-packing",
        "guided-evidence-investigation",
        "RepositoryIngestionService",
        "RepositoryInvestigationService",
        "ContributionAnalysisService",
        "Only make claims supported by files touched by the requested author",
    ):
        assert token in security


def test_operator_docs_include_byok_oauth_openrouter_and_hosted_examples() -> None:
    byok = read_text("docs/byok.mdx")
    models = read_text("docs/models.mdx")
    oauth = read_text("docs/oauth-providers.mdx")
    hosted = read_text("docs/hosted.mdx")
    deployment = read_text("docs/deployment.mdx")

    for token in (
        "RedisProviderKeySelector",
        "round-robin",
        "providerKeyId",
        "model-restricted key",
    ):
        assert token in byok

    for token in (
        "openrouter/meta-llama/llama-3.1-8b-instruct:free",
        "OPENROUTER_API_KEY",
        "providerApiKey",
        "providerKeyId",
    ):
        assert token in models

    for token in (
        "POST /api/oauth-providers/github_copilot/connect",
        "accessToken",
        "refreshToken",
        "expiresAt",
        "accountLabel",
        "browser device-code flow is still not claimed",
    ):
        assert token in oauth

    hosted_deployment = hosted + deployment
    for token in (
        "APP_MODE=hosted",
        "ENVIRONMENT=production",
        "FRONTEND_ORIGIN=https://gitresume.example.com",
        "CALLBACK_URL=https://gitresume.example.com/api/session/callback",
        "SESSION_COOKIE_HTTPS_ONLY=true",
        "ALLOWED_HOSTS=gitresume.example.com",
    ):
        assert token in hosted_deployment


def test_docs_describe_current_byok_hosted_and_oauth_model_constraints() -> None:
    byok = read_text("docs/byok.mdx")
    hosted = read_text("docs/hosted.mdx")
    models = read_text("docs/models.mdx")
    oauth = read_text("docs/oauth-providers.mdx")

    for token in ("ALLOW_SAVED_BYOK=true", "SETTINGS_ENCRYPTION_KEY"):
        assert token in byok
    assert "`POST /api/generations`" in byok
    assert "`providerApiKey`" in byok
    assert "ephemeral BYOK" in byok
    assert "per generation" in byok

    assert "hosted saved keys require GitHub login" in hosted
    assert "`GET /api/settings`" in hosted
    assert "loginRequired" in hosted

    for content in (models, oauth):
        assert "GitHub Copilot" in content
        assert "ChatGPT Codex" in content
        assert "manual" in content
        assert "device-code" in content
    assert "OpenRouter" in models
    assert ":free" in models
    assert "becomes selectable only when" in models
    assert "become selectable only when" in oauth
