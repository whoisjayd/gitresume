# GitResume Migration Notes

## Current Architecture
The current application is a **FastAPI-based web application** designed for generating resumes from GitHub repositories.

### Key Components:
- **Web Layer (`app.py`)**: Handles HTTP requests, OAuth2 authentication with GitHub, session management via Redis, and WebSocket-based streaming for real-time progress updates.
- **State Management**: Uses **Redis** for session storage, analytics counters, and rate limiting.
- **Git Operations (`tools/git_operations.py`)**: Handles cloning repositories using `git clone --depth 1` and sparse-checkout patterns.
- **Ingestion (`tools/gitingest.py`)**: Analyzes the repository structure and content. It uses **Tree-sitter** for structural code analysis (extracting metrics like function and class counts).
- **LLM Orchestration (`tools/api_utils.py`)**: A robust, custom-built multi-provider client factory supporting Gemini, OpenAI, Groq, and Anthropic with automatic retries and rate-limit management.
- **Resume Generation (`tools/create_resume.py`)**: Orchestrates the prompt construction, LLM call, and JSON parsing.
- **Refinement (`tools/grammar_check.py`)**: Uses low-cost LLM models to correct grammar and style in the generated content.

### Execution Flow:
1. User provides a GitHub URL.
2. (Optional) OAuth authentication if the repo is private.
3. Repository is cloned to a temporary directory.
4. `gitingest` analyzes the code and produces a summary + file content map.
5. `create_resume` sends the analysis to an LLM.
6. `grammar_check` refines the output.
7. Result is displayed via Jinja2 templates.

---

## Deletion List
The following components are **out of scope** for the CLI-first, artifact-driven architecture and should be removed or deprecated:
- **OAuth Logic**: GitHub OAuth flow, callback handling, and `starlette.middleware.sessions`.
- **Redis Dependency**: Session storage, analytics tracking (`increment_analytics_counter`), and Redis-backed rate limiting.
- **WebSocket Streaming**: The current WebSocket implementation in `app.py`. CLI progress will use `rich` or `tqdm`.
- **Web Middleware**: `Analytics`, `TrustedHostMiddleware`, `GZipMiddleware`, and Cloudflare-specific logic.
- **HTML Templates**: Most Jinja2 templates (except those potentially used for generating "read-only" views).

---

## Reuse Plan
The core logic will be moved to a structured `src/` directory.

| Current File | New Location (Proposed) | Notes |
|--------------|-------------------------|-------|
| `tools/git_operations.py` | `src/gitresume/core/git.py` | Keep cloning logic; remove web-specific logging. |
| `tools/gitingest.py` | `src/gitresume/core/ingest.py` | Keep tree-sitter logic; refine file filtering. |
| `tools/api_utils.py` | `src/gitresume/core/llm/client.py` | **Crucial asset.** Keep the multi-provider logic. |
| `tools/create_resume.py` | `src/gitresume/core/llm/generator.py`| Extract prompt to a dedicated template file. |
| `tools/grammar_check.py` | `src/gitresume/core/llm/refiner.py` | Keep for final polish step. |
| `tools/utils.py` | `src/gitresume/utils/files.py` | Keep `robust_rmtree`. |

### New CLI Architecture:
- **Framework**: `Typer` for command handling.
- **Output**: All results (raw analysis, LLM response, refined resume) saved to `artifacts/{repo_name}/{timestamp}/`.
- **Config**: Use `pyproject.toml` or `~/.config/gitresume/config.yaml` for API keys instead of strictly `.env`.

---

## Risks & Hidden Complexity
1. **Tree-sitter Dependencies**: The project relies on multiple `tree-sitter-*` packages. Ensuring these compile/install correctly across all environments for the CLI is a priority.
2. **Context Window Management**: Currently, `create_resume.py` has hardcoded truncation (`30,000` chars). This needs to be more dynamic or configurable in the CLI.
3. **Artifact Serialization**: We need to ensure that the internal data structures (especially from `gitingest`) are fully JSON-serializable to be saved as artifacts.
4. **Environment Variables**: The current logic relies heavily on specific environment variable names (e.g., `GEMINI_API_KEYS`). The migration should allow for cleaner configuration.
5. **Windows Pathing**: The codebase contains several Windows-specific fixes (e.g., `WindowsProactorEventLoopPolicy`). These must be preserved in the CLI for cross-platform support.
