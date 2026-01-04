#!/bin/bash
# ============================================================================
# Download models for ComfyUI + Ganimation
# ============================================================================

set -e

COMFYUI_DIR="/home/mika/ComfyUI"
MODELS_DIR="$COMFYUI_DIR/models"

echo "🎬 Downloading models for Ganimation Studio..."
echo ""

# Check if ComfyUI exists
if [ ! -d "$COMFYUI_DIR" ]; then
    echo "❌ ComfyUI not found at $COMFYUI_DIR"
    exit 1
fi

# Create directories
mkdir -p "$MODELS_DIR/checkpoints"
mkdir -p "$MODELS_DIR/loras"
mkdir -p "$MODELS_DIR/controlnet"

# ============================================================================
# SDXL Base Model
# ============================================================================
echo "📥 Downloading SDXL Base 1.0..."
if [ ! -f "$MODELS_DIR/checkpoints/sd_xl_base_1.0.safetensors" ]; then
    wget -q --show-progress -O "$MODELS_DIR/checkpoints/sd_xl_base_1.0.safetensors" \
        "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
    echo "✅ SDXL Base downloaded"
else
    echo "✅ SDXL Base already exists"
fi

# ============================================================================
# Ghibli LoRA
# ============================================================================
echo ""
echo "📥 Downloading Ghibli Style LoRA..."
if [ ! -f "$MODELS_DIR/loras/ghibli_style_sdxl.safetensors" ]; then
    wget -q --show-progress -O "$MODELS_DIR/loras/ghibli_style_sdxl.safetensors" \
        "https://huggingface.co/ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style/resolve/main/ghibli_style.safetensors"
    echo "✅ Ghibli LoRA downloaded"
else
    echo "✅ Ghibli LoRA already exists"
fi

# ============================================================================
# ControlNet Depth (SDXL)
# ============================================================================
echo ""
echo "📥 Downloading ControlNet Depth (SDXL)..."
if [ ! -f "$MODELS_DIR/controlnet/diffusers_xl_depth_full.safetensors" ]; then
    wget -q --show-progress -O "$MODELS_DIR/controlnet/diffusers_xl_depth_full.safetensors" \
        "https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors"
    echo "✅ ControlNet Depth downloaded"
else
    echo "✅ ControlNet Depth already exists"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "=============================================="
echo "✅ All models downloaded!"
echo ""
echo "Models location: $MODELS_DIR"
echo ""
echo "To start ComfyUI:"
echo "  cd $COMFYUI_DIR"
echo "  python main.py --listen --port 8188"
echo ""
echo "Then access Ganimation at:"
echo "  http://localhost:8501"
echo "=============================================="

