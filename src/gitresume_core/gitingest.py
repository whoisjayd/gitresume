"""
Repository ingestion and analysis tool.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Set

import aiofiles

logger = logging.getLogger(__name__)


IGNORE_DIRS: Set[str] = {
    # Build outputs and temporary directories
    "build",
    "dist",
    "out",
    "target",
    "bin",
    "obj",
    "artifacts",
    "generated",
    "gen",
    "release",
    "debug",
    "_build",
    ".build",
    "tmp",
    "temp",
    "cache",
    ".cache",
    "var",
    "run",
    # Version control
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    "CVS",
    ".fossil-settings",
    # IDE and editor
    ".vscode",
    ".idea",
    ".eclipse",
    ".vs",
    ".vscode-test",
    ".fleet",
    ".ionide",
    ".project",
    ".settings",
    ".metadata",
    ".recommenders",
    # Python
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
    "venv",
    ".env",
    "env",
    ".virtualenv",
    "site-packages",
    ".eggs",
    "*.egg-info",
    ".pyenv",
    ".conda",
    "anaconda3",
    "miniconda3",
    ".ipynb_checkpoints",
    # Node.js / JavaScript / TypeScript
    "node_modules",
    ".npm",
    ".yarn",
    ".pnpm",
    "bower_components",
    ".next",
    ".nuxt",
    ".angular",
    ".storybook-static",
    "nyc_output",
    ".parcel-cache",
    "webpack_cache",
    ".turbo",
    ".rush",
    # Go
    "vendor",
    ".gocache",
    ".gopath",
    "go.work.sum",
    "testdata",
    "pkg",
    # C/C++
    "CMakeFiles",
    "build",
    "Debug",
    "Release",
    "x64",
    "x86",
    "vcpkg_installed",
    "_deps",
    ".conan",
    ".hunter",
    "out",
    "bin",
    "obj",
    # C# / .NET
    "bin",
    "obj",
    "packages",
    "TestResults",
    "BenchmarkDotNet.Artifacts",
    ".nuget",
    "publish",
    "wwwroot",
    ".azure",
    ".deployment",
    # Java / JVM
    "target",
    ".gradle",
    ".m2",
    ".ivy2",
    ".sbt",
    "project/target",
    "project/project",
    ".bloop",
    ".metals",
    ".ammonite",
    "lib_managed",
    "src_managed",
    ".ensime_cache",
    # Ruby
    ".bundle",
    "vendor/bundle",
    ".gem",
    ".rbenv",
    ".rvm",
    "gems",
    ".ruby-version",
    ".ruby-gemset",
    "tmp/cache",
    # PHP
    "vendor",
    ".phpunit.cache",
    ".php_cs.cache",
    ".psalm",
    ".phpstan",
    # Swift / iOS
    "DerivedData",
    ".build",
    "Pods",
    "Carthage",
    "*.xcworkspace",
    "*.xcodeproj/project.xcworkspace",
    "*.xcodeproj/xcuserdata",
    "fastlane/report.xml",
    "fastlane/Preview.html",
    "fastlane/screenshots",
    "fastlane/test_output",
    # Android
    ".gradle",
    "app/build",
    ".idea",
    "local.properties",
    "proguard",
    "captures",
    ".externalNativeBuild",
    ".cxx",
    # Flutter / Dart
    ".dart_tool",
    ".flutter-plugins",
    ".flutter-plugins-dependencies",
    ".packages",
    "pubspec.lock",
    # Rust
    "target",
    ".cargo",
    # Elixir / Erlang
    "_build",
    "deps",
    ".mix",
    "priv/static",
    # Clojure
    ".lein",
    ".nrepl-port",
    ".cpcache",
    "resources/public/js",
    # Haskell
    "dist",
    "dist-newstyle",
    ".stack-work",
    ".cabal-sandbox",
    # OCaml
    "_build",
    "_opam",
    ".merlin",
    # F#
    "bin",
    "obj",
    "paket-files",
    # R
    ".Rproj.user",
    ".RData",
    ".Rhistory",
    "packrat",
    "renv",
    # MATLAB
    "*.asv",
    "*.mex*",
    "*.slx.autosave",
    "*.slxc",
    # Perl
    "blib",
    "Build",
    "MYMETA.*",
    "pm_to_blib",
    # Lua
    "luarocks",
    ".luarocks",
    # Julia
    ".julia",
    # Nim
    "nimcache",
    "htmldocs",
    # Zig
    "zig-cache",
    "zig-out",
    # Crystal
    ".crystal",
    ".shards",
    # D
    ".dub",
    # Scala
    ".bsp",
    ".metals",
    ".bloop",
    # Kotlin
    ".kotlin",
    # Documentation
    "docs",
    "_site",
    ".jekyll-cache",
    ".docusaurus",
    "site",
    "_book",
    "doc",
    "api-docs",
    # Logs
    "logs",
    "log",
    # Testing
    "coverage",
    "htmlcov",
    "test-results",
    "test-reports",
    "test-output",
    "allure-results",
    "allure-report",
    # Deployment / Cloud
    ".netlify",
    ".vercel",
    ".now",
    ".firebase",
    ".serverless",
    ".aws-sam",
    ".terraform",
    ".terragrunt-cache",
    ".pulumi",
    # Mobile
    ".expo",
    ".expo-shared",
    "ios/build",
    "android/build",
    # Game Development
    "Library",
    "Temp",
    "Obj",
    "Builds",
    "Logs",
    "MemoryCaptures",
    "UserSettings",
    # Containerization
    ".docker",
    ".podman",
    # Package managers
    ".composer",
    ".pip",
    ".poetry",
    ".pipenv",
    # OS-specific
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".Spotlight-V100",
    ".Trashes",
    "ehthumbs.db",
    "ehthumbs_vista.db",
    ".AppleDouble",
    ".LSOverride",
    ".TemporaryItems",
    ".apdisk",
}

IGNORE_EXTENSIONS: Set[str] = {
    # Compiled / Binary
    ".pyc",
    ".pyo",
    ".pyd",  # Python
    ".class",
    ".jar",
    ".war",
    ".ear",  # Java
    ".o",
    ".obj",
    ".lib",
    ".a",
    ".so",
    ".dll",
    ".dylib",  # C/C++
    ".exe",
    ".bin",
    ".out",
    ".app",  # Executables
    ".beam",  # Erlang/Elixir
    ".rlib",
    ".rmeta",  # Rust
    ".wasm",  # WebAssembly
    ".bc",
    ".ll",  # LLVM
    ".dex",
    ".apk",
    ".aab",
    ".ipa",  # Mobile
    ".unity3d",
    ".unitypackage",  # Unity
    # Go-specific
    ".test",
    ".prof",
    ".sum",
    ".mod",  # Go modules and test outputs
    # Ruby-specific
    ".gem",
    ".gemspec",
    ".lock",  # Ruby gems and lockfiles
    # Configuration / Metadata
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    # .NET / C#
    ".pdb",
    ".suo",
    ".user",
    ".userprefs",
    ".pidb",
    ".booproj",
    ".nupkg",
    ".snupkg",
    # Databases
    ".db",
    ".sqlite",
    ".sqlite3",
    ".db3",
    ".s3db",
    ".sl3",
    ".mdb",
    ".accdb",
    ".frm",
    ".myd",
    ".myi",
    # Logs
    ".log",
    ".out",
    ".err",
    ".crash",
    ".dump",
    ".stackdump",
    ".mdmp",
    ".dmp",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".tgz",
    ".tbz2",
    ".txz",
    # Images
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".ico",
    ".svg",
    ".webp",
    ".heic",
    ".avif",
    # Videos
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".mkv",
    ".m4v",
    ".3gp",
    ".mpeg",
    # Audio
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".wma",
    ".m4a",
    ".opus",
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    # eBooks
    ".epub",
    ".mobi",
    ".azw",
    ".azw3",
    ".fb2",
    # Text files
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".nfo",
    ".diz",
    # Temporary files
    ".tmp",
    ".temp",
    ".bak",
    ".swp",
    ".swo",
    ".orig",
    ".crdownload",
    ".part",
    # OS-specific
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".fuse_hidden*",
    ".directory",
    ".Trash-*",
    # IDE / Editor files
    ".iml",
    ".classpath",
    ".buildpath",
    ".launch",
    ".prefs",
    ".pydevproject",
    ".cproject",
    # Cache files
    ".cache",
    ".pid",
    ".lock",
    ".lck",
    ".sem",
    ".dsym",
    ".dSYM",
    ".gch",
    ".pch",
    # Certificates / Security
    ".pem",
    ".key",
    ".crt",
    ".cer",
    ".p12",
    ".pfx",
    ".jks",
    ".gpg",
    ".pgp",
    # Font files
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    # Web-related
    ".map",
    ".min.js",
    ".min.css",
    ".bundle.js",
    ".bundle.css",
    ".manifest",
    # Mobile development
    ".appx",
    ".msix",
    ".appxbundle",
    ".msixbundle",
    # Game development
    ".unity",
    ".prefab",
    ".asset",
    ".meta",
    ".fbx",
    ".blend",
    ".obj",
    ".dae",
    # CAD files
    ".dwg",
    ".dxf",
    ".step",
    ".stp",
    ".iges",
    ".3dm",
    ".skp",
    # Virtualization
    ".vmdk",
    ".vdi",
    ".vhd",
    ".vhdx",
    ".qcow2",
    ".iso",
    ".dmg",
    # Scientific/Engineering
    ".mat",
    ".fig",
    ".slx",
    ".mdl",
    ".sim",
    ".vtk",
    ".stl",
    # Package files
    ".deb",
    ".rpm",
    ".pkg",
    ".msi",
    ".appimage",
    # Version control metadata
    ".gitkeep",
    ".gitmodules",
    ".gitattributes",
    # Profiling and debugging
    ".prof",
    ".profdata",
    ".gcov",
    ".gcda",
    ".gcno",
    # Linting and formatting
    ".eslintrc",
    ".prettierrc",
    ".stylelintrc",
    ".editorconfig",
    # Blockchain/Crypto
    ".sol",
    ".vyper",
    ".yul",
    # Infrastructure as Code
    ".tfstate",
    ".tfstate.backup",
    ".tfplan",
    ".tfvars",
}

MAX_FILES_TO_PROCESS: int = 5000
MAX_FILE_SIZE_BYTES: int = 1 * 1024 * 1024
TEXT_FILE_EXTENSIONS: Set[str] = {
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".gitignore",
    ".dockerignore",
    ".editorconfig",
}

# --- Tree-sitter Initialization ---
PARSER: Optional[Any] = None
LANGUAGE_MAP: Dict[str, Any] = {}
try:
    from tree_sitter import Language, Parser

    PARSER = Parser()

    language_loaders = {
        ".py": lambda: Language(__import__("tree_sitter_python").language(), "python"),
        ".js": lambda: Language(__import__("tree_sitter_javascript").language(), "javascript"),
        ".jsx": lambda: Language(__import__("tree_sitter_javascript").language(), "javascript"),
        ".go": lambda: Language(__import__("tree_sitter_go").language(), "go"),
        ".rs": lambda: Language(__import__("tree_sitter_rust").language(), "rust"),
        ".java": lambda: Language(__import__("tree_sitter_java").language(), "java"),
        ".c": lambda: Language(__import__("tree_sitter_c").language(), "c"),
        ".cpp": lambda: Language(__import__("tree_sitter_cpp").language(), "cpp"),
        ".h": lambda: Language(__import__("tree_sitter_c").language(), "c"),
        ".hpp": lambda: Language(__import__("tree_sitter_cpp").language(), "cpp"),
        ".cs": lambda: Language(__import__("tree_sitter_c_sharp").language(), "c_sharp"),
    }

    try:
        from tree_sitter_typescript import language_tsx, language_typescript

        language_loaders[".ts"] = lambda: Language(language_typescript(), "typescript")
        language_loaders[".tsx"] = lambda: Language(language_tsx(), "tsx")
    except (ImportError, AttributeError):
        logger.warning("tree-sitter-typescript not found or invalid. TypeScript analysis disabled.")

    for ext, loader in language_loaders.items():
        try:
            LANGUAGE_MAP[ext] = loader()
        except Exception as e:
            logger.warning(f"Could not load tree-sitter language for '{ext}'. Error: {e}")

    if not LANGUAGE_MAP:
        PARSER = None
    else:
        logger.info(f"Tree-sitter initialized for: {list(LANGUAGE_MAP.keys())}")

except ImportError:
    logger.warning("Tree-sitter library not found. Falling back to text-only analysis.")
except Exception as e:
    logger.error(f"An unexpected error during tree-sitter initialization: {e}")


def _extract_ast_metrics(tree: Any, lang: Any) -> Dict[str, Any]:
    """Extracts metrics like function and class counts using language-specific queries."""
    if not tree or not lang:
        return {}

    # Language-specific queries for code analysis
    queries = {
        "python": {
            "functions": "(function_definition) @f",
            "classes": "(class_definition) @c",
        },
        "javascript": {
            "functions": "[(function_declaration) (arrow_function) (method_definition)] @f",
            "classes": "(class_declaration) @c",
        },
        "go": {
            "functions": "(function_declaration) @f",
            "classes": "(type_spec name: (type_identifier)) @c",
        },
        "rust": {
            "functions": "(function_item) @f",
            "classes": "[(struct_item) (enum_item)] @c",
        },
        "java": {
            "functions": "(method_declaration) @f",
            "classes": "(class_declaration) @c",
        },
        "c": {
            "functions": "(function_definition) @f",
            "classes": "[(struct_specifier) (enum_specifier)] @c",
        },
        "cpp": {
            "functions": "(function_definition) @f",
            "classes": "[(class_specifier) (struct_specifier)] @c",
        },
        "c_sharp": {
            "functions": "(method_declaration) @f",
            "classes": "[(class_declaration) (struct_declaration)] @c",
        },
    }
    queries["typescript"] = queries["javascript"]
    queries["tsx"] = queries["javascript"]

    lang_name = lang.name
    lang_queries = queries.get(lang_name, {})

    def count_captures(query_str):
        if not query_str:
            return 0
        try:
            query = lang.query(query_str)
            return len(query.captures(tree.root_node))
        except Exception:
            return 0

    return {
        "functions": count_captures(lang_queries.get("functions")),
        "classes": count_captures(lang_queries.get("classes")),
    }


async def _process_file(file_path: Path, repo_root: Path) -> Optional[Dict[str, Any]]:
    try:

        def get_size():
            return file_path.stat().st_size

        file_size = await asyncio.to_thread(get_size)

        if file_size > MAX_FILE_SIZE_BYTES or (file_size == 0 and file_path.suffix.lower() not in TEXT_FILE_EXTENSIONS):
            return None

        rel_path_str = file_path.relative_to(repo_root).as_posix()
        file_info = {
            "path": rel_path_str,
            "size": file_size,
            "extension": file_path.suffix.lower(),
            "content_preview": "",
            "metrics": {},
        }

        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = await f.read()
        file_info["content_preview"] = content[:2000]

        if PARSER and file_info["extension"] in LANGUAGE_MAP:
            parser_lang = LANGUAGE_MAP[file_info["extension"]]

            def parse_sync():
                PARSER.set_language(parser_lang)
                return PARSER.parse(bytes(content, "utf8"))

            tree = await asyncio.to_thread(parse_sync)
            if tree and tree.root_node and not tree.root_node.has_error:
                file_info["metrics"] = _extract_ast_metrics(tree, parser_lang)

        return file_info
    except Exception as e:
        logger.warning(f"Error processing file '{file_path}': {e}")
        return None


async def gitingest_tool(repo_path: str) -> Dict[str, Any]:
    repo_root = Path(repo_path).resolve()
    if not (repo_root.exists() and repo_root.is_dir() and (repo_root / ".git").exists()):
        return {
            "success": False,
            "error": f"Path '{repo_path}' is not a valid Git repository.",
        }

    logger.info(f"Starting ingestion of repository: {repo_path}")
    tasks, file_paths_to_process, tree_structure = [], [], []

    file_count = 0
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        root_path = Path(root)
        rel_root = root_path.relative_to(repo_root).as_posix()
        if rel_root == ".":
            rel_root = ""
        tree_structure.append(f"{rel_root}/")

        for file_name in files:
            if file_count >= MAX_FILES_TO_PROCESS:
                break
            file_path = root_path / file_name
            if file_path.suffix.lower() in IGNORE_EXTENSIONS:
                continue
            file_paths_to_process.append(file_path)
            file_count += 1
        if file_count >= MAX_FILES_TO_PROCESS:
            break

    for file_path in file_paths_to_process:
        tasks.append(_process_file(file_path, repo_root))
    processed_files_info = await asyncio.gather(*tasks)

    summary = {
        "total_files_processed": 0,
        "total_size_bytes": 0,
        "file_types": {},
        "code_metrics": {"total_functions": 0, "total_classes": 0, "languages": {}},
    }
    all_content = {}
    for file_info in filter(None, processed_files_info):
        summary["total_files_processed"] += 1
        summary["total_size_bytes"] += file_info["size"]
        ext = file_info["extension"] or ".other"
        summary["file_types"][ext] = summary["file_types"].get(ext, 0) + 1
        all_content[file_info["path"]] = file_info["content_preview"]
        if file_info["metrics"]:
            metrics, lang_metrics = (
                file_info["metrics"],
                summary["code_metrics"]["languages"].setdefault(ext, {"files": 0, "functions": 0, "classes": 0}),
            )
            summary["code_metrics"]["total_functions"] += metrics.get("functions", 0)
            summary["code_metrics"]["total_classes"] += metrics.get("classes", 0)
            lang_metrics["files"] += 1
            lang_metrics["functions"] += metrics.get("functions", 0)
            lang_metrics["classes"] += metrics.get("classes", 0)

    if summary["total_files_processed"] == 0:
        return {"success": False, "error": "No processable files were found."}

    logger.info(f"Ingestion complete for '{repo_path}'. Processed {summary['total_files_processed']} files.")
    return {
        "success": True,
        "tree": "\n".join(sorted(tree_structure)),
        "summary": summary,
        "content": all_content,
    }
