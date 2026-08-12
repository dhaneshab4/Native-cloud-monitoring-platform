.DEFAULT_GOAL := help
VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
IMAGE := ghcr.io/dhaneshab4/cloud-native-monitoring-app:local

CLUSTER   := monitoring
CHART     := charts/monitoring-app
TF_DEV    := infra/terraform/envs/dev

.PHONY: help setup lint fmt test cov run build scan up down logs k8s k8s-check clean \
        tools kind-up kind-down argo-install argo-password argo-ui \
        helm-lint helm-render helm-diff platform selfheal rollout-watch \
        tf-init tf-plan tf-apply tf-destroy tf-fmt verify

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

setup: ## Create the virtualenv and install dev dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

lint: ## Run ruff
	$(VENV)/bin/ruff check app tests
	$(VENV)/bin/ruff format --check app tests

fmt: ## Autoformat
	$(VENV)/bin/ruff format app tests
	$(VENV)/bin/ruff check --fix app tests

test: ## Run the test suite
	$(PY) -m pytest -q

cov: ## Run tests with a coverage floor
	$(PY) -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=90

run: ## Run the app locally on :5000
	$(PY) -m app.main

build: ## Build the container image
	docker build --target runtime -t $(IMAGE) .

scan: build ## Scan the image with Trivy
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
	  aquasec/trivy:latest image --severity HIGH,CRITICAL --ignore-unfixed $(IMAGE)

up: ## Start app + Prometheus + Grafana
	docker compose up -d --build
	@echo "app        http://localhost:5000"
	@echo "prometheus http://localhost:9090"
	@echo "grafana    http://localhost:3000"

down: ## Stop the stack and remove volumes
	docker compose down -v

logs: ## Follow stack logs
	docker compose logs -f

k8s: ## Apply the Kubernetes manifests
	kubectl apply -k deploy/k8s/

k8s-check: ## Validate the manifests the way CI does
	kubeconform -strict -summary -schema-location default \
	  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
	  deploy/k8s/

clean: ## Remove build and test artefacts
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage coverage.xml
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ---------------------------------------------------------------- toolchain
tools: ## Install the DevOps CLIs (macOS, Homebrew)
	brew install kind kubectl helm terraform tflint awscli argocd yq kubeconform
	brew install argoproj/tap/kubectl-argo-rollouts
	@echo "Docker Desktop must be installed separately: https://docker.com/products/docker-desktop"

# ------------------------------------------------------------ local cluster
kind-up: ## Create the local kind cluster
	kind create cluster --config local/kind-cluster.yaml
	kubectl cluster-info --context kind-$(CLUSTER)

kind-down: ## Delete the local kind cluster
	kind delete cluster --name $(CLUSTER)

argo-install: ## Install Argo CD and apply the app-of-apps root
	kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
	@# --server-side is required: the applicationsets CRD exceeds the 262144-byte
	@# annotation limit that client-side apply writes, and fails without it.
	kubectl apply -n argocd --server-side --force-conflicts \
	  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
	kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
	kubectl apply -f gitops/bootstrap/argocd-project.yaml
	kubectl apply -f gitops/bootstrap/root-app.yaml
	@echo "Root application applied. Watch it converge:  make argo-ui"

argo-password: ## Print the initial Argo CD admin password
	@kubectl -n argocd get secret argocd-initial-admin-secret \
	  -o jsonpath='{.data.password}' | base64 -d; echo

argo-ui: ## Port-forward the Argo CD UI to https://localhost:8081
	@echo "https://localhost:8081  — user: admin, password: make argo-password"
	kubectl -n argocd port-forward svc/argocd-server 8081:443

platform: kind-up argo-install ## Cluster + Argo CD + everything the root app pulls in
	@echo "Bootstrapped. The root app is now installing Prometheus, Rollouts and the app."

# -------------------------------------------------------------------- helm
helm-lint: ## Lint the chart against both environments
	@for env in dev prod; do \
	  helm lint $(CHART) --values $(CHART)/values.yaml --values $(CHART)/values-$$env.yaml; \
	done

helm-render: ## Render both environments to /tmp/rendered
	@mkdir -p /tmp/rendered
	@for env in dev prod; do \
	  helm template monitoring-app-$$env $(CHART) --namespace monitoring-$$env \
	    --api-versions monitoring.coreos.com/v1 --api-versions argoproj.io/v1alpha1 \
	    --values $(CHART)/values.yaml --values $(CHART)/values-$$env.yaml \
	    > /tmp/rendered/$$env.yaml; \
	  echo "wrote /tmp/rendered/$$env.yaml"; \
	done

helm-diff: helm-render ## Show what actually differs between dev and prod
	@diff -u /tmp/rendered/dev.yaml /tmp/rendered/prod.yaml || true

# ------------------------------------------------------------------ gitops
selfheal: ## Demo: scale by hand, watch Argo CD revert it
	kubectl -n monitoring-dev scale deploy/monitoring-app-dev --replicas=5
	@echo "Scaled to 5 out of band. Argo CD should revert this within ~60s."
	kubectl -n monitoring-dev get deploy monitoring-app-dev -w

rollout-watch: ## Watch the production canary progress
	kubectl argo rollouts get rollout monitoring-app-prod -n monitoring-prod --watch

# --------------------------------------------------------------- terraform
tf-fmt: ## Format all Terraform
	terraform fmt -recursive infra/terraform

tf-init: ## Initialise the dev environment
	terraform -chdir=$(TF_DEV) init

tf-plan: ## Plan the dev environment
	terraform -chdir=$(TF_DEV) plan -var-file=terraform.tfvars

tf-apply: ## Apply the dev environment (creates real AWS resources — costs money)
	terraform -chdir=$(TF_DEV) apply -var-file=terraform.tfvars

tf-destroy: ## Tear the dev environment down
	terraform -chdir=$(TF_DEV) destroy -var-file=terraform.tfvars

# ------------------------------------------------------------------ verify
verify: lint cov helm-lint k8s-check ## Everything CI checks, locally
	terraform -chdir=$(TF_DEV) fmt -check -recursive
	@echo "All local gates passed."
