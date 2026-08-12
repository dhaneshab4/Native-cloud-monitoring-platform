"""Flask application exposing host metrics as HTML, JSON and Prometheus text,
plus semantic search over the operational runbooks.

Endpoints are split deliberately:
  /              human dashboard
  /api/metrics   JSON snapshot for the dashboard's polling and for scripts
  /api/search    semantic search over the runbook corpus
  /api/triage    given an alert, the runbooks most likely to resolve it
  /metrics       Prometheus exposition format
  /healthz       liveness  - is the process up
  /readyz        readiness - can it actually collect a metric
"""

from __future__ import annotations

import logging
import os

from flask import Flask, Response, jsonify, render_template, request

from app.config import config
from app.metrics import collect, host_info, prometheus_payload, registry

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("monitoring-app")


def _load_searcher():
    """Load the prebuilt index, or run without search if it is absent.

    Retrieval is an enhancement, not a dependency. A missing or corrupt index
    must not stop the service reporting host metrics, so this degrades to
    HTTP 503 on the two search routes and leaves everything else working.
    """
    from app.rag.search import Searcher, register

    register(registry)
    try:
        searcher = Searcher.from_disk()
    except (FileNotFoundError, ValueError) as exc:
        log.warning("runbook search disabled: %s", exc)
        return None
    log.info(
        "runbook search ready: %s backend, %d runbooks, %d chunks, checksum %s",
        searcher.index.backend_name,
        searcher.index.document_count,
        searcher.index.chunk_count,
        searcher.index.checksum,
    )
    return searcher


def create_app() -> Flask:
    app = Flask(__name__)
    searcher = _load_searcher()

    @app.get("/")
    def index() -> str:
        snapshot = collect()
        return render_template(
            "index.html",
            snapshot=snapshot,
            info=host_info(),
            thresholds=config.thresholds(),
            interval_ms=int(config.sample_interval * 1000),
            search_enabled=searcher is not None,
        )

    @app.get("/api/metrics")
    def api_metrics() -> Response:
        snapshot = collect()
        payload = snapshot.as_dict() | {"host": host_info()}
        response = jsonify(payload)
        response.status_code = 200 if snapshot.status == "healthy" else 503
        return response

    @app.get("/api/search")
    def api_search() -> Response:
        if searcher is None:
            return jsonify(error="search index unavailable"), 503
        query = request.args.get("q", "")
        if not query.strip():
            return jsonify(error="missing query parameter 'q'"), 400
        try:
            k = min(max(int(request.args.get("k", 5)), 1), 20)
        except ValueError:
            return jsonify(error="'k' must be an integer"), 400
        hits = searcher.search(query, k=k)
        return jsonify(query=query, count=len(hits), results=[h.as_dict() for h in hits])

    @app.post("/api/triage")
    def api_triage() -> Response:
        if searcher is None:
            return jsonify(error="search index unavailable"), 503
        body = request.get_json(silent=True) or {}
        alert = str(body.get("alert", "")).strip()
        if not alert:
            return jsonify(error="body must contain 'alert'"), 400
        detail = str(body.get("detail", ""))
        return jsonify(searcher.triage(alert, detail))

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
