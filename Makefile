.PHONY: help start stop restart logs clean build status

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

start: ## Start all services
	@./start.sh

stop: ## Stop all services
	@echo "Stopping all services..."
	@docker compose down
	@echo "✅ All services stopped"

restart: ## Restart all services
	@echo "Restarting all services..."
	@docker compose restart
	@echo "✅ All services restarted"

logs: ## View logs from all services
	@docker compose logs -f

logs-jupyter: ## View Jupyter logs
	@docker compose logs -f jupyter

logs-featuremeshd: ## View FeatureMeshd logs
	@docker compose logs -f featuremeshd

status: ## Show status of all services
	@docker compose ps

build: ## Rebuild all containers
	@echo "Rebuilding containers..."
	@docker compose build
	@echo "✅ Build complete"

rebuild: ## Rebuild and restart all services
	@echo "Rebuilding and restarting..."
	@docker compose up -d --build
	@echo "✅ Services rebuilt and restarted"

clean: ## Stop services and remove volumes
	@echo "⚠️  This will remove all data volumes!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker compose down -v; \
		echo "✅ Services stopped and volumes removed"; \
	else \
		echo "Cancelled"; \
	fi

shell-jupyter: ## Open shell in Jupyter container
	@docker exec -it featuremesh-jupyter /bin/bash

shell-postgres: ## Open PostgreSQL shell
	@docker exec -it featuremesh-postgres psql -U featuremesh -d featuremesh

shell-redis: ## Open Redis CLI
	@docker exec -it featuremesh-redis redis-cli

test-connections: ## Test all service connections
	@echo "Testing connections..."
	@echo -n "PostgreSQL: "
	@docker exec featuremesh-postgres pg_isready -U featuremesh && echo "✅" || echo "❌"
	@echo -n "Redis: "
	@docker exec featuremesh-redis redis-cli ping | grep -q PONG && echo "✅" || echo "❌"
	@echo -n "FeatureMeshd: "
	@curl -sf http://localhost:10090/health > /dev/null && echo "✅" || echo "❌"
	@echo -n "Jupyter: "
	@curl -sf http://localhost:8881/api > /dev/null && echo "✅" || echo "❌"
	@echo -n "FastAPI: "
	@curl -sf http://localhost:8010/health > /dev/null && echo "✅" || echo "❌"
	@echo -n "Trino: "
	@curl -sf http://localhost:8081/v1/info > /dev/null && echo "✅" || echo "❌"

