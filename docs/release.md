# Release Process

This document outlines the steps to cut a new release for GitResume.

## 1. Versioning
We use [Semantic Versioning](https://semver.org/).
The version is maintained in `src/gitresume_core/version.py` and `pyproject.toml`.

## 2. Pre-release Checklist
- [ ] Run all tests: `pytest` (when implemented).
- [ ] Ensure `CHANGELOG.md` is updated (if applicable).
- [ ] Verify the CLI works: `gitresume doctor`.
- [ ] Build the package locally: `python -m build`.

## 3. Cutting a Release
1. **Update Version**: Bump the version in `src/gitresume_core/version.py`.
2. **Commit**: `git commit -am "chore: bump version to vX.Y.Z"`
3. **Tag**: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
4. **Push**: `git push origin main --tags`

## 4. CI/CD
The GitHub Action (when configured) will automatically:
- Build the wheel and source distribution.
- Publish to PyPI (future).
- Create a GitHub Release with the tag.

## 5. Artifacts
Release artifacts include:
- `gitresume-X.Y.Z-py3-none-any.whl`
- `gitresume-X.Y.Z.tar.gz`
