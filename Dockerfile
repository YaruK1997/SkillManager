# ==============================================================================
# Stage 1: Builder (Python 3.15 + uv environment build)
# ==============================================================================
FROM ghcr.io/astral-sh/uv:debian-slim AS builder

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYYAML_FORCE_LIBYAML=0

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN uv venv /opt/venv --python 3.15 && \
    uv pip install --python /opt/venv/bin/python setuptools wheel && \
    uv pip install --python /opt/venv/bin/python pyyaml --no-build-isolation && \
    uv pip install --python /opt/venv/bin/python --no-cache .

# ==============================================================================
# Stage 2: Runtime (Minimal non-root execution image)
# ==============================================================================
FROM debian:bookworm-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -m -s /bin/bash appuser

COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    HOME=/home/appuser

WORKDIR /app

RUN mkdir -p /home/appuser/.claude/skills \
             /home/appuser/.gemini/antigravity/skills \
             /home/appuser/.codex/skills \
             /home/appuser/.cursor/skills && \
    chown -R appuser:appgroup /home/appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["skill-manager", "healthcheck", "--format", "json"]

ENTRYPOINT ["skill-manager"]
CMD ["healthcheck", "--format", "json"]

