#!/bin/bash
# ============================================================================
# Start Ganimation Studio + ComfyUI
# ============================================================================

set -e

echo "🎬 Starting Ganimation Studio..."
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

GANIMATION_DIR="/home/mika/Ganimation2"
COMFYUI_DIR="/home/mika/ComfyUI"

# ============================================================================
# Check ComfyUI
# ============================================================================
if [ ! -d "$COMFYUI_DIR" ]; then
    echo -e "${RED}❌ ComfyUI not found at $COMFYUI_DIR${NC}"
    echo "Install it first with: git clone https://github.com/comfyanonymous/ComfyUI.git"
    exit 1
fi

# ============================================================================
# Check Models
# ============================================================================
MODELS_OK=true

if [ ! -f "$COMFYUI_DIR/models/checkpoints/sd_xl_base_1.0.safetensors" ]; then
    echo -e "${YELLOW}⚠️  SDXL model not found${NC}"
    MODELS_OK=false
fi

if [ ! -f "$COMFYUI_DIR/models/loras/ghibli_style_sdxl.safetensors" ]; then
    echo -e "${YELLOW}⚠️  Ghibli LoRA not found${NC}"
    MODELS_OK=false
fi

if [ "$MODELS_OK" = false ]; then
    echo ""
    echo -e "${CYAN}Run this to download models:${NC}"
    echo "  cd $GANIMATION_DIR && ./scripts/download_models.sh"
    echo ""
fi

# ============================================================================
# Kill existing processes
# ============================================================================
echo "🧹 Cleaning up existing processes..."
pkill -f "python main.py" 2>/dev/null || true
pkill -f "streamlit run" 2>/dev/null || true
sleep 2

# ============================================================================
# Environment for H100
# ============================================================================
export CUDA_VISIBLE_DEVICES=0,1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export NVIDIA_TF32_OVERRIDE=1
export TORCH_CUDA_ARCH_LIST="9.0"

# ============================================================================
# Start ComfyUI (background)
# ============================================================================
echo ""
echo -e "${GREEN}🚀 Starting ComfyUI on port 8188...${NC}"
cd "$COMFYUI_DIR"
nohup python main.py --listen --port 8188 --cuda-device 0 > /tmp/comfyui.log 2>&1 &
COMFYUI_PID=$!
echo "   PID: $COMFYUI_PID"
echo "   Log: /tmp/comfyui.log"

# Wait for ComfyUI to start
echo "   Waiting for ComfyUI to initialize..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo -e "   ${GREEN}✅ ComfyUI ready!${NC}"
        break
    fi
    sleep 1
    echo -n "."
done
echo ""

# ============================================================================
# Start Streamlit (foreground)
# ============================================================================
echo ""
echo -e "${GREEN}🌐 Starting Ganimation Studio on port 8501...${NC}"
echo ""
echo "=============================================="
echo -e "${CYAN}Access the app at:${NC}"
echo -e "  ${GREEN}http://localhost:8501${NC}"
echo ""
echo -e "${CYAN}ComfyUI direct access:${NC}"
echo -e "  ${GREEN}http://localhost:8188${NC}"
echo "=============================================="
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

cd "$GANIMATION_DIR"
streamlit run app.py \
    --server.port 8501 \
    --server.address localhost \
    --browser.gatherUsageStats false

# ============================================================================
# Cleanup on exit
# ============================================================================
cleanup() {
    echo ""
    echo "🛑 Stopping services..."
    pkill -f "python main.py" 2>/dev/null || true
    pkill -f "streamlit run" 2>/dev/null || true
    echo "👋 Goodbye!"
}

trap cleanup EXIT

