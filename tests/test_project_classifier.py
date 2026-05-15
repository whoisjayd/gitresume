from pathlib import Path

from gitresume.services.project_classifier import ProjectClassifier


def test_project_classifier_detects_fullstack_fastapi_vite_project(tmp_path: Path) -> None:
    (tmp_path / "src" / "gitresume").mkdir(parents=True)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "src" / "gitresume" / "main.py").write_text("from fastapi import FastAPI\n")
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi", "litellm"]\n')
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"@vitejs/plugin-react":"latest","react":"latest","vite":"latest"}}'
    )
    (tmp_path / "Dockerfile").write_text("FROM python\n")

    profile = ProjectClassifier(tmp_path).classify()

    assert profile.project_type == "fullstack-web-app"
    assert "python" in profile.languages
    assert "fastapi" in profile.frameworks
    assert "vite" in profile.frameworks
    assert "litellm" in profile.frameworks
    assert "src/gitresume/main.py" in profile.entrypoint_hints
    assert "src/**/*.py" in profile.relevant_globs


def test_project_classifier_supports_major_polyglot_languages(tmp_path: Path) -> None:
    files = {
        "main.go": "package main",
        "lib.rs": "fn main() {}",
        "App.java": "class App {}",
        "Program.cs": "class Program {}",
        "Main.kt": "fun main() {}",
        "index.php": "<?php echo 'hi';",
        "app.rb": "puts 'hi'",
        "schema.sql": "select 1;",
        "index.html": "<main></main>",
        "style.css": "main { display: block; }",
        "script.sh": "echo hi",
    }
    for relative_path, content in files.items():
        (tmp_path / relative_path).write_text(content, encoding="utf-8")

    profile = ProjectClassifier(tmp_path).classify()

    assert {
        "go",
        "rust",
        "java",
        "csharp",
        "kotlin",
        "php",
        "ruby",
        "sql",
        "html",
        "css",
        "shell",
    }.issubset(set(profile.languages))
    assert "**/*.go" in profile.relevant_globs
    assert "**/*.sql" in profile.relevant_globs
