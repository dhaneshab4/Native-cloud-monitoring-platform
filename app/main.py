"""Flask application exposing host metrics as HTML, JSON and Prometheus text.

Endpoints are split deliberately:
  /          human dashboard
  /api/metrics   JSON snapshot for the dashboard's polling and for scripts
  /metrics       Prometheus exposition format
  /healthz       liveness  - is the process up
  /readyz        readiness - can it actually collect a metric
"""

from __future__ import annotations

import logging
import os

from flask import Flask, Response, jsonify, render_template

from app.config import config
from app.metrics import collect, host_info, prometheus_payload

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("monitoring-app")


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        snapshot = collect()
        return render_template(
            "index.html",
            snapshot=snapshot,
            info=host_info(),
            thresholds=config.thresholds(),
            interval_ms=int(config.sample_interval * 1000),
        )

    @app.get("/api/metrics")
    def api_metrics() -> Response:
        snapshot = collect()
        payload = snapshot.as_dict() | {"host": host_info()}
        response = jsonify(payload)
        response.status_code = 200 if snapshot.status == "healthy" else 503
        return response

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(prometheus_payload(), mimetype="text/plain; version=0.0.4")

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz() -> Response:
        """Ready only if a real collection succeeds — not just if Flask answers."""
        try:
            collect()
        except Exception:
            log.exception("readiness probe failed to collect metrics")
            return jsonify(status="unready"), 503
        return jsonify(status="ready")

    @app.errorhandler(404)
    def not_found(_) -> Response:
        return jsonify(error="not found"), 404

    log.info("thresholds cpu=%s mem=%s disk=%s", config.cpu_warn, config.mem_warn, config.disk_warn)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.host, port=config.port)
