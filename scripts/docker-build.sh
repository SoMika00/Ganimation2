#!/bin/bash
# ============================================================================
# Ganimation Studio - Docker Build Script
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}🐳 Building Ganimation Studio Docker images...${NC}"

# Create data directories
echo -e "${YELLOW}📁 Creating data directories...${NC}"
mkdir -p data/{gallery/source_media,gallery/generated_images,gallery/generated_videos,temp,models}

# Build images
echo -e "${YELLOW}🔨 Building API image...${NC}"
docker build -f docker/Dockerfile.api -t ganimation-api:latest .

echo -e "${YELLOW}🔨 Building Frontend image...${NC}"
docker build -f docker/Dockerfile.frontend -t ganimation-frontend:latest .

echo -e "${GREEN}✅ Build complete!${NC}"
echo ""
echo "Images built:"
docker images | grep ganimation

