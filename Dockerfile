# Multi-stage build for minimal production image
# Stage 1: Build
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir build && \
    python -m build --wheel --outdir /build/dist

# Stage 2: Production
FROM python:3.12-slim AS production

LABEL maintainer="data-engineering"
LABEL description="BigQuery Entity Resolution Pipeline"

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r pipeline && useradd -r -g pipeline pipeline

WORKDIR /app

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

COPY config/defaults.yml /app/config/defaults.yml

VOLUME ["/app/config/user"]
VOLUME ["/app/secrets"]

HEALTHCHECK --interval=30s --timeout=5s \
    CMD test -f /tmp/pipeline_healthy

USER pipeline

ENTRYPOINT ["python", "-m", "bq_entity_resolution"]
CMD ["run", "--config", "/app/config/user/config.yml", "--defaults", "/app/config/defaults.yml"]
