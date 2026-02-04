# Use a slim Python image for the build stage
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy configuration files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Final stage
FROM python:3.12-slim

# Copy uv from builder (if needed for runtime, though uv run is used)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy the virtual environment and source code
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY pyproject.toml uv.lock ./

# Ensure the virtual environment is used
ENV PATH="/app/.venv/bin:$PATH"

# Entrypoint
ENTRYPOINT ["uv", "run", "gitresume"]
