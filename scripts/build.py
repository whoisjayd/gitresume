import os
from pathlib import Path

import PyInstaller.__main__


def build():
    # Get project root
    root = Path(__file__).resolve().parent.parent

    # Entry point
    entry_point = root / "src" / "gitresume_cli" / "main.py"

    # Templates directory to include
    templates_dir = root / "src" / "gitresume_web" / "templates"

    # Define arguments for PyInstaller
    args = [
        str(entry_point),
        "--name", "gitresume",
        "--onefile",
        "--clean",
        f"--paths={root / 'src'}",
        f"--add-data={templates_dir}{os.pathsep}gitresume_web/templates",
        # Include hidden imports for FastAPI/Uvicorn if needed
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.http.h11_impl",
        "--hidden-import=uvicorn.protocols.http.httptools_impl",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.protocols.websockets.wsproto_impl",
        "--hidden-import=uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import=uvicorn.loop.auto",
        "--hidden-import=uvicorn.loop.asyncio",
        "--hidden-import=uvicorn.loop.uvloop",
    ]

    print(f"Building GitResume binary from {entry_point}...")
    print(f"Including templates from {templates_dir}")

    PyInstaller.__main__.run(args)

if __name__ == "__main__":
    build()
