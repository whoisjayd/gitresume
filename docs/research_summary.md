# GitResume Migration Research Summary

This document outlines the best practices, dependency plans, and packaging strategies for the GitResume migration stack.

## 1. Stack Selection & Decisions

| Tool | Purpose | Why? |
|------|---------|------|
| **Typer + Rich** | CLI & Dashboard | Modern, type-safe CLI development with beautiful terminal rendering (tables, progress bars, panels). |
| **LiteLLM** | LLM Interface | Unified API for multiple providers (OpenAI, Anthropic, etc.) with built-in retries, caching, and Pydantic support. |
| **uv** | Project Management | Extremely fast (Rust-based) replacement for pip/poetry. Handles locking and environment sync efficiently. |
| **PyInstaller** | Packaging | Industry standard for creating standalone binaries for Windows, macOS, and Linux. |
| **FastAPI** | Artifact Viewer | Lightweight and fast for serving the read-only JSON/PDF resume artifacts. |

## 2. Dependency Plan

Recommended `pyproject.toml` structure using `uv` (as of Feb 2026, `uv >= 0.9.29`):

```toml
[project]
name = "gitresume"
version = "2.0.0"
description = "AI-powered resume generation from GitHub repositories"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12.0",
    "rich>=13.7.0",
    "litellm>=1.35.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.8.0",
    "instructor>=1.0.0",
    "python-dotenv>=1.0.1",
    "httpx>=0.27.0",
    "PyGithub>=1.59.0",
    "aiofiles>=23.2.0",
    "tree-sitter>=0.21.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pyinstaller>=6.14.0",
    "ruff>=0.4.0",
    "mypy>=1.9.0",
]

[tool.uv]
managed = true
package = true
```

## 3. Implementation Best Practices

### Typer + Rich Integration
- **Dashboard Layouts**: Use `rich.layout.Layout` for multi-pane terminal apps and `rich.panel.Panel` for grouping.
- **Live Updates**: Use `rich.live.Live` with a custom renderable to show real-time logs alongside a progress bar.
- **Error Handling**: Use `rich.traceback.install(show_locals=True)` at the entry point for beautiful, actionable tracebacks.

### LiteLLM Caching & Structured Outputs
- **Local Disk Caching**: For CLI usage without Redis, enable disk-based caching:
  ```python
  import litellm
  litellm.cache = litellm.Cache(type="disk") # Defaults to .cache/litellm
  ```
- **Structured Output**: Use the `response_format` with Pydantic v2 models or the `instructor` library for better validation and retries.

### FastAPI Artifact Viewer
- **High-Performance JSON**: Use `ORJSONResponse` for faster serialization of large resume artifacts.
- **Middleware**: Enable `GZipMiddleware` to compress large JSON/PDF responses for the viewer.
- **Static Assets**: Use `StaticFiles` to serve generated PDFs and ensures paths are resolved relative to `sys._MEIPASS` when bundled with PyInstaller.

### Real-time CLI Dashboards
- **Streaming Output**: Combine `LiteLLM` streaming with `rich.live.Live` to show the resume being generated in real-time within a `Panel`.
- **Status Indicators**: Use `rich.status.Status` for high-level state changes (e.g., "Cloning...", "Analyzing...") to keep the UI clean.

## 4. Packaging & Release Strategy

### uv + PyInstaller Bundle
1. Initialize environment: `uv sync`.
2. Build executable: `uv run pyinstaller --onefile --name gitresume src/main.py`.

### PyInstaller Hidden Imports for Stack
Standalone binaries for this stack often fail due to missing dynamic imports. Add these to your `.spec` file or command line:

**LiteLLM & AI:**
- `litellm`
- `litellm.llms`
- `instructor`
- `pydantic_core._pydantic_core`

**FastAPI & Uvicorn:**
- `uvicorn.logging`
- `uvicorn.loops`
- `uvicorn.loops.auto`
- `uvicorn.protocols`
- `uvicorn.protocols.http`
- `uvicorn.protocols.http.auto`
- `uvicorn.protocols.websockets`
- `uvicorn.protocols.websockets.auto`
- `uvicorn.lifespan`
- `uvicorn.lifespan.on`

### GitHub Actions Build Matrix & Signing
Automate the creation of signed and notarized binaries:

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest, macos-latest]
    include:
      - os: ubuntu-latest
        artifact_name: gitresume-linux
      - os: windows-latest
        artifact_name: gitresume-windows.exe
      - os: macos-latest
        artifact_name: gitresume-macos

steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v5
  - name: Build
    run: uv run pyinstaller --onefile src/main.py

  # macOS Signing & Notarization (Mandatory for distribution)
  - name: Sign & Notarize macOS
    if: matrix.os == 'macos-latest'
    uses: apple-actions/import-codesigning-certs@v2
    with:
      p12-file-base-64: ${{ secrets.MACOS_CERT_P12 }}
      p12-password: ${{ secrets.MACOS_CERT_PASSWORD }}

  # Windows Signing
  - name: Sign Windows Binary
    if: matrix.os == 'windows-latest'
    uses: skalinichev/signtool-code-signing@v1
    with:
      certificate: ${{ secrets.WINDOWS_CERT_BASE64 }}
      password: ${{ secrets.WINDOWS_CERT_PASSWORD }}
      cert-format: p12
```

## 5. Distribution Best Practices

### PyPI Publishing with uv
For publishing the package to PyPI, use `uv` with Trusted Publishers (OIDC) for maximum security:

1. Configure **Trusted Publishers** on PyPI.
2. Use the `pypa/gh-action-pypi-publish` action in GitHub Actions.
3. Build and publish in one go:
   ```bash
   uv build
   uv publish
   ```

### Standalone Binary Release
Attach the PyInstaller binaries created in the build matrix to GitHub Releases using `softprops/action-gh-release`.

## 6. Advanced LLM Features (LiteLLM + Instructor)

For high-reliability structured outputs, combine LiteLLM with the `instructor` library:

```python
import instructor
from litellm import completion
from pydantic import BaseModel

class ResumeSchema(BaseModel):
    name: str
    experience: list[str]
    skills: list[str]

client = instructor.from_litellm(completion)

def get_structured_resume(text: str):
    return client.chat.completions.create(
        model="gpt-4",
        response_model=ResumeSchema,
        messages=[{"role": "user", "content": text}]
    )
```

### CLI Configuration Management
Use `pydantic-settings` for robust, type-safe configuration that supports environment variables, `.env` files, and YAML/TOML config files.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    default_provider: str = "gemini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GITRESUME_",
        extra="ignore"
    )

settings = Settings()
```

### Tree-sitter Binary Distribution
Bundling `tree-sitter` requires including the compiled language grammars (`.so`, `.dll`, or `.dylib` files).

1. **Hidden Imports**: Ensure `tree_sitter_python`, `tree_sitter_javascript`, etc., are in `hiddenimports`.
2. **Data Files**: Use `collect_data_files` to include the shared libraries from the installed packages.
3. **Runtime Path**: At runtime, set the language library path using `sys._MEIPASS` if running from a PyInstaller bundle.

```python
import sys
from pathlib import Path

def get_resource_path(relative_path: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(".") / relative_path
```

## 6. References

- [Typer Documentation](https://typer.tiangolo.com/) - CLI best practices.
- [Rich Documentation](https://rich.readthedocs.io/) - Terminal formatting and layouts.
- [LiteLLM Documentation](https://docs.litellm.ai/) - LLM provider abstraction and caching.
- [uv Documentation](https://docs.astral.sh/uv/) - Modern Python project management.
- [PyInstaller Documentation](https://pyinstaller.org/en/stable/) - Executable bundling.
- [FastAPI Documentation](https://fastapi.tiangolo.com/) - Web API development.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
