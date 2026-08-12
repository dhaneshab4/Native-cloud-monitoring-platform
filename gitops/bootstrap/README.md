# Bootstrap

Two `kubectl apply` commands, once per cluster. After that every change to the
platform is a pull request.

```bash
# 1. Argo CD itself. This is the one component that cannot manage its own
#    installation, so it is installed imperatively and then adopts everything else.
#
#    --server-side is required, not optional. The applicationsets CRD is larger
#    than the 262144-byte limit on the last-applied-configuration annotation
#    that client-side apply writes, so a plain `kubectl apply` fails with
#    "metadata.annotations: Too long" and silently leaves that CRD missing
#    while everything else installs.
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s

# 2. The project (blast radius) and the root application (app-of-apps).
kubectl apply -f gitops/bootstrap/argocd-project.yaml
kubectl apply -f gitops/bootstrap/root-app.yaml
```

## Reaching the UI

```bash
kubectl -n argocd port-forward svc/argocd-server 8081:443
# https://localhost:8081  — user: admin
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d
```

Change the admin password and delete `argocd-initial-admin-secret` before
pointing this at anything that matters.

## What the root app pulls in

| Application | Namespace | Source |
| --- | --- | --- |
| `kube-prometheus-stack` | `observability` | Upstream Helm chart |
| `argo-rollouts` | `argo-rollouts` | Upstream Helm chart |
| `monitoring-app-dev` | `monitoring-dev` | `charts/monitoring-app` + `values-dev.yaml` |
| `monitoring-app-prod` | `monitoring-prod` | `charts/monitoring-app` + `values-prod.yaml` |

Dev self-heals and prunes automatically. Prod requires a manual sync — the
promotion gate is a human, and the sync window in the AppProject blocks
unattended weekend syncs regardless.

## Verifying the GitOps loop actually works

The demonstration that matters is not that it deploys, but that it *corrects*:

```bash
kubectl -n monitoring-dev scale deploy/monitoring-app-dev --replicas=5
kubectl -n monitoring-dev get deploy monitoring-app-dev -w
```

Within a minute Argo CD reverts it to the replica count declared in Git. That
reconciliation, not the initial install, is the thing worth screenshotting.
