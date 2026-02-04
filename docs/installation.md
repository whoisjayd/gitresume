# 📥 Installation Guide

GitResume can be installed in several ways depending on your environment and preference.

## 1. Using `uv` (Recommended)

[uv](https://github.com/astral-sh/uv) is an extremely fast Python package manager. It is the recommended way to install and run GitResume.

### Install as a global tool
```bash
uv tool install gitresume
```

### Run without installing
```bash
uvx gitresume analyze .
```

---

## 2. Using `pip`

You can install GitResume from PyPI using standard pip:

```bash
pip install gitresume
```

*Note: We recommend using a virtual environment.*

---

## 3. Using Docker

If you prefer not to install Python or dependencies locally, use our Docker image.

### Pull the image
```bash
docker pull whoisjayd/gitresume
```

### Run a command
You need to mount your project directory and pass your API key:

```bash
docker run -v $(pwd):/app/data \
  -e GEMINI_API_KEY=$GEMINI_API_KEY \
  whoisjayd/gitresume analyze /app/data
```

---

## 4. Download Binary (Coming Soon)

We provide pre-compiled binaries for Windows, macOS, and Linux on our [Releases page](https://github.com/whoisjayd/gitresume/releases).

1. Download the executable for your platform.
2. Rename it to `gitresume` (or `gitresume.exe` on Windows).
3. Move it to a directory in your `PATH`.

---

## 🛠 CLI Reference

### `gitresume analyze [PATH]`
Analyzes the repository at the given path.
- `PATH`: Local directory path (default: `.`).
- `--output-dir, -o`: Directory to store analysis artifacts (default: `artifacts`).
- `--include`: Glob patterns of files to include.
- `--exclude`: Glob patterns of files to exclude.

### `gitresume generate [PATH]`
Generates a resume from an analysis artifact or repo path.
- `PATH`: Path to a previous analysis artifact or a repository.
- `--model`: LLM model to use (overrides `GITRESUME_MODEL` env var).
- `--jd`: Path to a job description text file or a raw string.
- `--output, -o`: Output file path for the resume (default: `resume.md`).

### `gitresume web`
Launches the local viewer dashboard.
- `--port, -p`: Port to run the dashboard on (default: `8000`).
- `--no-open`: Prevents the browser from opening automatically.

### `gitresume bulk [INPUT_FILE]`
Processes multiple repositories in bulk.
- `INPUT_FILE`: Path to a file containing repository paths or URLs.
  - **.txt**: One path/URL per line.
  - **.json**: A JSON array of strings.
  - **.csv**: CSV where the first column contains the path/URL.
- `--mode, -m`: Processing mode, either `analyze` or `generate` (default: `analyze`).
- `--concurrency, -c`: Number of parallel tasks to run (default: `5`).
- `--output-dir, -o`: Directory to store analysis artifacts (default: `artifacts`).
- `--model`: LLM model to use (only for `generate` mode).
- `--jd`: Job description for tailoring (only for `generate` mode).
