# BTC-ML — local orchestration targets (no engine/runtime logic changes)
#
# Historical local pieces:
#   ./scripts/start_collectors.sh
#   ./run.sh  /  run.py [--with-collectors]
#   dashboard/scripts/start_dashboard.sh
# Docker (when deploy/ is present): make up / down / ps

.DEFAULT_GOAL := help

.PHONY: help runtime-stack runtime-stack-start runtime-stack-stop runtime-stack-status runtime-stack-restart

help: ## Show orchestration targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

runtime-stack: runtime-stack-start ## Start full local stack (alias)

runtime-stack-start: ## Start watchdog + run.py + dashboard API/UI
	./scripts/runtime_stack.sh start

runtime-stack-stop: ## Stop full local stack
	./scripts/runtime_stack.sh stop

runtime-stack-status: ## Status of stack processes / ports / feed
	./scripts/runtime_stack.sh status

runtime-stack-restart: ## Restart full local stack
	./scripts/runtime_stack.sh restart
