"""
Gallery Router
Browse and manage media library
"""

from pathlib import Path
from typing import Optional, List
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from loguru import logger

from api.config import settings
from api.services.gallery_service import GalleryService


router = APIRouter()
gallery_service = GalleryService()


# =============================================================================
# Models
# =============================================================================

class MediaType(str, Enum):
    """Media type enum"""
    SOURCE = "source"
    IMAGE = "image"
    VIDEO = "video"


class MediaItem(BaseModel):
    """Media item model"""
    id: str
    type: MediaType
    filename: str
    path: str
    size_mb: float
    created_at: datetime
    thumbnail_url: Optional[str] = None
    metadata: Optional[dict] = None


class GalleryStats(BaseModel):
    """Gallery statistics"""
    source_count: int
    source_size_mb: float
    images_count: int
    images_size_mb: float
    videos_count: int
    videos_size_mb: float
    total_size_mb: float


class PaginatedResponse(BaseModel):
    """Paginated response"""
    items: List[MediaItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/stats", response_model=GalleryStats)
async def get_gallery_stats():
    """Get gallery statistics"""
    return await gallery_service.get_stats()


@router.get("/source", response_model=PaginatedResponse)
async def list_source_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    sort_by: str = Query("created_at", regex="^(created_at|name|size)$"),
    order: str = Query("desc", regex="^(asc|desc)$")
):
    """List source media (ingested videos)"""
    return await gallery_service.list_media(
        media_type=MediaType.SOURCE,
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        order=order
    )


@router.get("/images", response_model=PaginatedResponse)
async def list_generated_images(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    sort_by: str = Query("created_at", regex="^(created_at|name|size)$"),
    order: str = Query("desc", regex="^(asc|desc)$")
):
    """List generated images"""
    return await gallery_service.list_media(
        media_type=MediaType.IMAGE,
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        order=order
    )


@router.get("/videos", response_model=PaginatedResponse)
async def list_generated_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    sort_by: str = Query("created_at", regex="^(created_at|name|size)$"),
    order: str = Query("desc", regex="^(asc|desc)$")
):
    """List generated videos"""
    return await gallery_service.list_media(
        media_type=MediaType.VIDEO,
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        order=order
    )


@router.get("/item/{media_type}/{item_id}", response_model=MediaItem)
async def get_media_item(media_type: MediaType, item_id: str):
    """Get specific media item details"""
    item = await gallery_service.get_item(media_type, item_id)
    
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")
    
    return item


@router.get("/item/{media_type}/{item_id}/file")
async def get_media_file(media_type: MediaType, item_id: str):
    """Download media file"""
    item = await gallery_service.get_item(media_type, item_id)
    
    if item is None:
        raise HTTPException(status_code=404, detail="Media item not found")
    
    # Determine media type for response
    if media_type == MediaType.IMAGE:
        content_type = "image/png"
    else:
        content_type = "video/mp4"
    
    return FileResponse(
        item['path'],
        media_type=content_type,
        filename=item['filename']
    )


@router.get("/item/{media_type}/{item_id}/thumbnail")
async def get_media_thumbnail(media_type: MediaType, item_id: str):
    """Get media thumbnail"""
    thumbnail_path = await gallery_service.get_thumbnail(media_type, item_id)
    
    if thumbnail_path is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    
    return FileResponse(
        thumbnail_path,
        media_type="image/jpeg"
    )


@router.delete("/item/{media_type}/{item_id}")
async def delete_media_item(media_type: MediaType, item_id: str):
    """Delete media item"""
    success = await gallery_service.delete_item(media_type, item_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Media item not found")
    
    return {"success": True, "message": "Item deleted"}


@router.put("/item/{media_type}/{item_id}/rename")
async def rename_media_item(media_type: MediaType, item_id: str, new_name: str):
    """Rename media item"""
    success = await gallery_service.rename_item(media_type, item_id, new_name)
    
    if not success:
        raise HTTPException(status_code=400, detail="Rename failed")
    
    return {"success": True, "message": f"Renamed to {new_name}"}


@router.post("/cleanup")
async def cleanup_temp():
    """Clean up temporary files"""
    deleted_count, freed_mb = await gallery_service.cleanup_temp()
    
    return {
        "success": True,
        "deleted_files": deleted_count,
        "freed_mb": round(freed_mb, 2)
    }


@router.get("/search")
async def search_gallery(
    query: str = Query(..., min_length=1),
    media_type: Optional[MediaType] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """Search across all gallery media"""
    return await gallery_service.search(
        query=query,
        media_type=media_type,
        page=page,
        page_size=page_size
    )

