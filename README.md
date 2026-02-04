# 🚀 GitResume

*Transform your GitHub repositories into professional, ATS-optimized resumes using AI.*

GitResume is a CLI tool that analyzes your local or remote repositories, extracts technical achievements, and generates impactful resume bullet points, tech stack summaries, and interview preparation materials.

<div align="center">
  <img src="https://raw.githubusercontent.com/WhoIsJayD/gitresume/main/docs/images/cli_demo.png" alt="GitResume CLI Demo" width="100%"/>
  <p><em>(Placeholder for Rich UI Screenshot)</em></p>
</div>

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://choosealicense.com/licenses/mit/)
[![GitHub Issues](https://img.shields.io/github/issues/whoisjayd/gitresume)](https://github.com/whoisjayd/gitresume/issues)
[![Contributions Welcome](https://img.shields.io/badge/Contributions-Welcome-brightgreen.svg)](https://github.com/whoisjayd/gitresume)

</div>

---

## ✨ Features

- **🔍 Deep Analysis**: Uses Tree-sitter to parse your code and understand the actual technical complexity.
- **🤖 Multi-LLM Support**: Integrates with Gemini, OpenAI, Anthropic, and Groq via LiteLLM.
- **📄 Multiple Formats**: Generates resumes in Markdown and structured JSON.
- **💻 Local-First**: No need to upload your code to a 3rd party service. Analysis happens on your machine.
- **📊 Web Dashboard**: View your generated resumes and analysis history in a beautiful local web interface.
- **🎯 Job Tailoring**: Provide a job description to generate targeted achievements.

---

## 🚀 Quick Start

### Installation

We recommend using [uv](https://github.com/astral-sh/uv) for the best experience:

```bash
# Install as a global tool
uv tool install gitresume

# Or via pip
pip install gitresume
```

### 1. Analyze a Repository
Point GitResume at any local folder or clone a remote repo to create an analysis artifact.

```bash
gitresume analyze ./my-awesome-project
```

### 2. Generate a Resume
Use the analysis to generate a polished resume. You can optionally provide a job description for better targeting.

```bash
gitresume generate ./artifacts/my-awesome-project-run-id --jd "Senior Backend Engineer at Google"
```

### 3. View in Dashboard
Start the local dashboard to browse your artifacts and view your resumes.

```bash
gitresume web
```

---

## 🔧 Configuration

GitResume uses environment variables for API keys. You can set them in your shell or use an `.env` or `env.yaml` file in your working directory.

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Required for Gemini models (Default) |
| `OPENAI_API_KEY` | Required for OpenAI models |
| `ANTHROPIC_API_KEY`| Required for Claude models |
| `GROQ_API_KEY` | Required for Groq models |

**Example `env.yaml`:**
```yaml
GEMINI_API_KEY: "your-key-here"
GITRESUME_MODEL: "gemini/gemini-1.5-flash"
```

---

## 🏗 CLI Reference

### `gitresume analyze [PATH]`
Analyzes the repository at the given path.
- `--output-dir, -o`: Where to save analysis artifacts (default: `artifacts`).

### `gitresume generate [PATH]`
Generates a resume from an analysis artifact or repo path.
- `--model`: Specific LLM model to use.
- `--jd`: Path to a job description text file or a raw string.
- `--prompt`: Custom prompt override for generation.

### `gitresume web`
Launches the local viewer dashboard.
- `--port, -p`: Port to run the dashboard on (default: `8000`).
- `--no-open`: Don't open the browser automatically.

---

## 📄 Documentation

- [Release Process](docs/release.md)
- [Security & Data Handling](docs/security.md)
- [Legacy Web App Note](docs/legacy_web.md)

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
Created with ❤ by [Jaydeep Solanki](https://github.com/whoisjayd).
