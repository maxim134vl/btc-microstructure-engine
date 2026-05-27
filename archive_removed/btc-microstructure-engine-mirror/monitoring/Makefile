# =============================================================================
# BTC Microstructure Engine — Observability Platform
# Top-level entry points. Run from monitoring/ (or via repo-root delegator).
#
# Two modes:
#   * local dev — `make build` / `make up` builds images locally and runs the
#     engine + obs compose with the dev overlay (loopback ports etc.)
#   * push to prod — `make push TAG=1.0.0` builds + pushes images to the
#     private registry. On the server, run:
#         docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d
# =============================================================================

SHELL := /usr/bin/env bash
.ONESHELL:
.DEFAULT_GOAL := help

COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; else echo "docker-compose"; fi)

REPO_ROOT      := $(realpath ..)
ENGINE_COMPOSE := -f $(REPO_ROOT)/docker-compose.yml
MON_COMPOSE    := -f deploy/docker-compose.monitoring.yml
DEV_OVERRIDE   := -f deploy/docker-compose.dev.yml

COMPOSE_FILES := $(ENGINE_COMPOSE) $(MON_COMPOSE) $(DEV_OVERRIDE)

help: ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

init: ## first-time setup: copies .env.example, ensures volumes exist
	@./scripts/bootstrap.sh

# ---- local dev ----
build: ## build all custom service images locally
	$(COMPOSE) $(COMPOSE_FILES) build

build-no-cache: ## build without docker layer cache
	$(COMPOSE) $(COMPOSE_FILES) build --no-cache

up: ## start engine + monitoring stack (local dev)
	$(COMPOSE) $(COMPOSE_FILES) up -d
	@$(MAKE) ps

up-mon: ## start monitoring only (engine assumed running)
	$(COMPOSE) $(MON_COMPOSE) $(DEV_OVERRIDE) up -d

down: ## stop & remove containers (volumes preserved)
	$(COMPOSE) $(COMPOSE_FILES) down

restart: ## restart all services
	@$(MAKE) down
	@$(MAKE) up

restart-svc: ## restart one service (usage: make restart-svc SVC=health-api)
	@test -n "$(SVC)" || { echo "usage: make restart-svc SVC=<name>"; exit 1; }
	$(COMPOSE) $(COMPOSE_FILES) restart $(SVC)

ps: ## list running services
	$(COMPOSE) $(COMPOSE_FILES) ps

logs: ## tail logs (usage: make logs [SVC=health-api])
	@if [ -n "$(SVC)" ]; then \
	  $(COMPOSE) $(COMPOSE_FILES) logs -f --tail=200 $(SVC); \
	else \
	  $(COMPOSE) $(COMPOSE_FILES) logs -f --tail=80; \
	fi

# ---- registry push ----
# Version comes from monitoring/VERSION and is auto-bumped on every push.
# Default: bump patch. Override with BUMP=minor|major or force TAG=X.Y.Z.
push: ## build + push all 5 images, auto-bumps VERSION (BUMP=patch|minor|major or TAG=X.Y.Z)
	@$(if $(TAG),TAG=$(TAG),) $(if $(BUMP),BUMP=$(BUMP),) ./scripts/build-and-push.sh

push-one: ## push only one image (TAG required — partial push doesn't bump VERSION)
	@test -n "$(NAME)" || { echo "usage: make push-one NAME=<image> [TAG=<version>]"; exit 1; }
	@ONLY=$(NAME) $(if $(TAG),TAG=$(TAG),) $(if $(BUMP),BUMP=$(BUMP),) ./scripts/build-and-push.sh

version: ## show the current VERSION
	@cat VERSION

# ---- testing ----
test: ## run unit tests
	@for svc in metrics-exporter health-api alert-engine watchdog; do \
	  echo ">> testing $$svc"; \
	  (cd services/$$svc && python3 -m pytest -q || exit 1); \
	done

smoke: ## end-to-end smoke test against running stack
	@./scripts/smoke-test.sh

shell: ## drop into a service shell (usage: make shell SVC=health-api)
	@test -n "$(SVC)" || { echo "usage: make shell SVC=<name>"; exit 1; }
	$(COMPOSE) $(COMPOSE_FILES) exec $(SVC) /bin/sh

audit: ## tail the watchdog audit log
	@curl -sf http://localhost:9103/api/audit | python3 -m json.tool

snapshot: ## pretty-print the metrics-exporter snapshot
	@curl -sf http://localhost:9101/api/snapshot | python3 -m json.tool

.PHONY: help init build build-no-cache up up-mon down restart restart-svc ps logs push push-one version test smoke shell audit snapshot
