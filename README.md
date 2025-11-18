# FeatureMesh Demos - Public Edition

A simplified, all-in-one Docker Compose setup for running FeatureMesh demos with all required services.

## What's Included

This setup includes all the services you need to run FeatureMesh demos:

- **FeatureMeshd** - The FeatureMesh daemon for query routing and serving
- **Jupyter Lab** - Interactive notebooks for demos and experimentation
- **PostgreSQL** - Relational database for feature storage
- **Redis** - Cache for online features
- **Trino** - Distributed SQL query engine for offline analytics
- **FastAPI** - HTTP endpoints

## Quick Start

Get up and running in 5 minutes!

### Prerequisites

- Docker Desktop installed and running
- FeatureMesh credentials (go to https://console.featuremesh.com to get them)

### Step 1: Get Your Credentials

You'll need:
- `FEATUREMESHD_IMAGE` - The FeatureMesh daemon Docker image URL
- `FEATUREMESH_REGISTRY_TOKEN` - Your service account token for featuremeshd access to registry
- `FEATUREMESH_IDENTITY_TOKEN` - Your identity token (optional, for project-specific access in notebooks)

### Step 2: Configure Environment

```bash
# Copy the example environment file
cp env.example .env

# Edit .env and add your credentials
nano .env  # or use your favorite editor
```

Update these lines in `.env`:
```bash
FEATUREMESHD_IMAGE=your-image-url-here
FEATUREMESH_REGISTRY_TOKEN=your-token-here # service account token
FEATUREMESH_IDENTITY_TOKEN=your-identity-token-here  # identity token
```

### Step 3: Start Everything

```bash
./start.sh
```

This will:
- Validate your Docker setup and credentials
- Pull all required Docker images
- Build the Jupyter container
- Start all services in the correct order
- Wait for health checks to pass

### Step 4: Access Jupyter Lab

Open your browser to:
```
http://localhost:8881/lab
```

This will automatically log you in to Jupyter Lab.

## Service Endpoints

Once running, you can access:

| Service | URL | Description |
|---------|-----|-------------|
| Jupyter Lab | http://localhost:8881 | Interactive notebooks |
| FeatureMesh Serving | http://localhost:10090 | HTTP API for queries |
| FeatureMesh Proxy | http://localhost:10080 | Proxy for data sources |
| Trino | http://localhost:8081 | Query engine UI |
| PostgreSQL | localhost:5433 | Database (user: featuremesh, pass: featuremesh) |
| Redis | localhost:6380 | Cache |
| FastAPI | http://localhost:8010 | HTTP endpoint |

## Verify Everything Works

### Check all services are running:
```bash
docker compose ps
```

You should see all services with "Healthy" status.

### Test FeatureMesh serving:
```bash
curl http://localhost:10090/health
```

Should return a healthy status.

### Check logs if needed:
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f featuremeshd
docker compose logs -f jupyter
```

## Managing Services

### View logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f featuremeshd
```

### Stop services
```bash
docker compose down
```

### Stop and remove data volumes
```bash
docker compose down -v
```

### Restart a service
```bash
docker compose restart [service-name]
```

### Rebuild Jupyter container
```bash
docker compose up -d --build jupyter
```

## Customization

### Port Configuration

You can customize ports in your `.env` file:

```bash
POSTGRES_PORT=5433
REDIS_PORT=6380
TRINO_PORT=8081
FASTAPI_PORT=8010
JUPYTER_PORT=8881
```

## Troubleshooting

### Port already in use

If you see "port is already allocated":
```bash
# Check what's using the port (example for 8881)
lsof -i :8881

# Either stop that service or change the port in .env
```

### Docker not running

```bash
# Make sure Docker Desktop is running
docker info
```

### Services fail to start

1. Check if ports are already in use:
   ```bash
   lsof -i :8881  # Check Jupyter port
   lsof -i :5433  # Check PostgreSQL port
   ```

2. Check service logs:
   ```bash
   docker compose logs featuremeshd
   ```

3. Try rebuilding:
   ```bash
   docker compose down
   docker compose up -d --build
   ```

### FeatureMeshd fails to start

- Verify your credentials in `.env` are correct
- Check you have access to the FeatureMesh registry:
  ```bash
  docker login europe-west1-docker.pkg.dev
  ```

### Jupyter can't connect to databases

- Ensure all services are healthy:
  ```bash
  docker compose ps
  ```
- All services should show "healthy" status

### Reset everything

```bash
# Stop and remove all containers, networks, and volumes
docker compose down -v

# Remove images (optional)
docker compose down --rmi all

# Start fresh
docker compose up -d
```

## Next Steps

1. **Explore the notebooks** in Jupyter Lab at http://localhost:8881
2. **Check the demos** in the `notebooks/demos` directory
3. **Read the FeatureMesh documentation** for advanced features

## Support

For issues or questions:
- Check the troubleshooting section above
- Review logs: `docker compose logs -f`
- Contact your FeatureMesh administrator

## License

See LICENSE file for details.
