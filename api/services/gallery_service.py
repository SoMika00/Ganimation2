"""
Gallery Service
Media library management
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

from loguru import logger

from api.config import settings


class MediaType(str, Enum):
    SOURCE = "source"
    IMAGE = "image"
    VIDEO = "video"


class GalleryService:
    """Gallery management service"""
    
    def __init__(self):
        self.source_dir = settings.source_media_dir
        self.images_dir = settings.generated_images_dir
        self.videos_dir = settings.generated_videos_dir
        self.temp_dir = settings.temp_dir
        
        # Ensure directories
        for d in [self.source_dir, self.images_dir, self.videos_dir, self.temp_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    def _get_dir_for_type(self, media_type: MediaType) -> Path:
        """Get directory for media type"""
        if media_type == MediaType.SOURCE:
            return self.source_dir
        elif media_type == MediaType.IMAGE:
            return self.images_dir
        elif media_type == MediaType.VIDEO:
            return self.videos_dir
        raise ValueError(f"Unknown media type: {media_type}")
    
    def _get_extension_for_type(self, media_type: MediaType) -> str:
        """Get file extension for media type"""
        if media_type == MediaType.IMAGE:
            return "*.png"
        return "*.mp4"
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get gallery statistics"""
        def get_dir_stats(path: Path, pattern: str):
            count = 0
            size = 0
            for f in path.glob(pattern):
                if f.is_file():
                    count += 1
                    size += f.stat().st_size
            return count, size / (1024 * 1024)
        
        source_count, source_size = get_dir_stats(self.source_dir, "*.mp4")
        images_count, images_size = get_dir_stats(self.images_dir, "*.png")
        videos_count, videos_size = get_dir_stats(self.videos_dir, "*.mp4")
        
        return {
            'source_count': source_count,
            'source_size_mb': round(source_size, 2),
            'images_count': images_count,
            'images_size_mb': round(images_size, 2),
            'videos_count': videos_count,
            'videos_size_mb': round(videos_size, 2),
            'total_size_mb': round(source_size + images_size + videos_size, 2)
        }
    
    async def list_media(
        self,
        media_type: MediaType,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc"
    ) -> Dict[str, Any]:
        """List media items with pagination"""
        directory = self._get_dir_for_type(media_type)
        extension = self._get_extension_for_type(media_type)
        
        items = []
        for path in directory.glob(extension):
            if search and search.lower() not in path.stem.lower():
                continue
            
            items.append({
                'id': path.stem,
                'type': media_type,
                'filename': path.name,
                'path': str(path),
                'size_mb': round(path.stat().st_size / (1024 * 1024), 2),
                'created_at': datetime.fromtimestamp(path.stat().st_mtime),
                'thumbnail_url': f"/api/v1/gallery/item/{media_type}/{path.stem}/thumbnail"
            })
        
        # Sort
        reverse = order == "desc"
        if sort_by == "created_at":
            items.sort(key=lambda x: x['created_at'], reverse=reverse)
        elif sort_by == "name":
            items.sort(key=lambda x: x['filename'].lower(), reverse=reverse)
        elif sort_by == "size":
            items.sort(key=lambda x: x['size_mb'], reverse=reverse)
        
        # Paginate
        total = len(items)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        
        return {
            'items': items[start:end],
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages
        }
    
    async def get_item(self, media_type: MediaType, item_id: str) -> Optional[Dict]:
        """Get specific media item"""
        directory = self._get_dir_for_type(media_type)
        extension = "png" if media_type == MediaType.IMAGE else "mp4"
        
        path = directory / f"{item_id}.{extension}"
        
        if not path.exists():
            # Try partial match
            for p in directory.glob(f"{item_id}*"):
                path = p
                break
            else:
                return None
        
        return {
            'id': path.stem,
            'type': media_type,
            'filename': path.name,
            'path': str(path),
            'size_mb': round(path.stat().st_size / (1024 * 1024), 2),
            'created_at': datetime.fromtimestamp(path.stat().st_mtime),
        }
    
    async def get_thumbnail(self, media_type: MediaType, item_id: str) -> Optional[str]:
        """Get or generate thumbnail for media item"""
        directory = self._get_dir_for_type(media_type)
        
        if media_type == MediaType.IMAGE:
            # For images, return the image itself
            path = directory / f"{item_id}.png"
            if path.exists():
                return str(path)
        else:
            # For videos, generate thumbnail
            thumb_path = self.temp_dir / f"thumb_{item_id}.jpg"
            
            if thumb_path.exists():
                return str(thumb_path)
            
            video_path = directory / f"{item_id}.mp4"
            if not video_path.exists():
                for p in directory.glob(f"{item_id}*.mp4"):
                    video_path = p
                    break
                else:
                    return None
            
            # Generate thumbnail
            import subprocess
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vframes', '1',
                '-q:v', '5',
                str(thumb_path)
            ]
            
            try:
                subprocess.run(cmd, capture_output=True, timeout=30)
                if thumb_path.exists():
                    return str(thumb_path)
            except:
                pass
        
        return None
    
    async def delete_item(self, media_type: MediaType, item_id: str) -> bool:
        """Delete media item"""
        directory = self._get_dir_for_type(media_type)
        extension = "png" if media_type == MediaType.IMAGE else "mp4"
        
        path = directory / f"{item_id}.{extension}"
        
        if not path.exists():
            for p in directory.glob(f"{item_id}*"):
                path = p
                break
            else:
                return False
        
        try:
            path.unlink()
            
            # Also delete thumbnail if exists
            thumb_path = self.temp_dir / f"thumb_{item_id}.jpg"
            if thumb_path.exists():
                thumb_path.unlink()
            
            return True
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return False
    
    async def rename_item(self, media_type: MediaType, item_id: str, new_name: str) -> bool:
        """Rename media item"""
        directory = self._get_dir_for_type(media_type)
        extension = "png" if media_type == MediaType.IMAGE else "mp4"
        
        path = directory / f"{item_id}.{extension}"
        
        if not path.exists():
            for p in directory.glob(f"{item_id}*"):
                path = p
                extension = path.suffix
                break
            else:
                return False
        
        try:
            import re
            safe_name = re.sub(r'[<>:"/\\|?*]', '', new_name)
            safe_name = re.sub(r'[\s]+', '_', safe_name).strip('._')[:100]
            
            new_path = directory / f"{safe_name}{extension}"
            path.rename(new_path)
            return True
        except Exception as e:
            logger.error(f"Rename error: {e}")
            return False
    
    async def cleanup_temp(self) -> tuple:
        """Clean up temporary files"""
        deleted = 0
        freed = 0
        
        for path in self.temp_dir.glob("*"):
            if path.is_file():
                try:
                    size = path.stat().st_size
                    path.unlink()
                    deleted += 1
                    freed += size
                except:
                    pass
        
        return deleted, freed / (1024 * 1024)
    
    async def search(
        self,
        query: str,
        media_type: Optional[MediaType] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """Search across gallery"""
        results = []
        
        types_to_search = [media_type] if media_type else list(MediaType)
        
        for mt in types_to_search:
            directory = self._get_dir_for_type(mt)
            extension = self._get_extension_for_type(mt)
            
            for path in directory.glob(extension):
                if query.lower() in path.stem.lower():
                    results.append({
                        'id': path.stem,
                        'type': mt,
                        'filename': path.name,
                        'path': str(path),
                        'size_mb': round(path.stat().st_size / (1024 * 1024), 2),
                        'created_at': datetime.fromtimestamp(path.stat().st_mtime),
                    })
        
        # Sort by relevance (name match) then by date
        results.sort(key=lambda x: (-x['filename'].lower().count(query.lower()), x['created_at']), reverse=True)
        
        # Paginate
        total = len(results)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        
        return {
            'items': results[start:end],
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'query': query
        }

