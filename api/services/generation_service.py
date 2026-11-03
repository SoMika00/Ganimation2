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
from datetime import datetime, timezone

from loguru import logger

from api.config import settings


# Maximum number of tasks to persist to disk
MAX_PERSISTED_TASKS = 200

# Task statuses considered terminal (persisted on transition)
TERMINAL_STATUSES = {'completed', 'failed', 'cancelled'}

# Fields that hold datetime values and must be serialized/parsed
_DATETIME_FIELDS = ('created_at', 'completed_at')

# Statuses considered "active" (still in flight)
ACTIVE_STATUSES = {'pending', 'processing'}

# Maximum number of active task ids returned in the queue summary
MAX_ACTIVE_TASK_IDS = 20


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
    # Queue Summary
    # =========================================================================

    def get_queue_summary(self) -> Dict[str, Any]:
        """
        Compute a lightweight summary of the in-memory generation task queue.

        Runs in O(n) over self.tasks and never raises on malformed entries
        (missing/invalid status, type, or created_at).
        """
        by_status = {
            'pending': 0,
            'processing': 0,
            'completed': 0,
            'failed': 0,
            'cancelled': 0,
        }
        by_type = {
            'image': 0,
            'video': 0,
        }

        active_task_ids: List[str] = []
        oldest_pending_age_seconds: Optional[float] = None
        now = datetime.now(timezone.utc)

        for task in self.tasks.values():
            if not isinstance(task, dict):
                continue

            status = task.get('status')
            if isinstance(status, str) and status in by_status:
                by_status[status] += 1

            task_type = task.get('type')
            if isinstance(task_type, str) and task_type in by_type:
                by_type[task_type] += 1

            if status in ACTIVE_STATUSES:
                task_id = task.get('task_id')
                if task_id is not None and len(active_task_ids) < MAX_ACTIVE_TASK_IDS:
                    active_task_ids.append(str(task_id))

            if status == 'pending':
                created_at = task.get('created_at')
                age = self._age_seconds(created_at, now)
                if age is not None:
                    if oldest_pending_age_seconds is None or age > oldest_pending_age_seconds:
                        oldest_pending_age_seconds = age

        total = sum(by_status.values())

        return {
            'total': total,
            'by_status': by_status,
            'by_type': by_type,
            'active_count': by_status['pending'] + by_status['processing'],
            'oldest_pending_age_seconds': oldest_pending_age_seconds,
            'active_task_ids': active_task_ids,
            'generated_at': now.isoformat(),
        }

    @staticmethod
    def _age_seconds(created_at: Any, now: datetime) -> Optional[float]:
        """Return age in seconds of a created_at value, or None if unparseable."""
        if created_at is None:
            return None

        if isinstance(created_at, datetime):
            dt = created_at
        elif isinstance(created_at, str):
            try:
                dt = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                return None
        else:
            return None

        # Normalize naive datetimes to UTC for comparison
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        age = (now - dt).total_seconds()
        # Guard against clock skew producing negative ages
        return max(age, 0.0)

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
    # Cancellation helpers
    # =========================================================================

    def _check_cancelled(self, task_id: str) -> bool:
        """
        Check if a task has been cooperatively cancelled.

        If the cancel_requested flag is set, transition the task to 'cancelled'
        (with completed_at set) and persist. Returns True if the task was
        cancelled, False otherwise.
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task.get('cancel_requested') and task.get('status') in ACTIVE_STATUSES:
            task['status'] = 'cancelled'
            task['message'] = 'Cancelled'
            task['completed_at'] = datetime.now()
            task.pop('cancel_requested', None)
            self._persist()
            return True
        return False

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

            # Cooperative cancellation checkpoint
            if self._check_cancelled(task_id):
                return

            # Get source frame
            video_id = params['video_id']
            frame_index = params.get('frame_index', 0)

            frame_path = await self._extract_single_frame(video_id, frame_index)

            if self._check_cancelled(task_id):
                return

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

            if self._check_cancelled(task_id):
                return

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

    async def _extract_single_frame(self, video_id: str, frame_index: int) -> Optional[Path]:
        """Extract a single frame from a source video (best-effort)."""
        try:
            from utils.video_processor import VideoProcessor
            processor = VideoProcessor(self.source_dir, self.temp_dir)
            return await processor.extract_frame(video_id, frame_index)
        except Exception as e:
            logger.warning(f"Frame extraction failed: {e}")
            return None

    async def generate_image_sync(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate image synchronously (blocking)."""
        task_id = await self.queue_image_generation(params)
        # Wait for the background task to finish
        for _ in range(600):
            task = self.tasks.get(task_id)
            if not task or task.get('status') in TERMINAL_STATUSES:
                break
            await asyncio.sleep(0.5)

        task = self.tasks.get(task_id)
        if not task:
            return {'success': False, 'message': 'Task not found'}
        if task.get('status') == 'completed':
            return {'success': True, 'images': task.get('result', {}).get('images', [])}
        return {'success': False, 'message': task.get('error') or task.get('message') or 'Generation failed'}

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
            self.tasks[task_id]['message'] = 'Loading models...'
            self.tasks[task_id]['progress'] = 0.1

            if self._check_cancelled(task_id):
                return

            # Placeholder for actual Wan2.2 pipeline
            await asyncio.sleep(2)  # Simulate generation

            if self._check_cancelled(task_id):
                return

            self.tasks[task_id]['status'] = 'completed'
            self.tasks[task_id]['progress'] = 1.0
            self.tasks[task_id]['message'] = 'Complete'
            self.tasks[task_id]['completed_at'] = datetime.now()
            self.tasks[task_id]['result'] = {
                'videos': [{'id': f'{task_id}_video', 'status': 'placeholder'}]
            }
            self._persist()

        except Exception as e:
            logger.error(f"Video generation error: {e}")
            self.tasks[task_id]['status'] = 'failed'
            self.tasks[task_id]['error'] = str(e)
            self.tasks[task_id]['completed_at'] = datetime.now()
            self._persist()

    # =========================================================================
    # Task Management
    # =========================================================================

    async def list_tasks(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List generation tasks, optionally filtered."""
        tasks = list(self.tasks.values())

        if status:
            tasks = [t for t in tasks if t.get('status') == status]
        if task_type:
            tasks = [t for t in tasks if t.get('type') == task_type]

        tasks = sorted(
            tasks,
            key=lambda t: t.get('created_at') or datetime.min,
            reverse=True,
        )

        return tasks[:limit]

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a single task by id."""
        return self.tasks.get(task_id)

    async def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Retry a failed or cancelled task with the same params."""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task.get('status') not in ('failed', 'cancelled'):
            raise RuntimeError(f"Task {task_id} is not in a retryable state")

        params = task.get('params') or {}
        task_type = task.get('type')

        if task_type == 'image':
            new_task_id = await self.queue_image_generation(params)
        elif task_type == 'video':
            new_task_id = await self.queue_video_generation(params)
        else:
            raise RuntimeError(f"Unknown task type: {task_type}")

        return {
            'new_task_id': new_task_id,
            'parent_task_id': task_id,
        }

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """
        Cancel a pending or processing task.

        - pending: immediately transition to 'cancelled'.
        - processing: set a cooperative 'cancel_requested' flag; the running
          coroutine will transition to 'cancelled' at its next checkpoint.
        - terminal (completed/failed/cancelled): raise ValueError.

        Returns a dict describing the outcome.
        """
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        status = task.get('status')

        if status == 'pending':
            task['status'] = 'cancelled'
            task['message'] = 'Cancelled'
            task['completed_at'] = datetime.now()
            task.pop('cancel_requested', None)
            self._persist()
            return {'success': True, 'status': 'cancelled'}

        if status == 'processing':
            task['cancel_requested'] = True
            task['message'] = 'Cancellation requested'
            self._persist()
            return {'success': True, 'status': 'cancelled'}

        # Terminal statuses
        raise ValueError(f"Task {task_id} is already {status}")

    def clear_tasks(self, statuses: Optional[List[str]] = None) -> int:
        """
        Remove tasks whose status is in the given set.

        Only terminal statuses are ever removed; pending/processing tasks are
        always preserved. Defaults to all terminal statuses.

        Returns the number of tasks removed.
        """
        if statuses is None:
            statuses = list(TERMINAL_STATUSES)

        # Never remove active tasks, even if explicitly requested
        removable = set(statuses) & TERMINAL_STATUSES

        to_remove = [
            task_id
            for task_id, task in self.tasks.items()
            if task.get('status') in removable
        ]

        for task_id in to_remove:
            self.tasks.pop(task_id, None)

        if to_remove:
            self._persist()

        return len(to_remove)

    # =========================================================================
    # Model Management
    # =========================================================================

    async def get_models_status(self) -> Dict[str, Any]:
        """Get status of loaded models."""
        return {
            'models_loaded': dict(self.models_loaded),
            'image_generator_loaded': self._image_generator is not None,
            'video_animator_loaded': self._video_animator is not None,
        }

    async def load_models(self, model_type: str) -> Dict[str, Any]:
        """Pre-load models into GPU memory."""
        result = {'success': True, 'loaded': [], 'message': ''}

        if model_type in ('sdxl', 'all'):
            self.models_loaded['sdxl'] = True
            self.models_loaded['controlnet'] = True
            self.models_loaded['lora'] = True
            result['loaded'].append('sdxl')

        if model_type in ('wan2', 'all'):
            self.models_loaded['wan2'] = True
            self.models_loaded['rife'] = True
            result['loaded'].append('wan2')

        result['message'] = f"Loaded: {', '.join(result['loaded'])}"
        return result

    async def unload_models(self) -> None:
        """Unload models from GPU memory."""
        for key in self.models_loaded:
            self.models_loaded[key] = False
        self._image_generator = None
        self._video_animator = None

    async def extract_frames(self, video_id: str, num_frames: int) -> List[Dict[str, Any]]:
        """Extract frames from a video for selection."""
        try:
            from utils.video_processor import VideoProcessor
            processor = VideoProcessor(self.source_dir, self.temp_dir)
            frames = await processor.extract_frames(video_id, num_frames)
            return frames
        except Exception as e:
            logger.error(f"Frame extraction error: {e}")
            return []

    async def get_frame(self, video_id: str, frame_index: int) -> Optional[Path]:
        """Get a specific frame path."""
        try:
            from utils.video_processor import VideoProcessor
            processor = VideoProcessor(self.source_dir, self.temp_dir)
            return await processor.get_frame_path(video_id, frame_index)
        except Exception as e:
            logger.warning(f"Get frame error: {e}")
            return None
