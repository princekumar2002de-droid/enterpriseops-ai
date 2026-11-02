# EnterpriseOps AI backend image.
# Two stages: dependencies are installed with uv from the lockfile in a builder,
# the runtime image only contains the virtualenv + source and runs as non-root.

FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Install dependencies first (cached layer while only source code changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .

FROM python:3.12-slim AS runtime
RUN groupadd --system eops && useradd --system --gid eops --home /app eops
WORKDIR /app
COPY --from=builder --chown=eops:eops /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER eops
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
