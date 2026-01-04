# 🐳 Ganimation Studio - Docker Documentation

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         NGINX (Port 80/443)                     │
│                      Reverse Proxy & Load Balancer              │
└─────────────────┬─────────────────────────┬─────────────────────┘
                  │                         │
                  ▼                         ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│      Frontend           │   │         API             │
│    (Streamlit:8501)     │   │    (FastAPI:8000)       │
│                         │   │                         │
│  • Web UI               │   │  • REST Endpoints       │
│  • API Client           │   │  • GPU Processing       │
│  • Live Preview         │   │  • Background Tasks     │
└─────────────────────────┘   └───────────┬─────────────┘
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                  ┌─────────────────┐   ┌─────────────────┐
                  │     Worker      │   │      Redis      │
                  │  (GPU Tasks)    │   │   (Task Queue)  │
                  │                 │   │                 │
                  │  • Image Gen    │   │  • Job Queue    │
                  │  • Video Gen    │   │  • Cache        │
                  │  • Post-proc    │   │  • Sessions     │
                  └─────────────────┘   └─────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │    2x NVIDIA H100     │
              │    (160GB VRAM)       │
              │                       │
              │  • SDXL + LoRA        │
              │  • ControlNet         │
              │  • Wan2.2             │
              │  • RIFE               │
              └───────────────────────┘
```

## Quick Start

### Prerequisites

```bash
# Docker & Docker Compose
curl -fsSL https://get.docker.com | sh

# NVIDIA Container Toolkit (for GPU support)
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
    sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Development Mode

```bash
# Clone and enter project
cd Ganimation2

# Copy environment file
cp env.example .env

# Start in development mode (with hot-reload)
./scripts/docker-start.sh dev

# Or with docker-compose directly
docker compose -f docker-compose.dev.yml up --build
```

### Production Mode

```bash
# Start in production mode (with nginx)
./scripts/docker-start.sh prod -d

# Or with docker-compose
docker compose -f docker-compose.yml --profile production up -d
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| **frontend** | 8501 | Streamlit Web UI |
| **api** | 8000 | FastAPI Backend |
| **worker** | - | Background GPU tasks |
| **redis** | 6379 | Task queue & cache |
| **nginx** | 80/443 | Reverse proxy (production) |

## URLs

- **Web UI**: http://localhost:8501
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Docker Commands

### Build

```bash
# Build all images
./scripts/docker-build.sh

# Build specific service
docker compose build api
docker compose build frontend
```

### Start/Stop

```bash
# Start (foreground)
./scripts/docker-start.sh dev

# Start (background)
./scripts/docker-start.sh dev -d

# Stop
./scripts/docker-stop.sh

# Stop and remove volumes
./scripts/docker-stop.sh --clean
```

### Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f frontend

# Last 100 lines
docker compose logs --tail=100 api
```

### Shell Access

```bash
# API container
docker compose exec api bash

# Frontend container
docker compose exec frontend bash

# Redis CLI
docker compose exec redis redis-cli
```

## GPU Configuration

### Verify GPU Access

```bash
# Check NVIDIA driver
nvidia-smi

# Check Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

### H100 Optimizations

The Docker configuration automatically enables:

- **TF32**: 8x faster matrix operations
- **BFloat16**: Native H100 precision
- **Flash Attention 2**: 3-4x faster attention
- **Multi-GPU**: Balanced distribution across both H100s

Environment variables in `docker-compose.yml`:

```yaml
environment:
  - CUDA_VISIBLE_DEVICES=0,1
  - NVIDIA_TF32_OVERRIDE=1
  - PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
  - TORCH_CUDA_ARCH_LIST=9.0
```

## Volumes

| Volume | Host Path | Container Path | Description |
|--------|-----------|----------------|-------------|
| gallery_data | ./data/gallery | /data/gallery | Media library |
| temp_data | ./data/temp | /data/temp | Temporary files |
| models_data | ./data/models | /data/models | AI models |
| redis_data | (managed) | /data | Redis persistence |

### Backup Volumes

```bash
# Backup gallery
docker run --rm -v ganimation2_gallery_data:/data -v $(pwd):/backup \
    alpine tar czf /backup/gallery-backup.tar.gz /data

# Restore gallery
docker run --rm -v ganimation2_gallery_data:/data -v $(pwd):/backup \
    alpine tar xzf /backup/gallery-backup.tar.gz -C /
```

## Configuration

### Environment Variables

Copy `env.example` to `.env` and customize:

```bash
cp env.example .env
nano .env
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| API_WORKERS | 2 | API worker processes |
| SDXL_STEPS | 30 | Image generation steps |
| SDXL_BATCH_SIZE | 4 | Batch size for H100 |
| WAN_NUM_FRAMES | 96 | Video frames (H100 optimized) |
| VIDEO_CRF | 16 | Video quality (lower = better) |

### Custom nginx.conf

Edit `docker/nginx.conf` for:
- SSL/HTTPS configuration
- Custom domain
- Rate limiting
- Caching

## Health Checks

```bash
# Check all services
docker compose ps

# API health
curl http://localhost:8000/health

# Frontend health
curl http://localhost:8501/_stcore/health

# GPU status
curl http://localhost:8000/api/v1/system/gpu
```

## Troubleshooting

### GPU Not Detected

```bash
# Check nvidia-container-toolkit
docker info | grep -i nvidia

# Reinstall toolkit
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Out of Memory

```bash
# Clear GPU cache via API
curl -X POST http://localhost:8000/api/v1/system/gpu/clear-cache

# Restart worker with fresh memory
docker compose restart worker
```

### Container Won't Start

```bash
# Check logs
docker compose logs api --tail=50

# Verify image built correctly
docker compose build --no-cache api

# Check disk space
df -h
```

### Port Already in Use

```bash
# Find process using port
sudo lsof -i :8501

# Kill process or change port in docker-compose.yml
```

## CI/CD Integration

### GitHub Actions

The `.github/workflows/ci.yml` provides:

1. **Lint**: Ruff, Black, MyPy checks
2. **Build**: Docker image build & push to GHCR
3. **Test**: Integration tests with Redis
4. **Deploy**: Production deployment (customizable)

### Manual Deployment

```bash
# Pull latest images
docker compose pull

# Restart with new images
docker compose up -d --force-recreate
```

## Security

### Production Checklist

- [ ] Change `SECRET_KEY` in `.env`
- [ ] Enable HTTPS in nginx
- [ ] Set `API_KEY` for API protection
- [ ] Configure firewall (only expose 80/443)
- [ ] Use Docker secrets for sensitive data
- [ ] Regular security updates

### Network Isolation

Services communicate via internal Docker network. Only nginx exposes external ports in production.

## Performance Tuning

### For 2x H100

The default configuration is optimized for 2x H100. Key settings:

```yaml
# docker-compose.yml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

### Memory Limits

Add memory limits if needed:

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 32G
```

### Redis Tuning

```yaml
redis:
  command: redis-server --appendonly yes --maxmemory 4gb --maxmemory-policy allkeys-lru
```

