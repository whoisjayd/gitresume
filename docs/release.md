# 📦 Release Process

This document outlines the steps to cut a new release for GitResume.

## 1. Versioning
We use [Semantic Versioning](https://semver.org/).
The version is maintained in:
- `pyproject.toml`
- `src/gitresume_core/version.py`

## 2. Pre-release Checklist
- [ ] Run all tests: `uv run pytest`
- [ ] Run linting & formatting: `uv run make check`
- [ ] Verify the CLI works: `uv run gitresume --help`
- [ ] Ensure `CHANGELOG.md` is updated (if applicable).

## 3. Cutting a Release
1. **Update Version**: Bump the version in `pyproject.toml` and `src/gitresume_core/version.py`.
2. **Commit**: `git commit -am "chore: bump version to vX.Y.Z"`
3. **Tag**: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
4. **Push**: `git push origin main --tags`

## 4. CI/CD & Publishing
The GitHub Action (`build.yml`) will automatically:
- Run tests across OS platforms.
- Build the wheel and source distribution using `uv build`.
- Build platform-specific binaries using PyInstaller.
- Create a GitHub Release and upload artifacts if a tag is pushed.

## 5. Manual PyPI Publishing (If needed)
To publish manually to PyPI:
```bash
uv build
uv publish
```
