"""
Generation Router
Image and video generation endpoints
"""

from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from loguru import logger

from api.config import settings
from api.services.generation_service import GenerationService


router = APIRouter()
generation_service = GenerationService()


# =============================================================================
# Models
# =============================================================================

class ImageGenerationRequest(BaseModel):
    """Image generation request"""
    video_id: str = Field(..., description="Source video ID")
    frame_index: int = Field(0, ge=0, description="Frame index to use")
    
    # SDXL Settings
    lora_weight: float = Field(0.75, ge=0.0, le=1.5)
    cfg_scale: float = Field(5.0, ge=1.0, le=15.0)
    steps: int = Field(30, ge=10, le=50)
    seed: int = Field(-1, ge=-1)
    
    # ControlNet
    controlnet_type: str = Field("depth", regex="^(depth|canny)$")
    controlnet_strength: float = Field(0.6, ge=0.0, le=1.0)
    
    # Output
    num_images: int = Field(1, ge=1, le=4, description="Number of images to generate")


class ImageGenerationResponse(BaseModel):
    """Image generation response"""
    success: bool
    message: str
    task_id: Optional[str] = None
    images: Optional[List[dict]] = None


class VideoGenerationRequest(BaseModel):
    """Video generation request"""
    image_id: str = Field(..., description="Generated image ID")
    source_video_id: str = Field(..., description="Source video ID for motion")
    
    # Wan2.2 Settings
    num_frames: int = Field(96, ge=16, le=256)
    motion_strength: float = Field(0.7, ge=0.0, le=1.0)
    guidance_scale: float = Field(7.5, ge=1.0, le=20.0)
    num_inference_steps: int = Field(40, ge=10, le=100)
    
    # Relighting
    use_relighting: bool = Field(False)
    relight_strength: float = Field(0.5, ge=0.0, le=1.0)
    
    # Post-processing
    use_rife: bool = Field(True)
    rife_multiplier: int = Field(4, ge=1, le=8)
    use_upscale: bool = Field(False)
    merge_audio: bool = Field(True)
    
    # Output
    output_fps: int = Field(30, ge=24, le=60)


class VideoGenerationResponse(BaseModel):
    """Video generation response"""
    success: bool
    message: str
    task_id: Optional[str] = None
    video_id: Optional[str] = None


class FrameExtractionRequest(BaseModel):
    """Frame extraction request"""
    video_id: str
    num_frames: int = Field(10, ge=1, le=50)


class FrameExtractionResponse(BaseModel):
    """Frame extraction response"""
    success: bool
    frames: List[dict]


class GenerationTask(BaseModel):
    """Generation task status"""
    task_id: str
    type: str  # "image" or "video"
    status: str  # pending, processing, completed, failed
    progress: float
    message: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[dict] = None
    error: Optional[str] = None


# =============================================================================
# Image Generation Endpoints
# =============================================================================

@router.post("/image", response_model=ImageGenerationResponse)
async def generate_image(request: ImageGenerationRequest, background_tasks: BackgroundTasks):
    """
    Generate Ghibli-style image from video frame
    
    Pipeline: SDXL + ControlNet + LoRA Ghibli
    Optimized for H100 with batch generation
    """
    try:
        task_id = await generation_service.queue_image_generation(request.dict())
        
        return ImageGenerationResponse(
            success=True,
            message="Image generation started",
            task_id=task_id,
        )
        
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image/sync", response_model=ImageGenerationResponse)
async def generate_image_sync(request: ImageGenerationRequest):
    """
    Generate image synchronously (blocking)
    For testing or single image generation
    """
    try:
        result = await generation_service.generate_image_sync(request.dict())
        
        if result['success']:
            return ImageGenerationResponse(
                success=True,
                message="Generation complete",
                images=result['images'],
            )
        else:
            raise HTTPException(status_code=400, detail=result['message'])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sync image generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/frames/extract", response_model=FrameExtractionResponse)
async def extract_frames(request: FrameExtractionRequest):
    """Extract frames from video for selection"""
    try:
        frames = await generation_service.extract_frames(
            request.video_id,
            request.num_frames
        )
        
        return FrameExtractionResponse(
            success=True,
            frames=frames
        )
        
    except Exception as e:
        logger.error(f"Frame extraction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frames/{video_id}/{frame_index}")
async def get_frame(video_id: str, frame_index: int):
    """Get specific frame as image"""
    frame_path = await generation_service.get_frame(video_id, frame_index)
    
    if frame_path is None:
        raise HTTPException(status_code=404, detail="Frame not found")
    
    return FileResponse(
        frame_path,
        media_type="image/png"
    )


# =============================================================================
# Video Generation Endpoints
# =============================================================================

@router.post("/video", response_model=VideoGenerationResponse)
async def generate_video(request: VideoGenerationRequest, background_tasks: BackgroundTasks):
    """
    Generate animated video from image
    
    Pipeline: Wan2.2 Animate Control + RIFE + Optional Upscale
    """
    try:
        task_id = await generation_service.queue_video_generation(request.dict())
        
        return VideoGenerationResponse(
            success=True,
            message="Video generation started",
            task_id=task_id,
        )
        
    except Exception as e:
        logger.error(f"Video generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Task Management Endpoints
# =============================================================================

@router.get("/tasks", response_model=List[GenerationTask])
async def list_tasks(
    status: Optional[str] = Query(None, regex="^(pending|processing|completed|failed)$"),
    type: Optional[str] = Query(None, regex="^(image|video)$"),
    limit: int = Query(20, ge=1, le=100)
):
    """List generation tasks"""
    return await generation_service.list_tasks(
        status=status,
        task_type=type,
        limit=limit
    )


@router.get("/tasks/{task_id}", response_model=GenerationTask)
async def get_task(task_id: str):
    """Get task status and result"""
    task = await generation_service.get_task(task_id)
    
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """Cancel pending task"""
    success = await generation_service.cancel_task(task_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel task")
    
    return {"success": True, "message": "Task cancelled"}


# =============================================================================
# Model Management Endpoints
# =============================================================================

@router.get("/models/status")
async def get_models_status():
    """Get status of loaded models"""
    return await generation_service.get_models_status()


@router.post("/models/load")
async def load_models(model_type: str = Query(..., regex="^(sdxl|wan2|all)$")):
    """Pre-load models into GPU memory"""
    try:
        result = await generation_service.load_models(model_type)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/unload")
async def unload_models():
    """Unload models from GPU memory"""
    await generation_service.unload_models()
    return {"success": True, "message": "Models unloaded"}


# =============================================================================
# Settings Endpoints
# =============================================================================

@router.get("/settings/presets")
async def get_presets():
    """Get available generation presets"""
    return {
        "image": {
            "quality": {
                "name": "High Quality",
                "steps": 35,
                "cfg_scale": 5.5,
                "lora_weight": 0.8,
            },
            "balanced": {
                "name": "Balanced",
                "steps": 25,
                "cfg_scale": 5.0,
                "lora_weight": 0.75,
            },
            "fast": {
                "name": "Fast",
                "steps": 15,
                "cfg_scale": 4.5,
                "lora_weight": 0.7,
            },
        },
        "video": {
            "quality": {
                "name": "High Quality",
                "num_frames": 128,
                "num_inference_steps": 50,
                "rife_multiplier": 4,
            },
            "balanced": {
                "name": "Balanced",
                "num_frames": 96,
                "num_inference_steps": 40,
                "rife_multiplier": 2,
            },
            "fast": {
                "name": "Fast",
                "num_frames": 48,
                "num_inference_steps": 25,
                "rife_multiplier": 2,
            },
        },
    }

