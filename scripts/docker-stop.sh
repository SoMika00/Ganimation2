#!/bin/bash
# ============================================================================
# Ganimation Studio - Docker Stop Script
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Docker compose command
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

echo "🛑 Stopping Ganimation Studio..."

# Stop all compose files
$DOCKER_COMPOSE -f docker-compose.yml down 2>/dev/null || true
$DOCKER_COMPOSE -f docker-compose.dev.yml down 2>/dev/null || true

echo "✅ Containers stopped"

# Optional: Remove volumes
if [ "$1" = "--clean" ] || [ "$1" = "-c" ]; then
    echo "🧹 Cleaning up volumes..."
    docker volume rm ganimation2_gallery_data 2>/dev/null || true
    docker volume rm ganimation2_temp_data 2>/dev/null || true
    docker volume rm ganimation2_models_data 2>/dev/null || true
    docker volume rm ganimation2_redis_data 2>/dev/null || true
    echo "✅ Volumes removed"
fi

