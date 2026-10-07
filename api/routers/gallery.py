"""
Gallery Router
Media management endpoints
"""

from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from api.config import settings
from api.services.gallery_service import GalleryService


router = APIRouter()
gallery_service = GalleryService()


# =============================================================================
# Models
# =============================================================================

class GalleryStats(BaseModel):
    """Gallery statistics"""
    source_count: int
    image_count: int
    video_count: int
    total_count: int
    total_size_bytes: int


class GalleryItem(BaseModel):
    """Gallery item"""
    id: str
    name: str
    type: str  # "image" or "video"
    path: str
    size_bytes: int
    created_at: Optional[str] = None


class BulkDownloadRequest(BaseModel):
    """Bulk download request"""
    ids: List[str] = Field(..., description="List of item IDs to download")


# =============================================================================
# Gallery Endpoints
# =============================================================================

@router.get("/stats", response_model=GalleryStats)
async def get_stats():
    """Get gallery statistics"""
    return gallery_service.get_stats()


@router.get("/source", response_model=List[GalleryItem])
async def list_source_media():
    """List source media"""
    return gallery_service.list_source_media()


@router.get("/images", response_model=List[GalleryItem])
async def list_images():
    """List generated images"""
    return gallery_service.list_images()


@router.get("/videos", response_model=List[GalleryItem])
async def list_videos():
    """List generated videos"""
    return gallery_service.list_videos()


@router.get("/file/{item_id}")
async def get_file(item_id: str):
    """Get a gallery file by ID"""
    item = gallery_service.get_item(item_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    media_type = "image/png" if item['type'] == 'image' else "video/mp4"

    return FileResponse(
        item['path'],
        media_type=media_type,
        filename=item['name'],
    )


@router.post("/download")
async def bulk_download(request: BulkDownloadRequest):
    """
    Bulk download gallery items as a ZIP archive.

    Accepts a list of item IDs and returns a streamed ZIP file containing
    the original filenames, preserving directory structure (`images/` or
    `videos/`).
    """
    if not request.ids:
        raise HTTPException(status_code=400, detail="No item IDs provided")

    # Validate all IDs exist and belong to generated images or videos
    items = []
    for item_id in request.ids:
        item = gallery_service.get_item(item_id)
        if item is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid item ID: {item_id}",
            )
        if item['type'] not in ('image', 'video'):
            raise HTTPException(
                status_code=400,
                detail=f"Item is not a generated image or video: {item_id}",
            )
        items.append(item)

    # Build the ZIP archive in memory (streamed)
    zip_bytes = gallery_service.build_zip(items)

    return StreamingResponse(
        zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="gallery_download.zip"',
        },
    )
