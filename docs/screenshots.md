# Screenshots to capture

Save into `docs/img/` with these exact filenames — `README.md` links them.
A reviewer decides in about eight seconds, so the top three matter most.

Run everything against the kind cluster first. It costs nothing and looks
identical to EKS in a screenshot.

## The three that carry the repo

| File | What to capture | How |
| --- | --- | --- |
| `argocd-tree.png` | The Argo CD application tree, everything green and Synced | UI → `root` → tree view. Expand so all four apps are visible. |
| `argocd-selfheal.png` | Argo reverting a manual change | Run the self-heal demo below, screenshot the app going OutOfSync then Synced |
| `rollout-canary.png` | A canary mid-progress at 34% | `kubectl argo rollouts get rollout monitoring-app-prod -n monitoring-prod --watch` |

**The self-heal demo is the single most valuable screenshot in the repo.**
Anyone can deploy something. Showing the platform *correcting drift on its own*
is the thing that distinguishes GitOps from a deploy script:

```bash
kubectl -n monitoring-dev scale deploy/monitoring-app-dev --replicas=5
# screenshot the Argo CD UI here — OutOfSync, 5 replicas
# wait ~60s
kubectl -n monitoring-dev get deploy monitoring-app-dev
# back to 1, because that is what Git says
```

## The rest

| File | What to capture | How |
| --- | --- | --- |
| `grafana-dashboard.png` | Host metrics dashboard with real data | Grafana → NodePort 30082, or port-forward |
| `prometheus-targets.png` | The app target UP, discovered via ServiceMonitor | Prometheus → Status → Targets |
| `gha-pipeline.png` | The CI run, all six jobs green | Actions → a successful run |
| `gha-infra.png` | The Infra workflow green | Actions → Infra |
| `code-scanning.png` | Trivy + Checkov findings in the security tab | Security → Code scanning alerts |
| `terraform-plan.png` | `terraform plan` output showing the resource count | `make tf-plan` |
| `jenkins-pipeline.png` | The stage view, including the promotion gate | Jenkins → Blue Ocean, or the classic stage view |
| `helm-diff.png` | Rendered dev vs prod difference | `make helm-diff` |

## Before you commit any of them

- Crop out browser bookmarks, other tabs and your desktop.
- **Redact the AWS account ID** — it appears in ECR URLs, IRSA role ARNs and
  `terraform plan` output. A 12-digit number in the corner of a screenshot is
  the single most common leak in a public portfolio repo.
- Redact any cluster endpoint hostname.
- Use dark mode consistently; a mixed set looks careless.
- Retina screenshots are ~2–4 MB. Shrink them, or the clone gets heavy:
  `sips -Z 1600 docs/img/*.png` on macOS.

## Embedding

Put the top three directly under the title in `README.md`, before any prose:

```markdown
| GitOps reconciliation | Canary rollout | Observability |
| --- | --- | --- |
| ![Argo CD](docs/img/argocd-tree.png) | ![Canary](docs/img/rollout-canary.png) | ![Grafana](docs/img/grafana-dashboard.png) |
```
