import typer

app = typer.Typer(
    help="GitResume CLI - Generate professional resumes from your GitHub repositories.",
    no_args_is_help=True,
)

@app.command()
def doctor():
    """Check if GitResume is configured correctly."""
    typer.echo("GitResume Doctor")
    typer.echo("Everything looks good! (Placeholder)")

@app.command()
def version():
    """Show the version of GitResume."""
    from gitresume_core.version import get_tool_version
    typer.echo(f"GitResume version: {get_tool_version()}")

if __name__ == "__main__":
    app()
