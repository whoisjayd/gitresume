# Contributing to GitResume

Thank you for your interest in contributing! Please follow these guidelines to help us maintain a high-quality project.

## Local Development Setup

We use [uv](https://github.com/astral-sh/uv) for dependency management.

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/whoisjayd/gitresume.git
    cd gitresume
    ```
2.  **Setup Environment**:
    ```bash
    uv sync
    ```
3.  **Run CLI locally**:
    ```bash
    uv run gitresume --help
    ```
4.  **Run Tests**:
    ```bash
    uv run pytest
    ```

## How to Contribute

- Fork the repository and clone it locally.
- Create a new branch for your feature or bugfix: `git checkout -b feature/your-feature`.
- Make your changes and add tests if applicable.
- Ensure your code follows the existing style and passes linting.
- Commit your changes and push your branch.
- Open a Pull Request (PR) with a clear description of your changes.

## Code Style

- Use clear, descriptive commit messages.
- Follow PEP8 for Python code.
- Keep functions and modules focused and well-documented.

## Reporting Issues

- Use [GitHub Issues](https://github.com/whoisjayd/gitresume/issues) for bugs and feature requests.
- Provide as much detail as possible (steps to reproduce, logs, screenshots).

## Community

- Be respectful and inclusive in all interactions.
- See our [Code of Conduct](CODE_OF_CONDUCT.md).
