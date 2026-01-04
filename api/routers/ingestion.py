"""
Ingestion Router
Video download and upload endpoints
"""

import os
import re
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from loguru import logger

from api.config import settings
from api.services.video_service import VideoService


router = APIRouter()
video_service = VideoService()


# =============================================================================
# Models
# =============================================================================

class DownloadRequest(BaseModel):
    """Video download request"""
    url: HttpUrl
    custom_name: Optional[str] = None


class DownloadResponse(BaseModel):
    """Video download response"""
    success: bool
    message: str
    task_id: Optional[str] = None
    video_id: Optional[str] = None
    filename: Optional[str] = None


class UploadResponse(BaseModel):
    """Video upload response"""
    success: bool
    message: str
    video_id: str
    filename: str
    duration: Optional[float] = None
    resolution: Optional[str] = None


class VideoInfo(BaseModel):
    """Video information"""
    id: str
    filename: str
    path: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    size_mb: float
    created_at: datetime


class TaskStatus(BaseModel):
    """Background task status"""
    task_id: str
    status: str  # pending, processing, completed, failed
    progress: float
    message: str
    result: Optional[dict] = None


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/download", response_model=DownloadResponse)
async def download_video(request: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Download video from URL (YouTube, TikTok, etc.)
    
    - Downloads video using yt-dlp
    - Normalizes to standard format (720p, 30fps, H.264)
    - Stores in gallery/source_media
    """
    try:
        # Generate task ID
        import uuid
        task_id = str(uuid.uuid4())[:8]
        
        # Start background download
        background_tasks.add_task(
            video_service.download_and_normalize,
            str(request.url),
            request.custom_name,
            task_id
        )
        
        return DownloadResponse(
            success=True,
            message="Download started",
            task_id=task_id,
        )
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/sync", response_model=DownloadResponse)
async def download_video_sync(request: DownloadRequest):
    """
    Download video synchronously (blocking)
    For smaller videos or testing
    """
    try:
        result = await video_service.download_and_normalize_sync(
            str(request.url),
            request.custom_name
        )
        
        if result['success']:
            return DownloadResponse(
                success=True,
                message="Download complete",
                video_id=result['video_id'],
                filename=result['filename'],
            )
        else:
            raise HTTPException(status_code=400, detail=result['message'])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sync download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=UploadResponse)
async def upload_video(
    file: UploadFile = File(...),
    custom_name: Optional[str] = Form(None)
):
    """
    Upload and normalize video file
    
    Supported formats: MP4, MOV, AVI, MKV, WebM
    Max size: 2GB
    """
    # Validate file type
    allowed_types = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 
                     'video/x-matroska', 'video/webm']
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed: MP4, MOV, AVI, MKV, WebM"
        )
    
    try:
        result = await video_service.upload_and_normalize(file, custom_name)
        
        if result['success']:
            return UploadResponse(
                success=True,
                message="Upload complete",
                video_id=result['video_id'],
                filename=result['filename'],
                duration=result.get('duration'),
                resolution=result.get('resolution'),
            )
        else:
            raise HTTPException(status_code=400, detail=result['message'])
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Get status of background download task"""
    status = video_service.get_task_status(task_id)
    
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskStatus(**status)


@router.get("/videos", response_model=list[VideoInfo])
async def list_videos(
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at",
    order: str = "desc"
):
    """List all ingested videos"""
    videos = await video_service.list_videos(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        order=order
    )
    return videos


@router.get("/videos/{video_id}", response_model=VideoInfo)
async def get_video(video_id: str):
    """Get video information by ID"""
    video = await video_service.get_video(video_id)
    
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return video


@router.get("/videos/{video_id}/download")
async def download_video_file(video_id: str):
    """Download video file"""
    video = await video_service.get_video(video_id)
    
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return FileResponse(
        video['path'],
        media_type="video/mp4",
        filename=video['filename']
    )


@router.delete("/videos/{video_id}")
async def delete_video(video_id: str):
    """Delete video from gallery"""
    success = await video_service.delete_video(video_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return {"success": True, "message": "Video deleted"}


@router.put("/videos/{video_id}/rename")
async def rename_video(video_id: str, new_name: str):
    """Rename video"""
    success = await video_service.rename_video(video_id, new_name)
    
    if not success:
        raise HTTPException(status_code=404, detail="Video not found or rename failed")
    
    return {"success": True, "message": f"Video renamed to {new_name}"}

