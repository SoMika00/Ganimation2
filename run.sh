#!/bin/bash
#===============================================================================
# 🎬 Ganimation Studio - Launch Script
# Optimized for 2x NVIDIA H100 (160GB VRAM total)
#===============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="docker"
DETACHED=""
BUILD="--build"

for arg in "$@"; do
    case "$arg" in
        docker|local)
            MODE="$arg"
            ;;
        -d|--detached)
            DETACHED="-d"
            ;;
        --build)
            BUILD="--build"
            ;;
        --no-build)
            BUILD=""
            ;;
        --help|-h)
            MODE="--help"
            ;;
        *)
            ;;
    esac
done

if [ "$MODE" = "--help" ] || [ "$MODE" = "-h" ]; then
    echo "Usage: ./run.sh [docker|local]"
    echo "  docker (default): start ComfyUI + Studio via docker compose"
    echo "  local: start Streamlit locally (does NOT start ComfyUI)"
    echo "  -d, --detached: run in detached mode"
    echo "  --build: rebuild Docker images (default in docker mode; uses cache)"
    echo "  --no-build: start containers without rebuilding"
    exit 0
fi

if [ "$MODE" = "docker" ]; then
    echo -e "${CYAN}🐳 Starting Docker stack (Studio + ComfyUI)...${NC}"

    export HOST_UID="$(id -u)"
    export HOST_GID="$(id -g)"

    # Create persistent host directories
    mkdir -p \
        data/comfyui/{models,output,input,user,custom_nodes} \
        gallery/{source_media,generated_images,generated_videos} \
        temp \
        models

    if docker compose version &> /dev/null; then
        DOCKER_COMPOSE="docker compose"
    elif command -v docker-compose &> /dev/null; then
        DOCKER_COMPOSE="docker-compose"
    else
        echo -e "${RED}❌ Docker Compose not found. Install docker compose.${NC}"
        exit 1
    fi

    if ! docker info 2>/dev/null | grep -qi "nvidia"; then
        echo -e "${YELLOW}⚠️  NVIDIA runtime not detected in Docker. GPU may not be available inside containers.${NC}"
        echo -e "${YELLOW}   Install nvidia-container-toolkit and restart Docker.${NC}"
    fi

    $DOCKER_COMPOSE -f docker-compose.studio.yml up $DETACHED $BUILD
    exit 0
fi

echo -e "${PURPLE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           🎬 GANIMATION STUDIO                                ║"
echo "║           AI-Powered Video Editing Platform                   ║"
echo "║           Optimized for 2x H100 GPUs                          ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

#-------------------------------------------------------------------------------
# GPU Configuration for 2x H100
#-------------------------------------------------------------------------------
export CUDA_VISIBLE_DEVICES=0,1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Enable TF32 for faster computation on H100
export NVIDIA_TF32_OVERRIDE=1

# Optimal settings for H100
export TORCH_CUDA_ARCH_LIST="9.0"  # Hopper architecture

# Enable Flash Attention 2 (native on H100)
export FLASH_ATTENTION_SKIP_CUDA_BUILD=TRUE

# Disable memory fragmentation
export PYTORCH_NO_CUDA_MEMORY_CACHING=0

#-------------------------------------------------------------------------------
# Check System
#-------------------------------------------------------------------------------
echo -e "${CYAN}🔍 Checking system requirements...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found. Please install Python 3.9+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}✅ Python $PYTHON_VERSION${NC}"

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${RED}❌ FFmpeg not found. Installing...${NC}"
    sudo apt-get update && sudo apt-get install -y ffmpeg
fi
echo -e "${GREEN}✅ FFmpeg $(ffmpeg -version 2>&1 | head -n1 | cut -d' ' -f3)${NC}"

# Check NVIDIA GPUs
if command -v nvidia-smi &> /dev/null; then
    echo -e "${CYAN}🎮 GPU Configuration:${NC}"
    nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader | while read line; do
        echo -e "   ${GREEN}$line${NC}"
    done
    
    # Get total VRAM
    TOTAL_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | awk '{sum+=$1} END {print sum/1024}')
    echo -e "${GREEN}✅ Total VRAM: ${TOTAL_VRAM}GB${NC}"
else
    echo -e "${YELLOW}⚠️  nvidia-smi not found. GPU features may be limited.${NC}"
fi

#-------------------------------------------------------------------------------
# Virtual Environment
#-------------------------------------------------------------------------------
echo -e "\n${CYAN}🐍 Setting up Python environment...${NC}"

if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

source venv/bin/activate
echo -e "${GREEN}✅ Virtual environment activated${NC}"

#-------------------------------------------------------------------------------
# Install Dependencies
#-------------------------------------------------------------------------------
echo -e "\n${CYAN}📦 Checking dependencies...${NC}"

# Upgrade pip
pip install --upgrade pip -q

# Check if requirements are installed
if ! python -c "import streamlit" 2>/dev/null; then
    echo -e "${YELLOW}Installing requirements...${NC}"
    pip install -r requirements.txt
    
    # Install PyTorch with CUDA 12.1 for H100
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    
    # Install xformers for memory efficient attention
    pip install xformers
    
    # Install flash-attn for H100
    pip install flash-attn --no-build-isolation
    
    echo -e "${GREEN}✅ All dependencies installed${NC}"
else
    echo -e "${GREEN}✅ Dependencies already installed${NC}"
fi

# Install yt-dlp if missing
if ! command -v yt-dlp &> /dev/null; then
    pip install yt-dlp
fi
echo -e "${GREEN}✅ yt-dlp ready${NC}"

#-------------------------------------------------------------------------------
# Create Directories
#-------------------------------------------------------------------------------
echo -e "\n${CYAN}📁 Ensuring directory structure...${NC}"

mkdir -p gallery/source_media
mkdir -p gallery/generated_images
mkdir -p gallery/generated_videos
mkdir -p models/wan2.2
mkdir -p models/rife
mkdir -p models/realesrgan
mkdir -p temp

echo -e "${GREEN}✅ Directories ready${NC}"

#-------------------------------------------------------------------------------
# GPU Memory Check
#-------------------------------------------------------------------------------
echo -e "\n${CYAN}🧠 GPU Memory Status:${NC}"
python3 << 'EOF'
import torch

if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        total = props.total_memory / (1024**3)
        print(f"   GPU {i}: {props.name} - {total:.1f}GB VRAM")
    
    # Check compute capability
    major, minor = torch.cuda.get_device_capability(0)
    print(f"   Compute Capability: {major}.{minor}")
    
    if major >= 9:
        print("   ✅ H100 detected - Flash Attention 2 & TF32 enabled")
else:
    print("   ⚠️  No CUDA devices available")
EOF

#-------------------------------------------------------------------------------
# Launch Application
#-------------------------------------------------------------------------------
echo -e "\n${PURPLE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 Launching Ganimation Studio...${NC}"
echo -e "${PURPLE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${CYAN}   🌐 URL: ${NC}${GREEN}http://localhost:8501${NC}"
echo -e "${CYAN}   📡 Network: ${NC}${GREEN}http://$(hostname -I | awk '{print $1}'):8501${NC} (si besoin d'accès externe)"
echo ""
echo -e "${YELLOW}   Press Ctrl+C to stop the server${NC}"
echo ""

# Launch Streamlit with optimized settings
streamlit run app.py \
    --server.port 8501 \
    --server.address localhost \
    --server.maxUploadSize 2000 \
    --server.enableXsrfProtection false \
    --browser.gatherUsageStats false \
    --theme.base dark

