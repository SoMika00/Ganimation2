#!/bin/bash
# ============================================================================
# Ganimation Studio - Docker Start Script
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# Parse arguments
MODE="${1:-dev}"  # dev or prod
DETACHED="${2:-}"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           🐳 GANIMATION STUDIO - DOCKER                       ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker not found. Please install Docker.${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}❌ Docker Compose not found. Please install Docker Compose.${NC}"
    exit 1
fi

# Check NVIDIA Docker runtime
if ! docker info 2>/dev/null | grep -q "Runtimes.*nvidia"; then
    echo -e "${YELLOW}⚠️  NVIDIA Docker runtime not detected. GPU features may not work.${NC}"
    echo -e "${YELLOW}   Install nvidia-container-toolkit for GPU support.${NC}"
fi

# Create data directories
mkdir -p data/{gallery/source_media,gallery/generated_images,gallery/generated_videos,temp,models}

# Select compose file
if [ "$MODE" = "prod" ]; then
    COMPOSE_FILE="docker-compose.yml"
    echo -e "${GREEN}🚀 Starting in PRODUCTION mode${NC}"
else
    COMPOSE_FILE="docker-compose.dev.yml"
    echo -e "${GREEN}🚀 Starting in DEVELOPMENT mode${NC}"
fi

# Docker compose command (support both v1 and v2)
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# Start containers
echo -e "${CYAN}📦 Starting containers...${NC}"

if [ "$DETACHED" = "-d" ] || [ "$DETACHED" = "--detached" ]; then
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d --build
    
    echo ""
    echo -e "${GREEN}✅ Containers started in background${NC}"
    echo ""
    echo -e "${CYAN}Services:${NC}"
    echo -e "   Frontend: ${GREEN}http://localhost:8501${NC}"
    echo -e "   API:      ${GREEN}http://localhost:8000${NC}"
    echo -e "   API Docs: ${GREEN}http://localhost:8000/docs${NC}"
    echo ""
    echo -e "${YELLOW}Commands:${NC}"
    echo "   View logs:    $DOCKER_COMPOSE -f $COMPOSE_FILE logs -f"
    echo "   Stop:         $DOCKER_COMPOSE -f $COMPOSE_FILE down"
    echo "   Restart:      $DOCKER_COMPOSE -f $COMPOSE_FILE restart"
else
    echo ""
    echo -e "${CYAN}Services will be available at:${NC}"
    echo -e "   Frontend: ${GREEN}http://localhost:8501${NC}"
    echo -e "   API:      ${GREEN}http://localhost:8000${NC}"
    echo -e "   API Docs: ${GREEN}http://localhost:8000/docs${NC}"
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    echo ""
    
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" up --build
fi

