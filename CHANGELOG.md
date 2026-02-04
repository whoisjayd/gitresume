# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.2] - 2026-02-04

### Changed
- Binaries are now distributed as `.tar.gz` (Linux/macOS) and `.zip` (Windows) archives.
- Fixed executable permissions in distributed binaries.
- Binaries inside archives are named `gitresume` (no OS suffix).

## [0.1.0] - 2025-02-04

### Added
- Initial Open Source Release.
- CLI tool for repository analysis and resume generation.
- Support for multiple LLMs via LiteLLM (Gemini, OpenAI, Anthropic, Groq).
- Local web dashboard for viewing artifacts and resumes.
- Docker support for containerized execution.
- Tree-sitter integration for deep code analysis.
- Redaction patterns for security-first local processing.
- Professional documentation suite (Installation, Configuration, Security).
