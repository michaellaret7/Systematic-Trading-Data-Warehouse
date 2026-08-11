# syntax=docker/dockerfile:1

# ====================================
# --> base: dependencies + source
# ====================================
# amd64 is pinned, not a default: arcticdb ships manylinux wheels for x86_64
# only — there is no Linux aarch64 wheel and no sdist to fall back on, so an
# arm64 build fails outright at `uv sync`. On an Apple Silicon host this image
# therefore runs under emulation; on an x86_64 server it runs natively.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies are installed before the source is copied so that editing a
# module does not invalidate the (slow) arcticdb wheel download.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY src ./src
COPY scripts ./scripts

# Modules are run as `python -m src.jobs.update_equities`, so /app must be on
# sys.path. It already is: python -m resolves against the working directory.
RUN useradd --create-home --uid 10001 warehouse \
    && chown -R warehouse:warehouse /app
USER warehouse


# ====================================
# --> api: long-running HTTP service
# ====================================
FROM base AS api

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ====================================
# --> cron: scheduled warehouse jobs
# ====================================
FROM base AS cron

USER root

# supercronic, not system cron: it runs in the foreground, logs job output to
# stdout, and inherits the container environment. Debian's cron does none of
# these, which is why cron-in-Docker classically cannot see $FMP_API_KEY.
ARG SUPERCRONIC_VERSION=v0.2.33
ARG TARGETARCH
ADD https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH} /usr/local/bin/supercronic
RUN chmod 0755 /usr/local/bin/supercronic

COPY docker/crontab /app/crontab

USER warehouse

# The absolute path is required, not stylistic: as PID 1 supercronic re-execs
# itself via os.Args[0] with no PATH lookup, so a bare "supercronic" dies at
# startup with "Failed to fork exec: no such file or directory".
CMD ["/usr/local/bin/supercronic", "/app/crontab"]
