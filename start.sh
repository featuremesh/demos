#!/bin/bash
set -e

echo "🚀 Starting FeatureMesh Demos Environment"
echo "=========================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found. Creating from template..."
    cp .env.example .env
    echo "📝 Please edit .env file with your FeatureMesh credentials before continuing."
    echo "   Required: FEATUREMESH_REGISTRY_TOKEN and FEATUREMESHD_IMAGE"
    echo ""
    read -p "Press Enter after updating .env to continue, or Ctrl+C to exit..."
fi

# Check if required environment variables are set
source .env
if [ "$FEATUREMESH_REGISTRY_TOKEN" = "__YOUR_SERVICE_ACCOUNT_TOKEN__" ]; then
    echo "❌ Error: Please update FEATUREMESH_REGISTRY_TOKEN in .env file"
    exit 1
fi

echo "✅ Environment configured"
echo ""

# Create necessary directories
echo "📁 Creating data directories..."
mkdir -p jupyter/notebooks jupyter/files

echo "🐳 Starting Docker containers..."
echo ""

# Start services
docker compose up -d

echo ""
echo "⏳ Waiting for services to become healthy..."
echo "   This may take a few minutes on first run..."
echo ""

# Wait for all services to be healthy
max_wait=180
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    # Count services with "(healthy)" in their status
    healthy=$(docker compose ps 2>/dev/null | grep -c "(healthy)" || echo "0")
    # Count total running services (excluding header lines)
    total=$(docker compose ps --status running --quiet 2>/dev/null | wc -l | tr -d ' ')
    
    if [ "$healthy" -eq "$total" ] && [ "$total" -gt 0 ]; then
        echo "✅ All services are healthy!"
        break
    fi
    
    sleep 5
    elapsed=$((elapsed + 5))
    
    if [ $((elapsed % 15)) -eq 0 ]; then
        echo "   Still waiting... ($healthy/$total services healthy)"
    fi
done

if [ $elapsed -ge $max_wait ]; then
    echo "⚠️  Warning: Some services may not be healthy yet. Check status with: docker compose ps"
fi

echo ""
echo "=========================================="
echo "✅ FeatureMesh Demos Environment is Ready!"
echo "=========================================="
echo ""
echo "🌐 Access Points:"
echo "   Jupyter Lab:           http://localhost:${JUPYTER_PORT:-18881}/lab"
echo "   ⚠️  !! ATTENTION !! This notebook has no authentication. Do not expose port ${JUPYTER_PORT:-18881} to untrusted networks."
echo ""
echo "   FeatureMesh Serving:   http://localhost:10090"
echo "   Trino:                 localhost:${TRINO_PORT:-28080}"
echo "   PostgreSQL:            localhost:${POSTGRES_PORT:-25432}"
echo "   Redis:                 localhost:${REDIS_PORT:-26379}"
echo ""
echo "📝 Useful Commands:"
echo "   View logs:             docker compose logs -f"
echo "   Stop services:         docker compose down"
echo "   Restart:               docker compose restart"
echo "   Rebuild Jupyter:       docker compose up -d --build jupyter"
echo ""
echo "📚 Next Steps:"
echo "   1. Open Jupyter Lab at http://localhost:${JUPYTER_PORT:-18881}/lab"
echo "   2. Explore the demo notebooks in the notebooks/ directory"
echo "   3. Check the documentation at https://docs.featuremesh.com"
echo ""

