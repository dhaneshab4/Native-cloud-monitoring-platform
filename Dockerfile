# syntax=docker/dockerfile:1.7
#
# Two stages so build tooling never reaches the runtime image: the builder
# compiles wheels into a virtualenv, the runtime copies only that venv. psutil
# needs a C toolchain to build, which would otherwise ship gcc to production
# for no reason.

# ---------------------------------------------------------------- build stage
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependencies are copied and installed before the source, so an application
# change reuses this layer instead of reinstalling every package.
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# -------------------------------------------------------------- runtime stage
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="cloud-native-monitoring-app" \
      org.opencontainers.image.description="Host metrics over HTTP, JSON and Prometheus" \
      org.opencontainers.image.source="https://github.com/dhaneshab4/CI-CD-pipeline" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

# A fixed uid/gid keeps file ownership predictable across bind mounts and hosts.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --chown=appuser:appuser app ./app

USER appuser
EXPOSE 5000

# Probes readiness, not liveness: this fails if metric collection breaks even
# while the process still answers HTTP. urllib avoids installing curl.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", \
       "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/readyz',timeout=2).status==200 else 1)"]

# Exec form so gunicorn is PID 1 and receives SIGTERM directly for clean stops.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", \
     "--access-logfile", "-", "--error-logfile", "-", "app.main:app"]
