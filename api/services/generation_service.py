'''
Generation Service
AI image and video generation
'''

import uuid
import asyncio
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from loguru import logger

from api.config import settings


# Maximum number of tasks to persist to disk
MAX_PERSISTED_TASKS = 200

# Task statuses considered terminal (persisted on transition)
TERMINAL_STATUSES = {'completed', 'failed', 'cancelled'}

# Fields that hold datetime values and must be serialized/parsed
_DATETIME_FIELDS = ('created_at', 'completed_at')


def _iso_to_datetime(value: Any) -> Any:
    """Parse an ISO-format string back into a datetime (best-effort)."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
    return value


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

        # Persistence path
        self._tasks_path = settings.data_dir / 'tasks.json'

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
        self._comfy_client = None

        # Load persisted task history
        self._load_tasks()

    # =========================================================================
    # Persistence
    # =========================================================================

    def _load_tasks(self) -> None:
        """Load persisted tasks from disk, tolerating corrupt/missing files."""
        if not self._tasks_path.exists():
            return

        try:
            with open(self._tasks_path, 'r') as f:
                data = json.load(f)

            if not isinstance(data, list):
                logger.warning(f"tasks.json has unexpected format; starting empty")
                return

            loaded: Dict[str, Dict] = {}
            for item in data:
                if not isinstance(item, dict) or 'task_id' not in item:
                    continue
                # Parse datetime fields back to datetime objects
                for field in _DATETIME_FIELDS:
                    if field in item:
                        item[field] = _iso_to_datetime(item[field])
                loaded[item['task_id']] = item

            self.tasks = loaded
            logger.info(f"Loaded {len(self.tasks)} generation task(s) from {self._tasks_path}")

        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning(f"Failed to load tasks from {self._tasks_path}: {e}; starting empty")
            self.tasks = {}

    def _save_tasks(self) -> None:
        """Atomically persist tasks to disk, capped at the most recent N tasks."""
        try:
            self._tasks_path.parent.mkdir(parents=True, exist_ok=True)

            # Sort by created_at desc and cap
            tasks = sorted(
                self.tasks.values(),
                key=lambda t: t.get('created_at') or datetime.min,
                reverse=True,
            )[:MAX_PERSISTED_TASKS]

            serializable = []
            for task in tasks:
                item = dict(task)
                for field in _DATETIME_FIELDS:
                    value = item.get(field)
                    if isinstance(value, datetime):
                        item[field] = value.isoformat()
                serializable.append(item)

            # Atomic write: temp file then os.replace
            tmp_path = self._tasks_path.with_suffix('.json.tmp')
            with open(tmp_path, 'w') as f:
                json.dump(serializable, f, indent=2, default=str)
            os.replace(tmp_path, self._tasks_path)

        except OSError as e:
            logger.warning(f"Failed to save tasks to {self._tasks_path}: {e}")

    def _persist(self) -> None:
        """Persist current task state to disk."""
        self._save_tasks()

    # =========================================================================
    # ComfyUI helpers
    # =========================================================================

    def _get_comfy_client(self):
        if self._comfy_client is None:
            from utils.comfyui_client import ComfyUIClient
            self._comfy_client = ComfyUIClient()
        return self._comfy_client

    async def _poll_comfy_progress(self, task_id: str) -> None:
        """Non-blocking poll of ComfyUI /history and queue for progress update."""
        task = self.tasks.get(task_id)
        if not task or 'comfy_prompt_id' not in task or not task.get('comfy_prompt_id'):
            return
        prompt_id = task['comfy_prompt_id']
        try:
            client = self._get_comfy_client()
            # Use existing client methods (non-blocking, best-effort)
            history = client.get_history() or {}
            queue = client.get_queue() or {}
            # Update progress if present in history for this prompt
            if prompt_id in history:
                # ComfyUI history entries may contain 'status' or outputs; treat as completed
                task['progress'] = 1.0
                task['status'] = 'completed'
                task['message'] = 'Complete'
            else:
                # Check queue for running status (simple heuristic)
                running = queue.get('queue_running', []) if isinstance(queue, dict) else []
                if any(str(prompt_id) in str(item) for item in running):
                    task['progress'] = min(task.get('progress', 0.1) + 0.1, 0.9)
                    task['message'] = 'Processing in ComfyUI'
        except Exception as e:
            logger.debug(f"Comfy progress poll skipped: {e}")

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
            'comfy_prompt_id': None,
        }
        self._persist()

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
                self.tasks[task_id]['completed_at'] = datetime.now()
                self._persist()
                return

            self.tasks[task_id]['message'] = 'Generating image...'
            self.tasks[task_id]['progress'] = 0.3

            # Placeholder for ComfyUI path (would set comfy_prompt_id here)
            # e.g. prompt_id = client.queue_prompt(workflow)
            # self.tasks[task_id]['comfy_prompt_id'] = prompt_id

            # Placeholder result
            await asyncio.sleep(2)  # Simulate generation

            self.tasks[task_id]['status'] = 'completed'
            self.tasks[task_id]['progress'] = 1.0
            self.tasks[task_id]['message'] = 'Complete'
            self.tasks[task_id]['completed_at'] = datetime.now()
            self.tasks[task_id]['result'] = {
                'images': [{'id': f'{video_id}_gen_{task_id}', 'status': 'placeholder'}]
            }
            self._persist()

        except Exception as e:
            logger.error(f"Image generation error: {e}")
            self.tasks[task_id]['status'] = 'failed'
            self.tasks[task_id]['error'] = str(e)
            self.tasks[task_id]['completed_at'] = datetime.now()
            self._persist()

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
            'comfy_prompt_id': None,
        }
        self._persist()

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
            self._persist()

        except Exception as e:
            logger.error(f"Video generation error: {e}")
            self.tasks[task_id]['status'] = 'failed'
            self.tasks[task_id]['error'] = str(e)
            self.tasks[task_id]['completed_at'] = datetime.now()
            self._persist()

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
        for tid in list(self.tasks.keys()):
            await self._poll_comfy_progress(tid)
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
        await self._poll_comfy_progress(task_id)
        return self.tasks.get(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel pending task"""
        task = self.tasks.get(task_id)

        if not task or task['status'] != 'pending':
            return False

        task['status'] = 'cancelled'
        task['message'] = 'Cancelled by user'
        task['completed_at'] = datetime.now()
        self._persist()
        return True

    async def retry_task(self, task_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Retry a failed/cancelled task with the same (optionally overridden) params.

        Returns a dict with the new task_id and parent_task_id. Raises ValueError
        for non-existent tasks and RuntimeError for tasks that are still in progress.
        """
        original = self.tasks.get(task_id)

        if original is None:
            raise ValueError(f"Task not found: {task_id}")

        if original['status'] not in ('failed', 'cancelled'):
            raise RuntimeError(
                f"Task {task_id} is still in progress (status={original['status']})"
            )

        params = dict(original.get('params') or {})
        if overrides:
            params.update(overrides)

        if original['type'] == 'image':
            new_task_id = await self.queue_image_generation(params)
        else:
            new_task_id = await self.queue_video_generation(params)

        return {
            'new_task_id': new_task_id,
            'parent_task_id': task_id,
        }

    async def clear_tasks(self, status: Optional[str] = None) -> int:
        """Clear task history, optionally filtered by status.

        Returns the number of tasks removed.
        """
        if status is None:
            removed = len(self.tasks)
            self.tasks = {}
        else:
            to_remove = [tid for tid, t in self.tasks.items() if t.get('status') == status]
            removed = len(to_remove)
            for tid in to_remove:
                self.tasks.pop(tid, None)

        if removed:
            self._persist()

        return removed

    async def get_models_status(self):
        """Get status of loaded models"""
        return {
            'models_loaded': self.models_loaded,
            'image_generator': self._image_generator is not None,
            'video_animator': self._video_animator is not None,
        }

    async def load_models(self, model_type: str):
        """Pre-load models into GPU memory"""
        return {'success': True, 'message': f'Models loaded: {model_type}'}

    async def unload_models(self):
        """Unload models from GPU memory"""
        self.models_loaded = {k: False for k in self.models_loaded}
        self._image_generator = None
        self._video_animator = None
