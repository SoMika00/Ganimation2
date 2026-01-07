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
BOOTSTRAP_ONLY="0"

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
        --bootstrap-only)
            BOOTSTRAP_ONLY="1"
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
    echo "  --bootstrap-only: run model/node bootstrap then exit (no containers)"
    exit 0
fi

if [ "$MODE" = "docker" ]; then
    echo -e "${CYAN}🐳 Starting Docker stack (Studio + ComfyUI)...${NC}"

    export HOST_UID="$(id -u)"
    export HOST_GID="$(id -g)"

    if [ -f ".env" ]; then
        set -o allexport
        # shellcheck disable=SC1091
        source ".env"
        set +o allexport
    fi

    # Create persistent host directories
    mkdir -p \
        data/comfyui/{models,output,input,user,custom_nodes} \
        gallery/{source_media,generated_images,generated_videos} \
        temp \
        models

    # Ensure ComfyUI UI workflow directory exists (workflows are tracked directly in git)
    mkdir -p data/comfyui/user/default/workflows

    # Standard ComfyUI models layout (recommended)
    mkdir -p \
        data/comfyui/models/{checkpoints,loras,controlnet,vae,clip,clip_vision,upscale_models,embeddings,hypernetworks}

    mkdir -p \
        data/comfyui/models/{diffusion_models,text_encoders,sam2,grounding-dino,detection}

    mkdir -p data/comfyui/models/pulid

    AUTO_BOOTSTRAP="${AUTO_BOOTSTRAP:-1}"
    AUTO_DOWNLOAD_MODELS="${AUTO_DOWNLOAD_MODELS:-1}"
    AUTO_INSTALL_CUSTOM_NODES="${AUTO_INSTALL_CUSTOM_NODES:-1}"
    AUTO_INSTALL_VAP="${AUTO_INSTALL_VAP:-0}"

    BOOTSTRAP_WARNINGS=0

    download_if_missing() {
        local url="$1"
        local dest="$2"

        if [ -f "$dest" ]; then
            return 0
        fi

        mkdir -p "$(dirname "$dest")"
        echo -e "${BLUE}⬇️  Downloading: $(basename "$dest")${NC}"

        if command -v curl >/dev/null 2>&1; then
            local -a auth_args=()
            if [ -n "${HF_TOKEN:-}" ] && echo "$url" | grep -qi "huggingface.co"; then
                auth_args=(-H "Authorization: Bearer ${HF_TOKEN}")
            fi

            if ! curl -L --fail --retry 3 --retry-delay 2 "${auth_args[@]}" -o "${dest}.part" "$url"; then
                echo -e "${YELLOW}⚠️  Download failed for $(basename "$dest") (URL: $url)${NC}"
                rm -f "${dest}.part" 2>/dev/null || true
                return 1
            fi
        elif command -v wget >/dev/null 2>&1; then
            local -a auth_args=()
            if [ -n "${HF_TOKEN:-}" ] && echo "$url" | grep -qi "huggingface.co"; then
                auth_args=(--header="Authorization: Bearer ${HF_TOKEN}")
            fi

            if ! wget -q --show-progress "${auth_args[@]}" -O "${dest}.part" "$url"; then
                echo -e "${YELLOW}⚠️  Download failed for $(basename "$dest") (URL: $url)${NC}"
                rm -f "${dest}.part" 2>/dev/null || true
                return 1
            fi
        else
            echo -e "${YELLOW}⚠️  Missing downloader (curl or wget). Skipping auto-download of $(basename "$dest").${NC}"
            return 1
        fi

        mv "${dest}.part" "$dest"
        return 0
    }

    download_hf_if_missing() {
        local repo_id="$1"
        local repo_path="$2"
        local dest="$3"

        if [ -f "$dest" ]; then
            return 0
        fi

        mkdir -p "$(dirname "$dest")"
        echo -e "${BLUE}⬇️  Downloading: $(basename "$dest")${NC}"

        local url="https://huggingface.co/${repo_id}/resolve/main/${repo_path}"

        if command -v curl >/dev/null 2>&1; then
            local -a auth_args=()
            if [ -n "${HF_TOKEN:-}" ]; then
                auth_args=(-H "Authorization: Bearer ${HF_TOKEN}")
            fi

            if ! curl -L --fail --retry 3 --retry-delay 2 "${auth_args[@]}" -o "${dest}.part" "$url"; then
                echo -e "${YELLOW}⚠️  Download failed for $(basename "$dest") (HF: $repo_id/$repo_path)${NC}"
                rm -f "${dest}.part" 2>/dev/null || true
                return 1
            fi
        else
            echo -e "${YELLOW}⚠️  Missing downloader (curl). Skipping HF download of $(basename "$dest").${NC}"
            return 1
        fi

        mv "${dest}.part" "$dest"
        return 0
    }

    clone_if_missing() {
        local repo_url="$1"
        local dest_dir="$2"

        if [ -d "$dest_dir/.git" ] || [ -f "$dest_dir/__init__.py" ] || [ -f "$dest_dir/pyproject.toml" ]; then
            return 0
        fi

        mkdir -p "$(dirname "$dest_dir")"
        echo -e "${BLUE}🔌 Installing custom node: $(basename "$dest_dir")${NC}"

        if ! command -v git >/dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  git not found on host. Skipping install of $(basename "$dest_dir").${NC}"
            return 1
        fi

        rm -rf "$dest_dir" 2>/dev/null || true
        if ! git clone --depth 1 "$repo_url" "$dest_dir"; then
            echo -e "${YELLOW}⚠️  Failed to clone $repo_url${NC}"
            return 1
        fi

        return 0
    }

    if [ "$AUTO_BOOTSTRAP" = "1" ]; then
        if [ "$AUTO_INSTALL_CUSTOM_NODES" = "1" ]; then
            clone_if_missing "https://github.com/ltdrdata/ComfyUI-Manager.git" "data/comfyui/custom_nodes/ComfyUI-Manager" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/Fannovel16/comfyui_controlnet_aux.git" "data/comfyui/custom_nodes/comfyui_controlnet_aux" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/cubiq/PuLID_ComfyUI.git" "data/comfyui/custom_nodes/PuLID_ComfyUI" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            clone_if_missing "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git" "data/comfyui/custom_nodes/ComfyUI-VideoHelperSuite" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git" "data/comfyui/custom_nodes/ComfyUI-Frame-Interpolation" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/kijai/ComfyUI-segment-anything-2.git" "data/comfyui/custom_nodes/ComfyUI-segment-anything-2" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/brayevalerien/ComfyUI-resynthesizer.git" "data/comfyui/custom_nodes/ComfyUI-resynthesizer" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/chaojie/ComfyUI-RAFT.git" "data/comfyui/custom_nodes/ComfyUI-RAFT" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            clone_if_missing "https://github.com/kijai/ComfyUI-WanVideoWrapper.git" "data/comfyui/custom_nodes/ComfyUI-WanVideoWrapper" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git" "data/comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
            clone_if_missing "https://github.com/stuttlepress/ComfyUI-Wan-VACE-Prep.git" "data/comfyui/custom_nodes/ComfyUI-Wan-VACE-Prep" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
        fi

        if [ "$AUTO_INSTALL_VAP" = "1" ]; then
            if [ -d "data/comfyui/custom_nodes/ComfyUI-WanVideoWrapper/.git" ]; then
                ensure_git_branch "data/comfyui/custom_nodes/ComfyUI-WanVideoWrapper" "vap" || true
            else
                if command -v git >/dev/null 2>&1; then
                    rm -rf "data/comfyui/custom_nodes/ComfyUI-WanVideoWrapper" 2>/dev/null || true
                    git clone --depth 1 -b vap "https://github.com/kijai/ComfyUI-WanVideoWrapper.git" "data/comfyui/custom_nodes/ComfyUI-WanVideoWrapper" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
                else
                    BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
                fi
            fi
        fi

        if [ "$AUTO_DOWNLOAD_MODELS" = "1" ]; then
            download_if_missing \
                "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" \
                "data/comfyui/models/checkpoints/sd_xl_base_1.0.safetensors" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style/resolve/main/Studio%20Ghibli%20style.safetensors" \
                "data/comfyui/models/loras/ghibli_style_sdxl.safetensors" \
            || download_if_missing \
                "https://huggingface.co/ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style/resolve/main/Studio+Ghibli+style.safetensors" \
                "data/comfyui/models/loras/ghibli_style_sdxl.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/artificialguybr/StudioGhibli.Redmond-V2/resolve/main/StudioGhibli.Redmond-StdGBRRedmAF-StudioGhibli.safetensors" \
                "data/comfyui/models/loras/StudioGhibli.Redmond-StdGBRRedmAF-StudioGhibli.safetensors" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors" \
                "data/comfyui/models/controlnet/diffusers_xl_depth_full.safetensors" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors" \
                "data/comfyui/models/controlnet/diffusers_xl_canny_full.safetensors" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/guozinan/PuLID/resolve/main/pulid_v1.1.safetensors" \
                "data/comfyui/models/pulid/pulid_v1.1.safetensors" || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
                "data/comfyui/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" \
                "data/comfyui/models/vae/wan_2.1_vae.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors" \
                "data/comfyui/models/clip_vision/clip_vision_h.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors" \
                "data/comfyui/models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/Wan22Animate/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors" \
                "data/comfyui/models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" \
                "data/comfyui/models/vae/ae.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
                "data/comfyui/models/text_encoders/clip_l.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors" \
                "data/comfyui/models/text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Comfy-Org/flux1-kontext-dev_ComfyUI/resolve/main/split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors" \
                "data/comfyui/models/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_if_missing \
                "https://huggingface.co/Kontext-Style/Ghibli_lora/resolve/main/Ghibli_lora_weights.safetensors" \
                "data/comfyui/models/loras/Ghibli_lora_weights.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_hf_if_missing \
                "Kijai/WanVideo_comfy" \
                "LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16.safetensors" \
                "data/comfyui/models/loras/WanAnimate_relight_lora_fp16.safetensors" \
            || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            download_hf_if_missing \
                "Kijai/WanVideo_comfy" \
                "LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors" \
                "data/comfyui/models/loras/WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors" \
            || true

            AUTO_DOWNLOAD_WAN_MODELS="${AUTO_DOWNLOAD_WAN_MODELS:-0}"
            if [ "$AUTO_DOWNLOAD_WAN_MODELS" = "1" ]; then
                download_hf_if_missing \
                    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged" \
                    "split_files/diffusion_models/wan2.2_animate_14B_bf16.safetensors" \
                    "data/comfyui/models/diffusion_models/wan2.2_animate_14B_bf16.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_hf_if_missing \
                    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged" \
                    "split_files/diffusion_models/wan2.2_fun_control_high_noise_14B_bf16.safetensors" \
                    "data/comfyui/models/diffusion_models/wan2.2_fun_control_high_noise_14B_bf16.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_hf_if_missing \
                    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged" \
                    "split_files/diffusion_models/wan2.2_fun_control_low_noise_14B_bf16.safetensors" \
                    "data/comfyui/models/diffusion_models/wan2.2_fun_control_low_noise_14B_bf16.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_hf_if_missing \
                    "Comfy-Org/Wan_2.1_ComfyUI_repackaged" \
                    "split_files/diffusion_models/wan2.1_vace_14B_fp16.safetensors" \
                    "data/comfyui/models/diffusion_models/wan2.1_vace_14B_fp16.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_if_missing \
                    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/diffusion_models/wan2.1_vace_1.3B_fp16.safetensors" \
                    "data/comfyui/models/diffusion_models/wan2.1_vace_1.3B_fp16.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_if_missing \
                    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp16.safetensors" \
                    "data/comfyui/models/text_encoders/umt5_xxl_fp16.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_if_missing \
                    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors" \
                    "data/comfyui/models/loras/Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_if_missing \
                    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan21_CausVid_14B_T2V_lora_rank32.safetensors" \
                    "data/comfyui/models/loras/Wan21_CausVid_14B_T2V_lora_rank32.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                if [ "$AUTO_INSTALL_VAP" = "1" ]; then
                    download_if_missing \
                        "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Video-as-prompt/Wan2_1-I2V-14B-VAP_module_bf16.safetensors" \
                        "data/comfyui/models/diffusion_models/Video-as-prompt/Wan2_1-I2V-14B-VAP_module_bf16.safetensors" \
                    || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))
                fi

                download_hf_if_missing \
                    "Comfy-Org/Wan_2.2_ComfyUI_Repackaged" \
                    "split_files/vae/wan2.2_vae.safetensors" \
                    "data/comfyui/models/vae/wan2.2_vae.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

                download_hf_if_missing \
                    "Comfy-Org/Wan_2.1_ComfyUI_repackaged" \
                    "split_files/vae/wan_2.1_vae.safetensors" \
                    "data/comfyui/models/vae/wan_2.1_vae.safetensors" \
                || BOOTSTRAP_WARNINGS=$((BOOTSTRAP_WARNINGS+1))

            fi
        fi
    fi

    if [ "$AUTO_BOOTSTRAP" = "1" ] && [ "$BOOTSTRAP_WARNINGS" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Bootstrap completed with ${BOOTSTRAP_WARNINGS} warning(s).${NC}"
        echo -e "${YELLOW}   ComfyUI will still start, but some models/nodes may be missing.${NC}"
    fi

    if [ "$BOOTSTRAP_ONLY" = "1" ]; then
        echo -e "${GREEN}✅ Bootstrap-only complete. Not starting Docker containers.${NC}"
        exit 0
    fi

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

