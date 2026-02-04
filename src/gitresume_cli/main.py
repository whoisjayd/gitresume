import typer

app = typer.Typer(
    help="GitResume CLI - Generate professional resumes from your GitHub repositories.",
    no_args_is_help=True,
)


@app.command()
def doctor():
    """Check if GitResume is configured correctly."""
    import os
    import shutil
    import sys
    from pathlib import Path

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    table = Table(show_header=False, box=None)

    def add_check(name, status, message=""):
        status_str = (
            "[bold green]Pass[/bold green]"
            if status == "pass"
            else "[bold red]Fail[/bold red]"
            if status == "fail"
            else "[bold yellow]Warn[/bold yellow]"
        )
        table.add_row(name, f"[{status_str}]", message)

    # 1. Python Version
    py_version = sys.version_info
    if py_version.major == 3 and py_version.minor >= 10:
        add_check("Python Version", "pass", f"{sys.version.split()[0]} >= 3.10")
    else:
        add_check("Python Version", "fail", f"{sys.version.split()[0]} < 3.10")

    # 2. Git
    git_path = shutil.which("git")
    if git_path:
        add_check("Git Installed", "pass", f"Found at {git_path}")
    else:
        add_check("Git Installed", "fail", "Git not found in PATH")

    # 3. LLM Keys
    keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    found_keys = [k for k in keys if os.environ.get(k)]
    if found_keys:
        add_check("LLM Keys", "pass", f"Found: {', '.join(found_keys)}")
    else:
        add_check("LLM Keys", "warn", "No LLM keys found (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY)")

    # 4. Artifacts Dir
    artifacts_dir = Path("artifacts")
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_file = artifacts_dir / ".doctor_test"
        test_file.touch()
        test_file.unlink()
        add_check("Artifacts Dir", "pass", f"'{artifacts_dir}' is writable")
    except Exception as e:
        add_check("Artifacts Dir", "fail", f"Cannot write to '{artifacts_dir}': {e}")

    console.print(Panel(table, title="[bold blue]GitResume Health Check[/bold blue]", expand=False))


@app.command()
def version():
    """Show the version of GitResume."""
    from gitresume_core.version import get_tool_version

    typer.echo(f"GitResume version: {get_tool_version()}")


@app.command()
def analyze(
    path: str = typer.Argument(".", help="Path to the Git repository to analyze."),
    output_dir: str = typer.Option("artifacts", "--output-dir", "-o", help="Directory to save artifacts."),
):
    """Analyze a Git repository and produce an artifact bundle."""
    import asyncio

    asyncio.run(_run_analysis(path, output_dir))


async def _run_analysis(path: str, output_dir: str):
    import logging
    from pathlib import Path

    from rich.console import Console
    from rich.table import Table

    from gitresume_core.artifacts import ArtifactManager
    from gitresume_core.gitingest import gitingest_tool
    from gitresume_core.logging_config import setup_logging

    console = Console()

    # 1. Initialize ArtifactManager
    manager = ArtifactManager(base_dir=output_dir)

    # 2. Setup Logging
    setup_logging(log_file=manager.get_log_file())
    logger = logging.getLogger("gitresume_cli")

    manager.initialize(inputs={"path": str(Path(path).resolve())})

    console.print(f"[bold blue]Analyzing repository at:[/bold blue] {path}")
    console.print(f"[bold blue]Run ID:[/bold blue] {manager.run_id}")

    # 3. Call gitingest
    try:
        result = await gitingest_tool(path)
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        console.print(f"[bold red]Error during analysis:[/bold red] {e}")
        raise typer.Exit(code=1) from e

    if not result.get("success"):
        logger.error(f"Analysis failed: {result.get('error')}")
        console.print(f"[bold red]Analysis failed:[/bold red] {result.get('error')}")
        raise typer.Exit(code=1)

    # 4. Save results via ArtifactManager
    manager.save_artifact("repo.json", result)

    # 5. Update Manifest and finalize
    summary = result.get("summary", {})
    manager.update_stats(
        {
            "file_counts": summary.get("file_types", {}),
        }
    )
    manager.finalize()

    # 6. Print summary table via rich
    table = Table(title="Analysis Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Total Files Processed", str(summary.get("total_files_processed", 0)))
    table.add_row("Total Size", f"{summary.get('total_size_bytes', 0) / 1024:.2f} KB")
    table.add_row("Total Functions", str(summary.get("code_metrics", {}).get("total_functions", 0)))
    table.add_row("Total Classes", str(summary.get("code_metrics", {}).get("total_classes", 0)))

    console.print(table)
    console.print(f"\n[bold green]Artifacts saved to:[/bold green] {manager.base_path}")
    return manager


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is in use on a specific host."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind socket to this host."),
    port: int = typer.Option(8000, "--port", "-p", help="Bind socket to this port."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the browser automatically."),
    artifacts_dir: str = typer.Option("artifacts", "--artifacts-dir", help="Directory containing artifacts."),
):
    """Start the Web Dashboard to view generated resumes."""
    import os
    import webbrowser

    import uvicorn
    from rich.console import Console

    console = Console()

    # Try to find an available port
    original_port = port
    max_tries = 10
    found_port = False

    for try_port in range(port, port + max_tries):
        if not is_port_in_use(host, try_port):
            if try_port != original_port:
                console.print(f"[bold yellow]Port {original_port} is in use. Trying {try_port}...[/bold yellow]")
            port = try_port
            found_port = True
            break

    if not found_port:
        console.print(
            f"[bold red]Error:[/bold red] Could not find an available port in range {original_port} to {original_port + max_tries - 1}."
        )
        raise typer.Exit(code=1)

    os.environ["GITRESUME_ARTIFACTS_DIR"] = artifacts_dir

    url = f"http://{host}:{port}"
    console.print(f"[bold green]Starting GitResume Dashboard at {url}[/bold green]")

    if open_browser:
        # Give the server a moment to start
        import threading
        import time

        def open_url():
            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=open_url, daemon=True).start()

    from gitresume_web.main import app as web_app

    uvicorn.run(web_app, host=host, port=port, log_level="info")


@app.command()
def generate(
    path: str = typer.Argument(".", help="Path to repo or artifact directory."),
    model: str | None = typer.Option(None, "--model", help="LLM model to use."),
    prompt: str | None = typer.Option(None, "--prompt", help="Custom prompt override."),
    job_description: str | None = typer.Option(
        None, "--jd", "--job-description", help="Job description to tailor the resume."
    ),
    output_dir: str = typer.Option("artifacts", "--output-dir", "-o", help="Directory to save artifacts."),
):
    """Generate a resume from a repository analysis."""
    import asyncio
    from pathlib import Path

    from rich.console import Console
    from rich.status import Status

    from gitresume_core.artifacts import ArtifactManager
    from gitresume_core.create_resume import generate_resume_from_data, resume_to_markdown

    console = Console()
    path_obj = Path(path)
    manager = None

    # 1. Try to find repo.json
    repo_data = None
    if (path_obj / "repo.json").exists():
        # User pointed to an artifact directory
        manager = ArtifactManager(base_dir=str(path_obj.parent), run_id=path_obj.name)
        repo_data = manager.load_artifact("repo.json")
    elif (path_obj / "artifacts").exists() or path_obj.is_dir():
        # It's a repo path, let's see if we should analyze it first
        # For simplicity in Phase 4, if repo.json isn't found at the exact path, we run analyze
        console.print("[yellow]No existing analysis found. Running analysis first...[/yellow]")
        manager = asyncio.run(_run_analysis(path, output_dir))
        repo_data = manager.load_artifact("repo.json")

    if not repo_data:
        console.print("[bold red]Error:[/bold red] Could not find or generate repository analysis.")
        raise typer.Exit(code=1)

    # 2. Generate Resume
    console.print(f"[bold blue]Generating resume using model:[/bold blue] {model or 'default'}")

    with Status("[bold green]Working with LLM...", console=console):
        try:
            resume_result = asyncio.run(
                generate_resume_from_data(
                    repo_data=repo_data, job_description=job_description, model=model, prompt=prompt
                )
            )
        except Exception as e:
            console.print(f"[bold red]Generation failed:[/bold red] {e}")
            raise typer.Exit(code=1) from e

    if not resume_result.get("success"):
        console.print(f"[bold red]Generation failed:[/bold red] {resume_result.get('error')}")
        raise typer.Exit(code=1)

    # 3. Save Outputs
    if manager:
        resume_dir = manager.base_path / "resume"
        resume_dir.mkdir(exist_ok=True)

        manager.save_artifact("resume/resume.json", resume_result)
        md_content = resume_to_markdown(resume_result)
        manager.save_artifact("resume/resume.md", md_content, type="text")
        manager.finalize()

        # 4. Summary
        console.print("\n[bold green]Resume generated successfully![/bold green]")
        console.print(f"[bold blue]JSON:[/bold blue] {manager.base_path / 'resume.json'}")
        console.print(f"[bold blue]Markdown:[/bold blue] {manager.base_path / 'resume.md'}")
    else:
        # Fallback if manager is still None for some reason
        console.print("\n[bold green]Resume generated successfully![/bold green]")
        console.print("[yellow]Note: Artifacts were not saved to a managed directory.[/yellow]")

    # Print a snippet of the markdown
    console.print("\n[bold cyan]--- Resume Snippet ---[/bold cyan]")
    snippet = "\n".join(md_content.splitlines()[:15])
    console.print(snippet + "\n...")


@app.command()
def bulk(
    input_file: str = typer.Argument(..., help="Path to a text/json/csv file with repo paths."),
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Number of parallel tasks."),
    mode: str = typer.Option("analyze", "--mode", "-m", help="Processing mode: 'analyze' or 'generate'."),
    output_dir: str = typer.Option("artifacts", "--output-dir", "-o", help="Directory to save artifacts."),
    model: str | None = typer.Option(None, "--model", help="LLM model to use (for generate mode)."),
    job_description: str | None = typer.Option(
        None, "--jd", "--job-description", help="Job description (for generate mode)."
    ),
):
    """Process multiple repositories in bulk."""
    import asyncio

    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
    from rich.table import Table

    from gitresume_core.bulk import parse_input_file, process_bulk

    console = Console()

    try:
        inputs = parse_input_file(input_file)
    except Exception as e:
        console.print(f"[bold red]Error parsing input file:[/bold red] {e}")
        raise typer.Exit(code=1) from e

    if not inputs:
        console.print("[bold yellow]No inputs found in the file.[/bold yellow]")
        return

    console.print(f"[bold blue]Bulk processing {len(inputs)} repositories in '{mode}' mode...[/bold blue]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Processing {mode}...", total=len(inputs))

        def progress_callback(input_path, success):
            progress.advance(task)
            status = "[green]OK[/green]" if success else "[red]FAIL[/red]"
            progress.console.print(f"{status} {input_path}")

        report = asyncio.run(
            process_bulk(
                inputs=inputs,
                mode=mode,
                concurrency=concurrency,
                output_dir=output_dir,
                model=model,
                job_description=job_description,
                progress_callback=progress_callback,
            )
        )

    # Print Summary Table
    console.print("\n[bold blue]Bulk Processing Summary[/bold blue]")
    table = Table()
    table.add_column("Result", style="cyan")
    table.add_column("Count", style="magenta")

    table.add_row("Total", str(report["total"]))
    table.add_row("Success", f"[green]{report['success']}[/green]")
    table.add_row("Failed", f"[red]{report['failed']}[/red]")

    console.print(table)

    if report["failed"] > 0:
        console.print("\n[bold red]Failures:[/bold red]")
        for detail in report["details"]:
            if not detail["success"]:
                console.print(f"- {detail['input']}: {detail['error']}")


if __name__ == "__main__":
    app()
