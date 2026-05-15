import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import networkx as nx
import tiktoken
from gitingest import ingest_async
from tree_sitter_analyzer.api import analyze_file

from gitresume.services.analysis_tools import RepositoryAnalysisTools
from gitresume.services.context_ranking import RankedContextBuilder
from gitresume.services.project_classifier import ProjectClassifier, ProjectProfile


@dataclass(frozen=True)
class RepositoryDigest:
    summary: str
    tree: str
    content: str


class RepositoryIngestionService:
    """Build LLM-ready repository context from multiple analysis backends.

    Repomix is the preferred packer because it produces AI-oriented JSON/XML/Markdown,
    supports stdin-driven file selection, secret scanning, and compressed tree-sitter output.
    Gitingest remains as the Python-native fallback for environments without Node/npx.
    """

    repomix_package = "repomix@1.14.0"
    gitingest_exclude_patterns = {
        ".git/*",
        "node_modules/*",
        "dist/*",
        "build/*",
        "coverage/*",
        "htmlcov/*",
        ".venv/*",
        "venv/*",
        "__pycache__/*",
        "*.lock",
        "*.map",
        "*.min.js",
        "*.min.css",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "uv.lock",
    }

    async def build_context(self, repository_path: str | Path) -> dict[str, object]:
        repository_root = Path(repository_path)
        profile = ProjectClassifier(repository_path).classify()
        ranked_builder = RankedContextBuilder(repository_path, project_profile=profile)
        selected_paths = ranked_builder.selected_file_paths()
        file_analyses = await self.analyze_ranked_files(repository_path, selected_paths[:8])
        if shutil.which("npx"):
            try:
                packed = await self.pack_with_repomix(
                    repository_path, selected_paths=selected_paths
                )
                context = {
                    "strategy": "repomix",
                    "project_profile": profile,
                    "selected_files": selected_paths,
                    "file_analyses": file_analyses,
                    "context": packed,
                }
                return self._with_structured_evidence(
                    context, repository_root, profile, selected_paths, packed
                )
            except RuntimeError:
                pass

        ranked_context = ranked_builder.build_ranked_context()
        context = {
            "strategy": "ranked-files",
            "project_profile": profile,
            "selected_files": selected_paths,
            "file_analyses": file_analyses,
            "context": ranked_context,
        }
        return self._with_structured_evidence(
            context, repository_root, profile, selected_paths, ranked_context
        )

    async def digest_with_gitingest(
        self, repository_path: str | Path, *, selected_paths: list[str] | None = None
    ) -> RepositoryDigest:
        kwargs: dict[str, object] = {"exclude_patterns": set(self.gitingest_exclude_patterns)}
        if selected_paths:
            kwargs["include_patterns"] = set(selected_paths)
        summary, tree, content = await ingest_async(str(repository_path), **kwargs)
        return RepositoryDigest(summary=summary, tree=tree, content=content)

    async def analyze_structure(self, file_path: str | Path) -> dict[str, object]:
        try:
            return await asyncio.to_thread(
                analyze_file,
                file_path,
                include_elements=True,
                include_queries=True,
                include_complexity=True,
            )
        except TypeError:
            return await asyncio.to_thread(analyze_file, file_path, include_elements=True)

    async def analyze_ranked_files(
        self, repository_path: str | Path, selected_paths: list[str]
    ) -> list[dict[str, object]]:
        analyses = []
        root = Path(repository_path)
        for relative_path in selected_paths:
            try:
                result = await self.analyze_structure(root / relative_path)
            except Exception as error:
                result = {
                    "success": False,
                    "file_info": {"path": relative_path},
                    "error": str(error),
                }
            analyses.append(result)
        return analyses

    def classify_project(self, repository_path: str | Path) -> ProjectProfile:
        return ProjectClassifier(repository_path).classify()

    async def pack_with_repomix(
        self,
        repository_path: str | Path,
        *,
        style: str = "json",
        selected_paths: list[str] | None = None,
        mode: str = "selected-context",
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="gitresume-repomix-") as temporary_directory:
            output_path = Path(temporary_directory) / f"repomix-output.{style}"
            command = self._repomix_command(
                output_path, style=style, selected_paths=selected_paths, mode=mode
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=repository_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds
                )
            except TimeoutError as error:
                process.kill()
                await process.communicate()
                raise RuntimeError("Repomix timed out.") from error
            if process.returncode != 0:
                raise RuntimeError(stderr.decode(errors="replace") or "Repomix failed.")

            if style == "json":
                return json.loads(output_path.read_text(encoding="utf-8"))
            return {"output_path": str(output_path), "stdout": stdout.decode(errors="replace")}

    async def pack_repomix_metadata(
        self, repository_path: str | Path, *, style: str = "json"
    ) -> dict[str, object]:
        return await self.pack_with_repomix(repository_path, style=style, mode="metadata")

    async def pack_repomix_git_logs(
        self, repository_path: str | Path, *, style: str = "json"
    ) -> dict[str, object]:
        return await self.pack_with_repomix(repository_path, style=style, mode="git-log")

    def _repomix_command(
        self,
        output_path: Path,
        *,
        style: str = "json",
        selected_paths: list[str] | None = None,
        mode: str = "selected-context",
    ) -> list[str]:
        command = [
            "npx",
            "--yes",
            self.repomix_package,
            ".",
            "--compress",
            "--style",
            style,
            "--output",
            str(output_path),
            "--parsable-style",
            "--truncate-base64",
            "--output-show-line-numbers",
            "--include-full-directory-structure",
        ]
        if mode == "metadata":
            command.extend(["--no-files", "--token-count-tree", "--top-files-len", "20"])
        elif mode == "git-log":
            command.extend(["--include-logs", "--include-logs-count", "50"])
        if selected_paths:
            command.extend(["--include", ",".join(selected_paths)])
        return command

    def _with_structured_evidence(
        self,
        context: dict[str, object],
        repository_root: Path,
        profile: ProjectProfile,
        selected_paths: list[str],
        packed_context: object,
    ) -> dict[str, object]:
        inventory = self._inventory(repository_root, profile, selected_paths)
        dependency_graph = self._dependency_graph(repository_root, profile, selected_paths)
        git_history = self._git_history(repository_root)
        token_budget = self._token_budget(packed_context, selected_paths, repository_root)
        prompt_context = self._prompt_context(
            inventory=inventory,
            dependency_graph=dependency_graph,
            git_history=git_history,
            token_budget=token_budget,
            packed_context=packed_context,
            selected_paths=selected_paths,
        )
        context.update(
            {
                "inventory": inventory,
                "dependency_graph": dependency_graph,
                "git_history": git_history,
                "token_budget": token_budget,
                "prompt_context": prompt_context,
            }
        )
        return context

    def _inventory(
        self, repository_root: Path, profile: ProjectProfile, selected_paths: list[str]
    ) -> dict[str, object]:
        tools_files = RepositoryAnalysisTools(repository_root).glob("**/*", limit=100_000)
        return {
            "total_files": len(tools_files),
            "selected_file_count": len(selected_paths),
            "languages": profile.languages,
            "frameworks": profile.frameworks,
            "package_managers": profile.package_managers,
            "entrypoints": profile.entrypoint_hints,
        }

    def _dependency_graph(
        self, repository_root: Path, profile: ProjectProfile, selected_paths: list[str]
    ) -> dict[str, list[dict[str, object]]]:
        graph = nx.DiGraph()
        repository_node = "repository"
        graph.add_node(repository_node, type="repository", label=repository_root.name)

        manifest_dependencies = self._manifest_dependencies(repository_root)
        for manifest, dependencies in manifest_dependencies.items():
            graph.add_node(manifest, type="manifest", label=manifest)
            graph.add_edge(repository_node, manifest, relationship="declares")
            for dependency in sorted(dependencies):
                dependency_node = f"dependency:{dependency}"
                graph.add_node(dependency_node, type="dependency", label=dependency)
                graph.add_edge(manifest, dependency_node, relationship="depends_on")

        for framework in profile.frameworks:
            framework_node = f"framework:{framework}"
            graph.add_node(framework_node, type="framework", label=framework)
            graph.add_edge(repository_node, framework_node, relationship="uses_framework")

        for selected_path in selected_paths:
            file_node = f"file:{selected_path}"
            role = self._file_role(selected_path, profile)
            graph.add_node(file_node, type="file", label=selected_path, role=role)
            graph.add_edge(repository_node, file_node, relationship="selected_file")
            if selected_path in profile.entrypoint_hints:
                graph.add_edge(file_node, repository_node, relationship="entrypoint_for")

        return {
            "nodes": [
                {"id": node, **dict(attributes)} for node, attributes in graph.nodes(data=True)
            ],
            "edges": [
                {"source": source, "target": target, **dict(attributes)}
                for source, target, attributes in graph.edges(data=True)
            ],
        }

    def _manifest_dependencies(self, repository_root: Path) -> dict[str, set[str]]:
        dependencies: dict[str, set[str]] = {}
        pyproject = repository_root / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                project_dependencies = data.get("project", {}).get("dependencies", [])
                dependencies["pyproject.toml"] = {
                    str(item)
                    .split("[", 1)[0]
                    .split("=", 1)[0]
                    .split("<", 1)[0]
                    .split(">", 1)[0]
                    .strip()
                    for item in project_dependencies
                    if str(item).strip()
                }
            except (tomllib.TOMLDecodeError, OSError):
                dependencies["pyproject.toml"] = set()

        requirements = repository_root / "requirements.txt"
        if requirements.exists():
            dependencies["requirements.txt"] = {
                self._requirement_name(line)
                for line in requirements.read_text(encoding="utf-8", errors="ignore").splitlines()
                if self._requirement_name(line)
            }

        package_json = repository_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                package_dependencies = set(data.get("dependencies", {})) | set(
                    data.get("devDependencies", {})
                )
                dependencies["package.json"] = package_dependencies
            except (json.JSONDecodeError, OSError):
                dependencies["package.json"] = set()

        go_mod = repository_root / "go.mod"
        if go_mod.exists():
            dependencies["go.mod"] = self._go_dependencies(go_mod)
        return dependencies

    def _requirement_name(self, line: str) -> str:
        candidate = line.split("#", 1)[0].split(";", 1)[0].strip()
        if not candidate or candidate.startswith(("-", "http://", "https://")):
            return ""
        return re.split(r"\s*(?:===|==|~=|!=|<=|>=|<|>|@)\s*", candidate, maxsplit=1)[0].strip()

    def _go_dependencies(self, go_mod: Path) -> set[str]:
        dependencies: set[str] = set()
        in_require_block = False
        for raw_line in go_mod.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue
            if line == "require (":
                in_require_block = True
                continue
            if in_require_block and line == ")":
                in_require_block = False
                continue
            if line.startswith(("module ", "go ")):
                continue
            if line.startswith("require "):
                parts = line.split()
                if len(parts) >= 2:
                    dependencies.add(parts[1])
                continue
            if in_require_block:
                dependencies.add(line.split()[0])
        return dependencies

    def _file_role(self, relative_path: str, profile: ProjectProfile) -> str:
        path = Path(relative_path)
        name = path.name.lower()
        parts = {part.lower() for part in path.parts}
        if relative_path in profile.entrypoint_hints:
            return "entrypoint"
        if "test" in name or "tests" in parts:
            return "test"
        if name in {"dockerfile", "compose.yml", "docker-compose.yml"}:
            return "deployment"
        if parts & {"api", "routes", "controllers", "handlers"}:
            return "api"
        if parts & {"services", "workers", "jobs"}:
            return "service"
        if path.suffix.lower() in {".toml", ".json", ".yaml", ".yml"}:
            return "configuration"
        return "source"

    def _git_history(self, repository_root: Path) -> dict[str, list[dict[str, object]]]:
        if not (repository_root / ".git").exists():
            return {"recent_commits": [], "high_churn_files": []}
        recent_commits = self._run_git_log(repository_root)
        high_churn_files = self._run_git_churn(repository_root)
        return {"recent_commits": recent_commits, "high_churn_files": high_churn_files}

    def _run_git_log(self, repository_root: Path) -> list[dict[str, object]]:
        try:
            process = subprocess.run(
                ["git", "log", "-n", "10", "--pretty=format:%h%x09%ad%x09%s", "--date=short"],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if process.returncode != 0:
            return []
        commits = []
        for line in process.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
        return commits

    def _run_git_churn(self, repository_root: Path) -> list[dict[str, object]]:
        try:
            process = subprocess.run(
                ["git", "log", "--name-only", "--pretty=format:"],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if process.returncode != 0:
            return []
        counts = Counter(line.strip() for line in process.stdout.splitlines() if line.strip())
        return [{"path": path, "commits": commits} for path, commits in counts.most_common(20)]

    def _token_budget(
        self, packed_context: object, selected_paths: list[str], repository_root: Path
    ) -> dict[str, int]:
        prompt_context = self._json_safe(packed_context)
        encoding = tiktoken.get_encoding("cl100k_base")
        selected_file_tokens = 0
        for selected_path in selected_paths:
            try:
                content = (repository_root / selected_path).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                content = ""
            selected_file_tokens += len(encoding.encode(content))
        return {
            "prompt_context_tokens": len(encoding.encode(json.dumps(prompt_context, default=str))),
            "selected_file_context_tokens": selected_file_tokens,
        }

    def _prompt_context(
        self,
        *,
        inventory: dict[str, object],
        dependency_graph: dict[str, list[dict[str, object]]],
        git_history: dict[str, list[dict[str, object]]],
        token_budget: dict[str, int],
        packed_context: object,
        selected_paths: list[str],
    ) -> str:
        payload = {
            "inventory": inventory,
            "dependency_graph": dependency_graph,
            "git_history": git_history,
            "token_budget": token_budget,
            "selected_files": selected_paths,
            "packed_context": self._json_safe(packed_context),
        }
        return json.dumps(payload, default=str, ensure_ascii=False)

    def _json_safe(self, value: object) -> object:
        if isinstance(value, ProjectProfile):
            return asdict(value)
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [self._json_safe(item) for item in value]
        if isinstance(value, set):
            return sorted((self._json_safe(item) for item in value), key=str)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)


repository_ingestion_service = RepositoryIngestionService()
