# Cloud Native Monitoring — build, test, ship, run

[![CI/CD](https://github.com/dhaneshab4/CI-CD-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/dhaneshab4/CI-CD-pipeline/actions/workflows/ci.yml)

A small Python service that reports host metrics over HTTP, JSON and Prometheus,
plus the pipeline and deployment machinery around it. The service is deliberately
simple; the point of the repository is everything else — the multi-stage image,
the CI/CD pipeline, the observability stack and the three deployment paths.

```
                  ┌──────────────┐   scrape /metrics   ┌──────────────┐
   browser ──────▶│     app      │◀────────────────────│  Prometheus  │
                  │  Flask/gunicorn                    │   + alerts   │
                  │  psutil       │                    └──────┬───────┘
                  └──────────────┘                            │ query
                                                       ┌──────▼───────┐
                                                       │   Grafana    │
                                                       └──────────────┘
```

## Quick start

```bash
make setup      # virtualenv + dev dependencies
make test       # 22 tests
make run        # http://localhost:5000

make up         # app + Prometheus + Grafana via Docker Compose
make down
```

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:5000 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

## Endpoints

| Path | Purpose |
| --- | --- |
| `/` | Dashboard; polls the JSON API, no build step, dark mode |
| `/api/metrics` | JSON snapshot. Returns **503** when a threshold is breached |
| `/metrics` | Prometheus exposition format |
| `/healthz` | Liveness — is the process answering |
| `/readyz` | Readiness — can it *actually* collect a metric |

`/healthz` and `/readyz` are separate on purpose. A process can be alive and
still useless: if `/proc` is unreadable the app answers HTTP but cannot collect
anything. Liveness stays green so the orchestrator does not pointlessly restart
it; readiness goes red so traffic stops arriving.

## Configuration

Every value has a working default — the app runs with no configuration at all.

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_PORT` | `5000` | Listen port |
| `CPU_WARN_PERCENT` | `80` | CPU threshold for degraded status |
| `MEM_WARN_PERCENT` | `80` | Memory threshold |
| `DISK_WARN_PERCENT` | `85` | Disk threshold |
| `DISK_PATH` | `/` | Filesystem to measure |
| `SAMPLE_INTERVAL_SECONDS` | `5` | Dashboard poll interval |
| `LOG_LEVEL` | `INFO` | Log verbosity |

Invalid values fail at startup with a clear message rather than silently
falling back to a default — a typo in `CPU_WARN_PERCENT` should not quietly
disable alerting.

## The image

Multi-stage. The builder installs into a virtualenv and the runtime copies only
that virtualenv, so the C toolchain `psutil` needs to compile never reaches
production.

- Dependencies are installed **before** the source is copied, so an application
  change reuses the dependency layer instead of reinstalling every package
- Runs as a non-root user with a **fixed uid/gid (10001)** so ownership is
  predictable across bind mounts and hosts
- `HEALTHCHECK` probes `/readyz`, not `/healthz` — it should fail when the app
  is useless, not only when it is dead. Implemented with `urllib` so `curl`
  does not have to be installed
- Exec-form `CMD` so gunicorn is PID 1 and receives `SIGTERM` directly
- Compose runs it `read_only` with `no-new-privileges` and a tmpfs for `/tmp`

## The pipeline

`.github/workflows/ci.yml` — six jobs, gated in that order.

| Job | What it does |
| --- | --- |
| **lint** | `ruff check` and `ruff format --check` |
| **test** | pytest across Python 3.11, 3.12 and 3.13, coverage floor 90% |
| **validate-config** | `promtool check config` and `check rules` — a broken alert rule fails the build, not the on-call |
| **validate-manifests** | `kubeconform -strict` over `deploy/k8s/`, with CRD schemas so the ServiceMonitor is checked too |
| **build** | Buildx with GHA layer cache → **load locally and smoke-test first** → Trivy scan (SARIF to the Security tab) → multi-arch push to GHCR → cosign signature and SBOM attestation |
| **integration** | Brings the whole Compose stack up, waits for the container to report *healthy*, asserts Prometheus actually has the target `up`, checks Grafana's health endpoint |

Two details worth calling out:

**The image is smoke-tested before it is pushed.** It is loaded into the local
daemon, started, and probed on every endpoint — including a check that it really
is running as uid 10001. A broken image never reaches the registry.

**The integration job asserts the scrape works**, not just that the containers
started. `docker compose up` succeeding proves very little; querying
`up{job="monitoring-app"} == 1` proves Prometheus can actually reach the target.

Concurrency is set so a second push to a branch cancels the first.

### Supply chain

Every pushed image is signed with **cosign** using keyless OIDC — no private key
to store or rotate — and an **SPDX SBOM** is generated and attested to the same
image.

Both operate on the **digest**, not a tag. Tags are mutable: a tag signed today
can be repointed at a different image tomorrow, and the signature would still
appear valid. The digest cannot.

```bash
cosign verify ghcr.io/dhaneshab4/cloud-native-monitoring-app:latest \
  --certificate-identity-regexp 'https://github.com/dhaneshab4/CI-CD-pipeline/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Dependabot watches pip, Docker base images and the Actions themselves, grouped
so it opens one PR per ecosystem rather than a dozen.

## Deployment

Three paths, all in `deploy/`.

**Containers** — `docker compose up -d`. Prometheus and Grafana are provisioned
from files — datasource *and* a ten-panel dashboard — so the stack comes up with
graphs already drawn and nothing to click.

**Kubernetes** — `kubectl apply -k deploy/k8s/`. Two replicas, `maxUnavailable: 0`
so a rollout never drops below the current count, a PodDisruptionBudget, resource
requests and limits, and a locked-down `securityContext` (non-root, read-only
root filesystem, all capabilities dropped, `RuntimeDefault` seccomp).

The three probes do different jobs: `startupProbe` gives a slow start up to 60s
without a lenient liveness threshold, `livenessProbe` hits `/healthz` so a
*degraded* pod is not killed, and `readinessProbe` hits `/readyz` so a pod that
cannot collect metrics is pulled out of the Service instead. A `ServiceMonitor`
is included for clusters running the Prometheus Operator; it is inert elsewhere.

**Bare metal / VM** — `deploy/monitoring-app.service` is a hardened systemd unit:
ordered after `network-online.target`, dedicated non-login service user,
`EnvironmentFile` for secrets, `Restart=always` with a backoff, and a lockdown
block (`ProtectSystem=strict`, `NoNewPrivileges`, `MemoryDenyWriteExecute`,
`SystemCallFilter=@system-service`) because the service reads `/proc` and needs
essentially nothing else.

`deploy/ansible/playbook.yml` provisions a Debian/Ubuntu host end to end —
packages, service account, checkout, virtualenv, unit file, enable, and then
polls `/readyz` until it answers 200. Handlers mean a re-run only restarts the
service if something actually changed.

## Alerting

`deploy/alerts.yml` — high CPU, high memory, disk almost full, application
self-reported degraded, and target down. All have a `for:` duration so a single
scrape spike does not page anyone.

## Layout

```
app/            config.py  metrics.py  main.py  templates/
tests/          22 tests — API contracts, collection, config failure modes
deploy/
  prometheus.yml  alerts.yml        scrape config and five alert rules
  grafana/                          provisioned datasource + 10-panel dashboard
  monitoring-app.service            hardened systemd unit
  ansible/                          host provisioning playbook
  k8s/                              kustomize: deployment, service, PDB, ServiceMonitor
.github/        workflows/ci.yml  dependabot.yml
Dockerfile      multi-stage, non-root, healthchecked
docker-compose.yml
Makefile        setup lint fmt test cov run build scan up down logs clean
```

## Local development

```bash
make setup
make lint       # ruff
make cov        # tests with the 90% floor enforced
make fmt        # autoformat and autofix
make build      # build the image
make scan       # Trivy, HIGH and CRITICAL only
make k8s        # kubectl apply -k deploy/k8s/
make k8s-check  # kubeconform, the same check CI runs
```

## Licence

MIT
