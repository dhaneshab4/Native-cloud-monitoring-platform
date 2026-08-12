# Architecture

Three layers with one rule between them: **each layer only writes to the layer
below it through Git.**

```
  ┌─────────────────────────────────────────────────────────────────┐
  │ 1. INFRASTRUCTURE          Terraform                            │
  │    VPC · EKS · ECR · IRSA roles · S3 state + DynamoDB lock      │
  │    Changes by: terraform apply, from a reviewed plan            │
  └────────────────────────────┬────────────────────────────────────┘
                               │ hands over a cluster and a registry
  ┌────────────────────────────▼────────────────────────────────────┐
  │ 2. PLATFORM                Argo CD (app-of-apps)                │
  │    kube-prometheus-stack · argo-rollouts · the app, per env     │
  │    Changes by: a commit under gitops/ or charts/                │
  └────────────────────────────┬────────────────────────────────────┘
                               │ reconciles continuously
  ┌────────────────────────────▼────────────────────────────────────┐
  │ 3. APPLICATION             Helm chart + container image         │
  │    Flask · gunicorn · Prometheus metrics                        │
  │    Changes by: CI building an image and bumping a values tag    │
  └─────────────────────────────────────────────────────────────────┘
```

## Why CI never touches the cluster

GitHub Actions and Jenkins build, test, scan, sign and push. Neither runs
`kubectl apply`. The deploy is a commit that changes an image tag in
`charts/monitoring-app/values-{dev,prod}.yaml`; Argo CD notices and converges.

Three things follow from that, and they are the whole argument for GitOps:

- **The cluster matches `main`, always.** Not "matches whatever the last
  successful pipeline did". If someone hand-patches a Deployment, `selfHeal`
  puts it back.
- **CI needs no cluster credentials.** A compromised pipeline token cannot
  reach production, because production is not reachable from the pipeline.
- **Rollback is `git revert`.** No pipeline re-run, no "which build was good",
  no rebuilding an image that already exists.

## Delivery path

```
 commit ──▶ ci.yml ──▶ image built, scanned, signed, SBOM attested, pushed
                            │
                            ▼
              Jenkins bumps values-dev.yaml  ──▶  commit to main
                            │
                            ▼
                Argo CD syncs monitoring-app-dev automatically
                    (prune: true, selfHeal: true)
                            │
                            ▼
                  human approves the promotion in Jenkins
                            │
                            ▼
              Jenkins bumps values-prod.yaml  ──▶  commit to main
                            │
                            ▼
              Argo CD syncs monitoring-app-prod  (manual sync)
                            │
                            ▼
              Argo Rollouts canary: 10% → 34% → 67% → 100%
              aborts automatically if the success-rate analysis fails
```

## Environment differences

| | dev | prod |
| --- | --- | --- |
| Replicas | 1 | 3–10 (HPA) |
| Delivery | RollingUpdate | Argo Rollouts canary |
| Argo sync | automated, self-healing | manual, gated by review |
| Service | NodePort (kind → localhost:8080) | ClusterIP |
| PDB | off | minAvailable 2 |
| Log level | DEBUG | INFO |

Both run non-root with a read-only root filesystem and all capabilities
dropped. Hardening is not an environment difference — the only things that vary
are cost, exposure and how much automation is allowed to act unattended.

## Two ways to run it

**kind (free).** Everything above except Terraform. The Argo CD loop, the
canary, the dashboards and the self-heal demo all work identically on a laptop.

**EKS (~$110–150/month).** Adds real IRSA, a real load balancer, spot nodes and
the ECR lifecycle policy. Most of the bill is the control plane at $73 and the
NAT gateway at ~$35, neither of which scales down. Destroy the stack when not
in use.

## Deliberate omissions

- **No service mesh.** Argo Rollouts does replica-weighted canary without one.
  Adding Istio to run a 3-step canary is complexity nobody is paying for here.
- **No secrets in Git.** The IRSA roles exist and External Secrets is wired in
  Terraform, but no SealedSecret or SOPS file ships — an empty secrets story is
  more honest than a fake one.
- **No multi-cluster.** One cluster, two namespaces. The AppProject already
  scopes destinations, so adding a second cluster is a destination entry rather
  than a rewrite.
