# =============================================================================
# Repo-root Makefile — delegator.
# All real targets live in monitoring/Makefile. This file just forwards.
#
# Examples:
#   make init        -> cd monitoring && make init
#   make up          -> cd monitoring && make up
#   make logs SVC=traefik  -> forwards SVC unchanged
#
# `make help` shows the full list (from the monitoring Makefile).
# =============================================================================

MON_DIR := monitoring

.DEFAULT_GOAL := help

# Allow targets that don't exist here to forward to the monitoring Makefile.
# This catches make init, make build, make up, etc. transparently.
%:
	@$(MAKE) -C $(MON_DIR) $(MAKECMDGOALS) $(if $(SVC),SVC=$(SVC)) $(if $(ENVIRONMENT),ENVIRONMENT=$(ENVIRONMENT))

help:
	@printf "\n  BTC microstructure engine + observability\n"
	@printf "  Repo-root Makefile (delegator). All targets defined in $(MON_DIR)/Makefile.\n\n"
	@$(MAKE) -s -C $(MON_DIR) help

# Targets that need engine-side actions go here directly.
engine-up: ## start engine (collectors + pipeline) via the existing deploy.sh
	@./deploy.sh up

engine-down: ## stop engine containers (data volume preserved)
	@./deploy.sh down

engine-logs: ## tail engine logs (usage: make engine-logs SVC=binance-feed)
	@./deploy.sh logs $(SVC)

engine-ps: ## show engine container status
	@./deploy.sh ps

all-up: ## bring up BOTH engine and monitoring (recommended for full stack)
	@$(MAKE) engine-up
	@$(MAKE) -C $(MON_DIR) up-mon

all-down: ## stop both planes
	@$(MAKE) -C $(MON_DIR) down 2>/dev/null || true
	@$(MAKE) engine-down

.PHONY: help engine-up engine-down engine-logs engine-ps all-up all-down
