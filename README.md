# 🎬 Ganimation Studio

**AI-Powered Video Editing Platform** - Transform your shorts into Ghibli-style animations

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-red.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ Features

- **📥 Ingestion** - Import videos via URL (YouTube Shorts, TikTok) or file upload
- **🎨 Image Studio** - Generate Ghibli-style frames with SDXL + ControlNet + LoRA
- **🎬 Video Studio** - Animate images with Wan2.2 + RIFE interpolation
- **🖼️ Gallery** - Organize source media, generated images, and videos
- **🔌 REST API** - Full FastAPI backend for integration
- **🐳 Docker Ready** - Production-ready containerized deployment

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
cd Ganimation2

# Start Studio (Streamlit) + ComfyUI
./run.sh
```

Access:
- **Studio (Streamlit)**: http://localhost:8501
- **ComfyUI UI**: http://localhost:8188

Persistent storage (host):
- `./gallery/` (source videos + generated outputs)
- `./temp/`
- `./models/` (non-ComfyUI models used by the app)
- `./data/comfyui/models/` (ComfyUI models: checkpoints / loras / controlnet / etc.)
- `./data/comfyui/custom_nodes/` (ComfyUI plugins)
- `./data/comfyui/user/` (ComfyUI workflows + settings)

### Option 2: Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
./run.sh local
```

Note: local mode does **not** start ComfyUI. If you run locally, start ComfyUI separately.

## 📁 Project Structure

```
Ganimation2/
├── app.py                    # Streamlit application
├── config.py                 # Configuration management
├── run.sh                    # Local run script
├── docker-compose.yml        # API/worker stack (advanced)
├── docker-compose.dev.yml    # API/worker stack (advanced)
├── docker-compose.studio.yml # Minimal Studio + ComfyUI
│
├── api/                      # FastAPI Backend
│   ├── main.py               # API entry point
│   ├── config.py             # API configuration
│   ├── routers/              # API endpoints
│   │   ├── ingestion.py      # Video import endpoints
│   │   ├── gallery.py        # Media management
│   │   ├── generation.py     # AI generation endpoints
│   │   └── system.py         # System & GPU info
│   └── services/             # Business logic
│       ├── video_service.py
│       ├── gallery_service.py
│       ├── generation_service.py
│       └── gpu_manager.py
│
├── views/                    # Streamlit views/pages
│   ├── ingestion.py          # Video import UI
│   ├── gallery.py            # Media browser UI
│   ├── image_studio.py       # Image generation UI
│   └── video_studio.py       # Video generation UI
│
├── utils/                    # Shared utilities
│   ├── video_processor.py    # FFmpeg operations
│   ├── image_generator.py    # SDXL pipeline
│   └── video_animator.py     # Wan2.2 pipeline
│
├── docker/                   # Docker configurations
│   ├── Dockerfile.api        # API image
│   ├── Dockerfile.frontend   # Frontend image
│   ├── nginx.conf            # Reverse proxy config
│   └── streamlit_config.toml
│
├── scripts/                  # Deployment scripts
│   ├── docker-build.sh
│   ├── docker-start.sh
│   └── docker-stop.sh
│
├── .github/workflows/        # CI/CD
│   └── ci.yml
│
├── data/                     # Data directories
│   ├── gallery/
│   │   ├── source_media/     # Imported videos
│   │   ├── generated_images/ # Ghibli frames
│   │   └── generated_videos/ # Animated outputs
│   ├── temp/                 # Temporary files
│   └── models/               # AI models
│
└── requirements*.txt         # Dependencies
```

## 🐳 Docker Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    NGINX (80/443)                           │
│                   Reverse Proxy                             │
└─────────────────┬───────────────────┬───────────────────────┘
                  │                   │
        ┌─────────▼─────────┐ ┌───────▼───────┐
        │    Frontend       │ │     API       │
        │  (Streamlit)      │ │  (FastAPI)    │
        │    :8501          │ │    :8000      │
        └───────────────────┘ └───────┬───────┘
                                      │
                          ┌───────────┼───────────┐
                          │           │           │
                  ┌───────▼───┐ ┌─────▼─────┐ ┌───▼───┐
                  │  Worker   │ │   Redis   │ │ GPUs  │
                  │ (Tasks)   │ │  (Queue)  │ │2xH100 │
                  └───────────┘ └───────────┘ └───────┘
```

## 🔌 API Endpoints

### Ingestion
- `POST /api/v1/ingestion/download` - Download video from URL
- `POST /api/v1/ingestion/upload` - Upload video file
- `GET /api/v1/ingestion/videos` - List all videos

### Gallery
- `GET /api/v1/gallery/stats` - Gallery statistics
- `GET /api/v1/gallery/source` - List source media
- `GET /api/v1/gallery/images` - List generated images
- `GET /api/v1/gallery/videos` - List generated videos

### Generation
- `POST /api/v1/generation/image` - Generate Ghibli image
- `POST /api/v1/generation/video` - Generate animated video
- `GET /api/v1/generation/tasks` - List generation tasks
- `GET /api/v1/generation/tasks/{id}` - Get task status

### System
- `GET /api/v1/system/info` - System information
- `GET /api/v1/system/gpu` - GPU status
- `POST /api/v1/system/gpu/clear-cache` - Clear GPU memory

## 🎨 Generation Pipelines

### Image Generation (Ghibli Style)

| Component | Model | Purpose |
|-----------|-------|---------|
| Base | SDXL 1.0 | High-quality generation |
| Style | ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style | Ghibli aesthetic |
| Structure | ControlNet (Depth/Canny) | Preserve source |

**Settings (H100 optimized):**
- Steps: 30
- CFG: 5.0
- LoRA Weight: 0.75
- Batch Size: 4

Implementation note:
- The ComfyUI workflow is generated dynamically in `utils/comfyui_client.py` and executed via the ComfyUI HTTP API.
- That means you won't see a pre-saved graph in ComfyUI unless you build/import one yourself.

### Video Generation

```
Generated Image + Source Video
            ↓
    Wan2.2 Animate Control
            ↓
    RIFE 4x Interpolation
            ↓
    Optional Upscale
            ↓
    Audio Merge + Encode
            ↓
        Output Video
```

## 🖥️ Hardware Optimization

### 2x NVIDIA H100 (160GB VRAM)

Automatic optimizations enabled:
- ✅ TF32 Tensor Cores
- ✅ BFloat16 precision
- ✅ Flash Attention 2
- ✅ torch.compile
- ✅ Multi-GPU distribution
- ✅ No memory offloading needed

## 📋 Configuration

### Environment Variables

```bash
# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=2

# GPU
CUDA_VISIBLE_DEVICES=0,1
NVIDIA_TF32_OVERRIDE=1

# Generation
SDXL_STEPS=30
SDXL_BATCH_SIZE=4
WAN_NUM_FRAMES=96
RIFE_MULTIPLIER=4
```

See `env.example` for full configuration.

## 🔧 Development

### Local API Development

```bash
cd Ganimation2
source venv/bin/activate

# Run API with hot-reload
uvicorn api.main:app --reload --port 8000

# Run Frontend
streamlit run app.py
```

### Docker Development

```bash
# Start with hot-reload
./scripts/docker-start.sh dev

# View logs
docker compose -f docker-compose.dev.yml logs -f

# Rebuild after changes
docker compose -f docker-compose.dev.yml up --build
```

## 🚢 Production Deployment

```bash
# Build images
./scripts/docker-build.sh

# Start production stack (with nginx)
./scripts/docker-start.sh prod -d

# Check status
docker compose ps
docker compose logs -f
```

## 📚 Documentation

- [Docker Guide](DOCKER.md) - Detailed Docker documentation
- [API Docs](http://localhost:8000/docs) - Interactive API documentation
- [ReDoc](http://localhost:8000/redoc) - Alternative API docs

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- [Stability AI](https://stability.ai/) - SDXL
- [ntc-ai](https://huggingface.co/ntc-ai) - Ghibli LoRA
- [RIFE](https://github.com/megvii-research/ECCV2022-RIFE) - Frame interpolation
- [FastAPI](https://fastapi.tiangolo.com/) - API framework
- [Streamlit](https://streamlit.io/) - UI framework
