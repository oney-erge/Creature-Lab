FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS builder
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY creature_lab/ ./creature_lab/
COPY examples/ ./examples/
RUN uv sync --frozen --no-dev --extra sim --extra viz --no-editable

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS runtime
# Listen on every interface inside the container; compose.yaml publishes the port on 127.0.0.1 only.
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CREATURE_LAB_HOST=0.0.0.0
RUN useradd --create-home --uid 10001 creature
WORKDIR /app
COPY --from=builder --chown=creature:creature /app /app
RUN mkdir -p /app/runs /app/outputs && chown -R creature:creature /app/runs /app/outputs
USER creature
EXPOSE 8080
VOLUME ["/app/runs", "/app/outputs"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=12 \
  CMD ["python", "-c", "import socket; s=socket.create_connection(('127.0.0.1',8080),2); s.close()"]
CMD ["creature-lab", "build", "--preset", "quadruped", "--port", "8080", "--no-open-browser"]
