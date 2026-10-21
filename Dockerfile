# TMS service: MCP at /mcp, web pages, /dashboard. App Platform sets PORT (8080).
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH PORT=8080
EXPOSE 8080
CMD ["tms-server", "--http", "--host", "0.0.0.0"]
