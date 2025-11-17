# Load environment variables from .env file if it exists
set dotenv-load := true

# Show available recipes
default:
    @just --list

# Start all services
[group('services')]
start:
    @./start.sh

# Stop all services
[group('services')]
stop:
    @echo "Stopping all services..."
    @docker compose down
    @echo "✅ All services stopped"

# Restart all services
[group('services')]
restart:
    @echo "Restarting all services..."
    @docker compose restart
    @echo "✅ All services restarted"

# View logs from all services
[group('logs')]
logs:
    @docker compose logs -f

# View Jupyter logs
[group('logs')]
logs-jupyter:
    @docker compose logs -f jupyter

# View FeatureMeshd logs
[group('logs')]
logs-featuremeshd:
    @docker compose logs -f featuremeshd

# Show status of all services
[group('services')]
status:
    @docker compose ps

# Rebuild all containers
[group('build')]
build:
    @echo "Rebuilding containers..."
    @docker compose build
    @echo "✅ Build complete"

# Rebuild and restart all services
[group('build')]
rebuild:
    @echo "Rebuilding and restarting..."
    @docker compose up -d --build
    @echo "✅ Services rebuilt and restarted"

# Stop services and remove volumes
[group('services')]
clean:
    #!/bin/bash
    echo "⚠️  This will remove all data volumes!"
    read -p "Are you sure? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker compose down -v
        echo "✅ Services stopped and volumes removed"
    else
        echo "Cancelled"
    fi

# Open shell in Jupyter container
[group('shell')]
shell-jupyter:
    @docker exec -it featuremesh-jupyter /bin/bash

# Open PostgreSQL shell
[group('shell')]
shell-postgres:
    @docker exec -it featuremesh-postgres psql -U featuremesh -d featuremesh

# Open Redis CLI
[group('shell')]
shell-redis:
    @docker exec -it featuremesh-redis redis-cli

# Test all service connections
[group('util')]
test-connections:
    #!/bin/bash
    echo "Testing connections..."
    echo -n "PostgreSQL: "
    docker exec featuremesh-postgres pg_isready -U featuremesh && echo "✅" || echo "❌"
    echo -n "Redis: "
    docker exec featuremesh-redis redis-cli ping | grep -q PONG && echo "✅" || echo "❌"
    echo -n "FeatureMeshd: "
    curl -sf http://localhost:10090/health > /dev/null && echo "✅" || echo "❌"
    echo -n "Jupyter: "
    curl -sf http://localhost:8881/api > /dev/null && echo "✅" || echo "❌"
    echo -n "FastAPI: "
    curl -sf http://localhost:8010/health > /dev/null && echo "✅" || echo "❌"
    echo -n "Trino: "
    curl -sf http://localhost:8081/v1/info > /dev/null && echo "✅" || echo "❌"

