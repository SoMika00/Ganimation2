"""
System Router
Health checks, GPU status, system info
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Dict, List, Optional
import torch
import platform
import psutil

from api.config import settings


router = APIRouter()


# =============================================================================
# Models
# =============================================================================

class GPUInfo(BaseModel):
    """GPU information"""
    id: int
    name: str
    total_vram_gb: float
    used_vram_gb: float
    free_vram_gb: float
    temperature: Optional[int] = None
    utilization: Optional[int] = None


class SystemInfo(BaseModel):
    """System information"""
    platform: str
    python_version: str
    torch_version: str
    cuda_available: bool
    cuda_version: Optional[str]
    num_gpus: int
    gpus: List[GPUInfo]
    total_vram_gb: float
    is_h100: bool
    cpu_count: int
    memory_total_gb: float
    memory_available_gb: float


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    service: str
    version: str
    gpu_available: bool
    api_ready: bool


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/system/info", response_model=SystemInfo)
async def get_system_info(request: Request):
    """Get detailed system information"""
    
    gpus = []
    total_vram = 0
    is_h100 = False
    cuda_version = None
    
    if torch.cuda.is_available():
        cuda_version = torch.version.cuda
        
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            total = props.total_memory / (1024**3)
            allocated = torch.cuda.memory_allocated(i) / (1024**3)
            cached = torch.cuda.memory_reserved(i) / (1024**3)
            
            # Check for H100
            major, minor = torch.cuda.get_device_capability(i)
            if major >= 9:
                is_h100 = True
            
            gpus.append(GPUInfo(
                id=i,
                name=props.name,
                total_vram_gb=round(total, 2),
                used_vram_gb=round(cached, 2),
                free_vram_gb=round(total - cached, 2),
            ))
            total_vram += total
    
    memory = psutil.virtual_memory()
    
    return SystemInfo(
        platform=platform.platform(),
        python_version=platform.python_version(),
        torch_version=torch.__version__,
        cuda_available=torch.cuda.is_available(),
        cuda_version=cuda_version,
        num_gpus=len(gpus),
        gpus=gpus,
        total_vram_gb=round(total_vram, 2),
        is_h100=is_h100,
        cpu_count=psutil.cpu_count(),
        memory_total_gb=round(memory.total / (1024**3), 2),
        memory_available_gb=round(memory.available / (1024**3), 2),
    )


@router.get("/system/gpu", response_model=List[GPUInfo])
async def get_gpu_info():
    """Get GPU information"""
    gpus = []
    
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            total = props.total_memory / (1024**3)
            cached = torch.cuda.memory_reserved(i) / (1024**3)
            
            gpus.append(GPUInfo(
                id=i,
                name=props.name,
                total_vram_gb=round(total, 2),
                used_vram_gb=round(cached, 2),
                free_vram_gb=round(total - cached, 2),
            ))
    
    return gpus


@router.get("/system/health", response_model=HealthResponse)
async def health_check():
    """Detailed health check"""
    return HealthResponse(
        status="healthy",
        service="ganimation-api",
        version="1.0.0",
        gpu_available=torch.cuda.is_available(),
        api_ready=True,
    )


@router.post("/system/gpu/clear-cache")
async def clear_gpu_cache():
    """Clear GPU memory cache"""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        return {"message": "GPU cache cleared", "success": True}
    return {"message": "No GPU available", "success": False}


@router.get("/system/config")
async def get_config():
    """Get current configuration (non-sensitive)"""
    return {
        "video": {
            "target_fps": settings.video_target_fps,
            "target_width": settings.video_target_width,
            "target_height": settings.video_target_height,
            "crf": settings.video_crf,
        },
        "image_gen": {
            "lora_weight": settings.sdxl_lora_weight,
            "cfg_scale": settings.sdxl_cfg_scale,
            "steps": settings.sdxl_steps,
            "batch_size": settings.sdxl_batch_size,
        },
        "video_gen": {
            "num_frames": settings.wan_num_frames,
            "motion_strength": settings.wan_motion_strength,
            "rife_multiplier": settings.rife_multiplier,
        },
        "gpu": {
            "enable_tf32": settings.enable_tf32,
            "enable_flash_attention": settings.enable_flash_attention,
            "torch_dtype": settings.torch_dtype,
        },
    }

