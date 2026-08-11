.DEFAULT_GOAL := help
VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
IMAGE := ghcr.io/dhaneshab4/cloud-native-monitoring-app:local

.PHONY: help setup lint fmt test cov run build scan up down logs k8s k8s-check clean

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
