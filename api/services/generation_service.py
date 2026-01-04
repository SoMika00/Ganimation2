"""
Generation Service
AI image and video generation
"""

import uuid
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from loguru import logger

from api.config import settings


class GenerationService:
    """AI generation service"""
    
    def __init__(self):
        self.source_dir = settings.source_media_dir
        self.images_dir = settings.generated_images_dir
        self.videos_dir = settings.generated_videos_dir
        self.temp_dir = settings.temp_dir
        self.models_dir = settings.models_dir
        
        # Task tracking
        self.tasks: Dict[str, Dict] = {}
        
        # Model status
        self.models_loaded = {
            'sdxl': False,
            'controlnet': False,
            'lora': False,
            'wan2': False,
            'rife': False,
        }
        
        # Model instances (lazy loaded)
        self._image_generator = None
        self._video_animator = None
    
    # =========================================================================
    # Image Generation
    # =========================================================================
    
    async def queue_image_generation(self, params: Dict[str, Any]) -> str:
        """Queue image generation task"""
        task_id = str(uuid.uuid4())[:8]
        
        self.tasks[task_id] = {
            'task_id': task_id,
            'type': 'image',
            'status': 'pending',
            'progress': 0.0,
            'message': 'Queued',
            'created_at': datetime.now(),
            'params': params,
        }
        
        # Start async task
        asyncio.create_task(self._run_image_generation(task_id, params))
        
        return task_id
    
    async def _run_image_generation(self, task_id: str, params: Dict[str, Any]):
        """Run image generation"""
        try:
            self.tasks[task_id]['status'] = 'processing'
            self.tasks[task_id]['message'] = 'Loading models...'
            self.tasks[task_id]['progress'] = 0.1
            
            # Get source frame
            video_id = params['video_id']
            frame_index = params.get('frame_index', 0)
            
            frame_path = await self._extract_single_frame(video_id, frame_index)
            
            if not frame_path:
                self.tasks[task_id]['status'] = 'failed'
                self.tasks[task_id]['error'] = 'Failed to extract frame'
                return
            
            self.tasks[task_id]['message'] = 'Generating image...'
            self.tasks[task_id]['progress'] = 0.3
            
            # Import and run generation
            # This would use the actual image generator
            # For now, placeholder implementation
            
            """
            from utils.image_generator import GhibliImageGenerator
            
            if self._image_generator is None:
                self._image_generator = GhibliImageGenerator(self.models_dir)
            
            from PIL import Image
            source_image = Image.open(frame_path)
            
            success, message, images = self._image_generator.generate(
                source_image,
                settings=params,
                num_images=params.get('num_images', 1)
            )
            
            if success:
                # Save images
                results = []
                for i, img in enumerate(images):
                    output_name = f"{video_id}_gen_{task_id}_{i:02d}.png"
                    output_path = self.images_dir / output_name
                    img.save(output_path)
                    results.append({
                        'id': output_name.replace('.png', ''),
                        'path': str(output_path),
                        'filename': output_name
                    })
                
                self.tasks[task_id]['status'] = 'completed'
                self.tasks[task_id]['progress'] = 1.0
                self.tasks[task_id]['result'] = {'images': results}
            else:
                self.tasks[task_id]['status'] = 'failed'
                self.tasks[task_id]['error'] = message
            """
            
            # Placeholder result
            await asyncio.sleep(2)  # Simulate generation
            
            self.tasks[task_id]['status'] = 'completed'
            self.tasks[task_id]['progress'] = 1.0
            self.tasks[task_id]['message'] = 'Complete'
            self.tasks[task_id]['completed_at'] = datetime.now()
            self.tasks[task_id]['result'] = {
                'images': [{'id': f'{video_id}_gen_{task_id}', 'status': 'placeholder'}]
            }
            
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            self.tasks[task_id]['status'] = 'failed'
            self.tasks[task_id]['error'] = str(e)
    
    async def generate_image_sync(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous image generation"""
        task_id = await self.queue_image_generation(params)
        
        # Wait for completion
        while True:
            task = self.tasks.get(task_id)
            if task and task['status'] in ['completed', 'failed']:
                break
            await asyncio.sleep(0.5)
        
        task = self.tasks[task_id]
        
        if task['status'] == 'completed':
            return {
                'success': True,
                'images': task.get('result', {}).get('images', [])
            }
        else:
            return {
                'success': False,
                'message': task.get('error', 'Unknown error')
            }
    
    # =========================================================================
    # Video Generation
    # =========================================================================
    
    async def queue_video_generation(self, params: Dict[str, Any]) -> str:
        """Queue video generation task"""
        task_id = str(uuid.uuid4())[:8]
        
        self.tasks[task_id] = {
            'task_id': task_id,
            'type': 'video',
            'status': 'pending',
            'progress': 0.0,
            'message': 'Queued',
            'created_at': datetime.now(),
            'params': params,
        }
        
        asyncio.create_task(self._run_video_generation(task_id, params))
        
        return task_id
    
    async def _run_video_generation(self, task_id: str, params: Dict[str, Any]):
        """Run video generation"""
        try:
            self.tasks[task_id]['status'] = 'processing'
            self.tasks[task_id]['message'] = 'Initializing...'
            self.tasks[task_id]['progress'] = 0.05
            
            # Placeholder - actual implementation would use Wan2.2
            await asyncio.sleep(5)
            
            self.tasks[task_id]['status'] = 'completed'
            self.tasks[task_id]['progress'] = 1.0
            self.tasks[task_id]['message'] = 'Complete'
            self.tasks[task_id]['completed_at'] = datetime.now()
            
        except Exception as e:
            logger.error(f"Video generation error: {e}")
            self.tasks[task_id]['status'] = 'failed'
            self.tasks[task_id]['error'] = str(e)
    
    # =========================================================================
    # Frame Extraction
    # =========================================================================
    
    async def extract_frames(self, video_id: str, num_frames: int = 10) -> List[Dict]:
        """Extract frames from video"""
        import subprocess
        import json
        
        # Find video
        video_path = None
        for path in self.source_dir.glob(f"{video_id}*.mp4"):
            video_path = path
            break
        
        if not video_path:
            return []
        
        # Get duration
        cmd = [
            'ffprobe', '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        duration = float(data.get('format', {}).get('duration', 0))
        
        if duration <= 0:
            return []
        
        # Extract frames
        frames = []
        interval = duration / (num_frames + 1)
        
        frames_dir = self.temp_dir / f"frames_{video_id}"
        frames_dir.mkdir(exist_ok=True)
        
        for i in range(num_frames):
            timestamp = interval * (i + 1)
            output_path = frames_dir / f"frame_{i:03d}.png"
            
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(timestamp),
                '-i', str(video_path),
                '-vframes', '1',
                '-q:v', '2',
                str(output_path)
            ]
            
            subprocess.run(cmd, capture_output=True, timeout=30)
            
            if output_path.exists():
                frames.append({
                    'index': i,
                    'timestamp': round(timestamp, 2),
                    'path': str(output_path),
                    'url': f"/api/v1/generation/frames/{video_id}/{i}"
                })
        
        return frames
    
    async def _extract_single_frame(self, video_id: str, frame_index: int) -> Optional[Path]:
        """Extract single frame"""
        frames_dir = self.temp_dir / f"frames_{video_id}"
        frame_path = frames_dir / f"frame_{frame_index:03d}.png"
        
        if frame_path.exists():
            return frame_path
        
        # Extract if not exists
        frames = await self.extract_frames(video_id, frame_index + 1)
        
        if frame_index < len(frames):
            return Path(frames[frame_index]['path'])
        
        return None
    
    async def get_frame(self, video_id: str, frame_index: int) -> Optional[str]:
        """Get frame path"""
        path = await self._extract_single_frame(video_id, frame_index)
        return str(path) if path else None
    
    # =========================================================================
    # Task Management
    # =========================================================================
    
    async def list_tasks(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """List generation tasks"""
        tasks = list(self.tasks.values())
        
        if status:
            tasks = [t for t in tasks if t['status'] == status]
        
        if task_type:
            tasks = [t for t in tasks if t['type'] == task_type]
        
        # Sort by created_at desc
        tasks.sort(key=lambda x: x['created_at'], reverse=True)
        
        return tasks[:limit]
    
    async def get_task(self, task_id: str) -> Optional[Dict]:
        """Get task by ID"""
        return self.tasks.get(task_id)
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel pending task"""
        task = self.tasks.get(task_id)
        
        if not task or task['status'] != 'pending':
            return False
        
        task['status'] = 'cancelled'
        task['message'] = 'Cancelled by user'
        return True
    
    # =========================================================================
    # Model Management
    # =========================================================================
    
    async def get_models_status(self) -> Dict[str, Any]:
        """Get status of loaded models"""
        import torch
        
        return {
            'models': self.models_loaded,
            'gpu_available': torch.cuda.is_available(),
            'vram_used_gb': torch.cuda.memory_allocated() / (1024**3) if torch.cuda.is_available() else 0,
        }
    
    async def load_models(self, model_type: str) -> Dict[str, Any]:
        """Pre-load models"""
        # Placeholder - would actually load models here
        
        if model_type in ['sdxl', 'all']:
            self.models_loaded['sdxl'] = True
            self.models_loaded['controlnet'] = True
            self.models_loaded['lora'] = True
        
        if model_type in ['wan2', 'all']:
            self.models_loaded['wan2'] = True
            self.models_loaded['rife'] = True
        
        return {
            'success': True,
            'loaded': self.models_loaded
        }
    
    async def unload_models(self):
        """Unload models from memory"""
        import torch
        
        self._image_generator = None
        self._video_animator = None
        
        self.models_loaded = {k: False for k in self.models_loaded}
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

