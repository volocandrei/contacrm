# syntax=docker/dockerfile:1

# ─── Build ────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependențele se instalează înaintea codului: un layer care se invalidează doar
# când se schimbă lockfile-ul, nu la fiecare modificare de sursă.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ─── Runtime ──────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Aplicația nu rulează ca root: un upload malițios nu trebuie să aibă drepturi de sistem (R3).
RUN groupadd --system --gid 1001 contacrm \
 && useradd --system --uid 1001 --gid contacrm --create-home contacrm

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --from=builder --chown=contacrm:contacrm /app /app

# Storage-ul stă în afara webroot-ului și aparține utilizatorului aplicației (R3).
RUN mkdir -p /var/lib/contacrm/storage && chown -R contacrm:contacrm /var/lib/contacrm

USER contacrm
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request as r; r.urlopen('http://127.0.0.1:8000/health/live', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
