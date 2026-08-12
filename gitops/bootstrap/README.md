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

## Behind an HTTP proxy

On a network where pods have no working DNS and all egress goes through a
proxy, the repo-server cannot clone and every Application sits at
`ComparisonError: ... dial tcp: lookup github.com ... server misbehaving`.

Argo CD's git client honours the standard proxy variables, so the fix is to set
them on the three components that talk out. `NO_PROXY` matters as much as the
other two — without it the in-cluster gRPC between the controller, repo-server
and Redis is sent to the proxy as well, and Argo fails in a much more confusing
way than a plain clone failure.

```bash
kubectl -n argocd set env \
  deploy/argocd-repo-server \
  statefulset/argocd-application-controller \
  deploy/argocd-server \
  HTTP_PROXY=http://<proxy-host>:<port> \
  HTTPS_PROXY=http://<proxy-host>:<port> \
  NO_PROXY=localhost,127.0.0.1,10.96.0.0/12,10.244.0.0/16,.svc,.cluster.local

kubectl -n argocd annotate application root \
  argocd.argoproj.io/refresh=hard --overwrite
```

The kind nodes need the same treatment at creation time — export `HTTP_PROXY`,
`HTTPS_PROXY` and `NO_PROXY` before `kind create cluster` and kind writes them
into each node's containerd config, without which the kubelet cannot pull
images either.

**The environment variables are not sufficient on their own.** They fix image
pulls and anything shelling out to `git`, but the repo-server reaches
repositories through its own Go client, which does not read them. The symptom
is confusing, because `git ls-remote` run by hand inside that very pod
succeeds while Argo keeps reporting

```
ComparisonError: failed to list refs: ... dial tcp: lookup github.com ...
```

Argo takes the proxy per repository instead, declared on the repository secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-ci-cd-pipeline
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: https://github.com/dhaneshab4/Native-cloud-monitoring-platform.git
  proxy: http://<proxy-host>:<port>
```

The URL must match the `repoURL` in the Applications exactly, character for
character, or Argo will not associate the two and silently falls back to no
proxy.

## Verifying the GitOps loop actually works

The demonstration that matters is not that it deploys, but that it *corrects*:

```bash
kubectl -n monitoring-dev scale deploy/monitoring-app-dev --replicas=5
kubectl -n monitoring-dev get deploy monitoring-app-dev -w
```

Within a minute Argo CD reverts it to the replica count declared in Git. That
reconciliation, not the initial install, is the thing worth screenshotting.
