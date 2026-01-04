"""
Video Service
Handles video download, upload, and processing
"""

import os
import re
import json
import uuid
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import UploadFile
from loguru import logger
import aiofiles

from api.config import settings


class VideoService:
    """Video processing service"""
    
    def __init__(self):
        self.source_dir = settings.source_media_dir
        self.temp_dir = settings.temp_dir
        self.tasks: Dict[str, Dict] = {}
        
        # Ensure directories exist
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    # =========================================================================
    # Download Operations
    # =========================================================================
    
    async def download_and_normalize_sync(
        self,
        url: str,
        custom_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Download and normalize video synchronously"""
        try:
            # Generate video ID
            video_id = str(uuid.uuid4())[:8]
            
            # Get video title if no custom name
            if not custom_name:
                custom_name = await self._get_video_title(url)
            
            # Sanitize name
            safe_name = self._sanitize_filename(custom_name)
            
            # Download raw video
            raw_path = self.temp_dir / f"{video_id}_raw.mp4"
            
            logger.info(f"Downloading: {url}")
            
            # Force H264 codec (avoid AV1 which needs special decoder)
            download_cmd = [
                'yt-dlp',
                '-f', 'bestvideo[vcodec^=avc]+bestaudio/best[vcodec^=avc]/bestvideo+bestaudio/best',
                '--merge-output-format', 'mp4',
                '-o', str(raw_path),
                '--no-playlist',
                url
            ]
            
            process = await asyncio.create_subprocess_exec(
                *download_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0 or not raw_path.exists():
                return {
                    'success': False,
                    'message': f"Download failed: {stderr.decode()}"
                }
            
            # Normalize video
            output_path = self.source_dir / f"{safe_name}.mp4"
            
            # Handle duplicate names
            counter = 1
            while output_path.exists():
                output_path = self.source_dir / f"{safe_name}_{counter}.mp4"
                counter += 1
            
            success = await self._normalize_video(raw_path, output_path)
            
            # Cleanup raw file
            if raw_path.exists():
                raw_path.unlink()
            
            if success:
                info = await self._get_video_info(output_path)
                return {
                    'success': True,
                    'video_id': video_id,
                    'filename': output_path.name,
                    'path': str(output_path),
                    'duration': info.get('duration'),
                    'resolution': f"{info.get('width')}x{info.get('height')}"
                }
            
            return {'success': False, 'message': 'Normalization failed'}
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {'success': False, 'message': str(e)}
    
    async def download_and_normalize(
        self,
        url: str,
        custom_name: Optional[str],
        task_id: str
    ):
        """Background download task"""
        self.tasks[task_id] = {
            'task_id': task_id,
            'status': 'processing',
            'progress': 0.0,
            'message': 'Starting download...'
        }
        
        try:
            result = await self.download_and_normalize_sync(url, custom_name)
            
            if result['success']:
                self.tasks[task_id].update({
                    'status': 'completed',
                    'progress': 1.0,
                    'message': 'Complete',
                    'result': result
                })
            else:
                self.tasks[task_id].update({
                    'status': 'failed',
                    'progress': 0.0,
                    'message': result['message']
                })
                
        except Exception as e:
            self.tasks[task_id].update({
                'status': 'failed',
                'message': str(e)
            })
    
    # =========================================================================
    # Upload Operations
    # =========================================================================
    
    async def upload_and_normalize(
        self,
        file: UploadFile,
        custom_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload and normalize video file"""
        try:
            video_id = str(uuid.uuid4())[:8]
            
            # Get filename
            original_name = Path(file.filename).stem
            safe_name = self._sanitize_filename(custom_name or original_name)
            
            # Save uploaded file to temp
            ext = Path(file.filename).suffix
            temp_path = self.temp_dir / f"{video_id}_upload{ext}"
            
            async with aiofiles.open(temp_path, 'wb') as f:
                content = await file.read()
                await f.write(content)
            
            # Normalize
            output_path = self.source_dir / f"{safe_name}.mp4"
            
            counter = 1
            while output_path.exists():
                output_path = self.source_dir / f"{safe_name}_{counter}.mp4"
                counter += 1
            
            success = await self._normalize_video(temp_path, output_path)
            
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()
            
            if success:
                info = await self._get_video_info(output_path)
                return {
                    'success': True,
                    'video_id': video_id,
                    'filename': output_path.name,
                    'path': str(output_path),
                    'duration': info.get('duration'),
                    'resolution': f"{info.get('width')}x{info.get('height')}"
                }
            
            return {'success': False, 'message': 'Normalization failed'}
            
        except Exception as e:
            logger.error(f"Upload error: {e}")
            return {'success': False, 'message': str(e)}
    
    # =========================================================================
    # Video Operations
    # =========================================================================
    
    async def list_videos(
        self,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "created_at",
        order: str = "desc"
    ) -> List[Dict]:
        """List all videos"""
        videos = []
        
        for video_path in self.source_dir.glob("*.mp4"):
            info = await self._get_video_info(video_path)
            if info:
                videos.append({
                    'id': video_path.stem,
                    'filename': video_path.name,
                    'path': str(video_path),
                    'duration': info.get('duration', 0),
                    'width': info.get('width', 0),
                    'height': info.get('height', 0),
                    'fps': info.get('fps', 0),
                    'codec': info.get('video_codec', 'unknown'),
                    'size_mb': info.get('size_mb', 0),
                    'created_at': datetime.fromtimestamp(video_path.stat().st_mtime)
                })
        
        # Sort
        reverse = order == "desc"
        if sort_by == "created_at":
            videos.sort(key=lambda x: x['created_at'], reverse=reverse)
        elif sort_by == "name":
            videos.sort(key=lambda x: x['filename'].lower(), reverse=reverse)
        elif sort_by == "size":
            videos.sort(key=lambda x: x['size_mb'], reverse=reverse)
        
        return videos[offset:offset + limit]
    
    async def get_video(self, video_id: str) -> Optional[Dict]:
        """Get video by ID"""
        video_path = self.source_dir / f"{video_id}.mp4"
        
        if not video_path.exists():
            # Try to find by partial match
            for path in self.source_dir.glob(f"{video_id}*.mp4"):
                video_path = path
                break
            else:
                return None
        
        info = await self._get_video_info(video_path)
        if info:
            return {
                'id': video_path.stem,
                'filename': video_path.name,
                'path': str(video_path),
                **info,
                'created_at': datetime.fromtimestamp(video_path.stat().st_mtime)
            }
        return None
    
    async def delete_video(self, video_id: str) -> bool:
        """Delete video"""
        video_path = self.source_dir / f"{video_id}.mp4"
        
        if not video_path.exists():
            for path in self.source_dir.glob(f"{video_id}*.mp4"):
                video_path = path
                break
            else:
                return False
        
        try:
            video_path.unlink()
            return True
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return False
    
    async def rename_video(self, video_id: str, new_name: str) -> bool:
        """Rename video"""
        video_path = self.source_dir / f"{video_id}.mp4"
        
        if not video_path.exists():
            for path in self.source_dir.glob(f"{video_id}*.mp4"):
                video_path = path
                break
            else:
                return False
        
        try:
            safe_name = self._sanitize_filename(new_name)
            new_path = self.source_dir / f"{safe_name}.mp4"
            video_path.rename(new_path)
            return True
        except Exception as e:
            logger.error(f"Rename error: {e}")
            return False
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get task status"""
        return self.tasks.get(task_id)
    
    # =========================================================================
    # Private Methods
    # =========================================================================
    
    async def _get_video_title(self, url: str) -> str:
        """Get video title from URL"""
        try:
            cmd = ['yt-dlp', '--dump-json', '--no-download', url]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            
            if process.returncode == 0:
                data = json.loads(stdout.decode())
                return data.get('title', 'video')[:50]
        except:
            pass
        return 'video'
    
    async def _normalize_video(self, input_path: Path, output_path: Path) -> bool:
        """Normalize video to standard format"""
        try:
            vf_filters = [
                f'fps={settings.video_target_fps}',
                f'scale={settings.video_target_width}:{settings.video_target_height}:force_original_aspect_ratio=decrease',
                f'pad={settings.video_target_width}:{settings.video_target_height}:(ow-iw)/2:(oh-ih)/2:black',
                'format=yuv420p'
            ]
            
            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(input_path),
                '-vf', ','.join(vf_filters),
                '-c:v', 'libx264',
                '-crf', str(settings.video_crf),
                '-preset', settings.video_preset,
                '-c:a', 'aac',
                '-b:a', '192k',
                '-movflags', '+faststart',
                str(output_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.communicate()
            
            return process.returncode == 0 and output_path.exists()
            
        except Exception as e:
            logger.error(f"Normalization error: {e}")
            return False
    
    async def _get_video_info(self, video_path: Path) -> Optional[Dict]:
        """Get video metadata"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(video_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, _ = await process.communicate()
            
            if process.returncode != 0:
                return None
            
            data = json.loads(stdout.decode())
            
            video_stream = next(
                (s for s in data.get('streams', []) if s['codec_type'] == 'video'),
                None
            )
            
            info = {
                'duration': float(data.get('format', {}).get('duration', 0)),
                'size_mb': int(data.get('format', {}).get('size', 0)) / (1024 * 1024),
            }
            
            if video_stream:
                fps_str = video_stream.get('r_frame_rate', '0/1')
                if '/' in fps_str:
                    num, den = map(int, fps_str.split('/'))
                    fps = num / den if den else 0
                else:
                    fps = float(fps_str)
                
                info.update({
                    'width': int(video_stream.get('width', 0)),
                    'height': int(video_stream.get('height', 0)),
                    'fps': fps,
                    'video_codec': video_stream.get('codec_name', 'unknown'),
                })
            
            return info
            
        except Exception as e:
            logger.error(f"Video info error: {e}")
            return None
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize filename"""
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = re.sub(r'[\s]+', '_', name)
        name = name.strip('._')
        return name[:100] if name else 'unnamed'

