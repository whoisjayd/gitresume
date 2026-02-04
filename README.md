# 🚀 GitResume

*Transform your GitHub repositories into professional, ATS-optimized resumes using AI.*

GitResume is a CLI tool that analyzes your local or remote repositories, extracts technical achievements, and generates impactful resume bullet points, tech stack summaries, and interview preparation materials.

<div align="center">

[![PyPI version](https://img.shields.io/pypi/v/gitresume.svg)](https://pypi.org/project/gitresume/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://choosealicense.com/licenses/mit/)
[![Build Status](https://github.com/whoisjayd/gitresume/actions/workflows/build.yml/badge.svg)](https://github.com/whoisjayd/gitresume/actions/workflows/build.yml)
[![Docker Image Version](https://img.shields.io/docker/v/whoisjayd/gitresume?label=docker)](https://hub.docker.com/r/whoisjayd/gitresume)
[![GitHub Issues](https://img.shields.io/github/issues/whoisjayd/gitresume)](https://github.com/whoisjayd/gitresume/issues)

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

Choose your preferred installation method:

#### 1. Via `uv` (Recommended)
```bash
uv tool install gitresume
```

#### 2. Via `pip`
```bash
pip install gitresume
```

#### 3. Via Docker
```bash
docker pull whoisjayd/gitresume
```

---

## 📖 Usage

### 1. Analyze a Repository
Point GitResume at any local folder or clone a remote repo to create an analysis artifact.

```bash
# Local
gitresume analyze ./my-awesome-project

# Docker
docker run -v $(pwd):/app/data -e GEMINI_API_KEY=$GEMINI_API_KEY whoisjayd/gitresume analyze /app/data/my-project
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

GitResume uses environment variables for API keys. You can set them in your shell or use an `.env` or `env.yaml` file.

See the [Configuration Guide](docs/configuration.md) for a full list of environment variables.

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Required for Gemini models (Default) |
| `OPENAI_API_KEY` | Required for OpenAI models |
| `ANTHROPIC_API_KEY`| Required for Claude models |
| `GITRESUME_MODEL`| Model string (e.g., `gemini/gemini-1.5-flash`) |

---

## 🏗 CLI Reference

For detailed command usage, see the [CLI Reference](docs/installation.md#cli-reference).

---

## 📄 Documentation

- [Installation & Setup](docs/installation.md)
- [Configuration Guide](docs/configuration.md)
- [Security & Data Handling](docs/security.md)
- [Release Process](docs/release.md)

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
Created with ❤ by [Jaydeep Solanki](https://github.com/whoisjayd).
