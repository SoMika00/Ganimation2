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
                self.tasks[task_id]['error'] = 'Failed to extract source frame'
                self.tasks[task_id]['message'] = 'Failed to extract source frame'
                self.tasks[task_id]['completed_at'] = datetime.now()
                self._persist()
                return

            self.tasks[task_id]['message'] = 'Generating image...'
            self.tasks[task_id]['progress'] = 0.3

            # Use ComfyUI client for generation
            client = self._get_comfy_client()
            from PIL import Image
            source_image = Image.open(frame_path).convert('RGB')

            settings = {
                'lora_weight': params.get('lora_weight', 0.75),
                'cfg_scale': params.get('cfg_scale', 5.0),
                'steps': params.get('steps', 30),
                'seed': params.get('seed', -1),
                'controlnet_type': params.get('controlnet_type', 'depth'),
                'controlnet_strength': params.get('controlnet_strength', 0.6),
                'controlnet_depth_enabled': params.get('controlnet_type', 'depth') == 'depth',
                'controlnet_canny_enabled': params.get('controlnet_type', 'depth') == 'canny',
            }

            def progress_cb(progress, message):
                self.tasks[task_id]['progress'] = 0.3 + progress * 0.6
                self.tasks[task_id]['message'] = message

            success, message, images = client.generate_ghibli_image(
                source_image, settings, progress_callback=progress_cb
            )

            if self._check_cancelled(task_id):
                return

            if not success or not images:
                self.tasks[task_id]['status'] = 'failed'
                self.tasks[task_id]['error'] = message
                self.tasks[task_id]['message'] = message
                self.tasks[task_id]['completed_at'] = datetime.now()
                self._persist()
                return

            # Save generated images
            saved_images = []
            for i, img in enumerate(images):
                filename = f"{task_id}_{i}.png"
                output_path = self.images_dir / filename
                img.save(output_path)
                saved_images.append({
                    'image_id': filename,
                    'path': str(output_path),
                })

            self.tasks[task_id]['status'] = 'completed'
            self.tasks[task_id]['progress'] = 1.0
            self.tasks[task_id]['message'] = 'Complete'
            self.tasks[task_id]['completed_at'] = datetime.now()
            self.tasks[task_id]['result'] = {'images': saved_images}
            self._persist()

        except Exception as e:
            logger.error(f"Image generation error for {task_id}: {e}")
            self.tasks[task_id]['status'] = 'failed'
            self.tasks[task_id]['error'] = str(e)
            self.tasks[task_id]['message'] = str(e)
            self.tasks[task_id]['completed_at'] = datetime.now()
            self._persist()

    async def _extract_single_frame(self, video_id: str, frame_index: int) -> Optional[Path]:
        """Extract a single frame from a source video."""
        video_path = self.source_dir / f"{video_id}.mp4"
        if not video_path.exists():
            # Try to find by glob
            matches = list(self.source_dir.glob(f"{video_id}*"))
            if not matches:
                return None
            video_path = matches[0]

        output_path = self.temp_dir / f"frame_{video_id}_{frame_index}.png"

        try:
            import subprocess
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vf', f'select=eq(n\\,{frame_index})',
                '-vframes', '1',
                str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, timeout=60)
            if output_path.exists():
                return output_path
        except Exception as e:
            logger.warning(f"Frame extraction failed: {e}")

        return None

    async def generate_image_sync(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate image synchronously (blocking)."""
        task_id = await self.queue_image_generation(params)
        # Poll until terminal
        for _ in range(600):
            task = self.tasks.get(task_id)
            if task and task.get('status') in TERMINAL_STATUSES:
                break
            await asyncio.sleep(1)

        task = self.tasks.get(task_id)
        if not task:
            return {'success': False, 'message': 'Task not found'}

        if task.get('status') == 'completed':
            return {
                'success': True,
                'message': 'Generation complete',
                'images': task.get('result', {}).get('images', []),
            }
        return {
            'success': False,
            'message': task.get('error') or task.get('message') or 'Generation failed',
        }

    async def extract_frames(self, video_id: str, num_frames: int) -> List[dict]:
        """Extract multiple frames from a source video."""
        video_path = self.source_dir / f"{video_id}.mp4"
        if not video_path.exists():
            matches = list(self.source_dir.glob(f"{video_id}*"))
            if not matches:
                raise ValueError(f"Video not found: {video_id}")
            video_path = matches[0]

        frames = []
        try:
            import subprocess
            # Get duration
            probe = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(video_path)],
                capture_output=True, text=True, timeout=30
            )
            duration = float(json.loads(probe.stdout).get('format', {}).get('duration', 0))
            if duration <= 0:
                return []

            interval = duration / num_frames
            for i in range(num_frames):
                timestamp = interval * i
                output_path = self.temp_dir / f"frame_{video_id}_{i}.png"
                cmd = [
                    'ffmpeg', '-y',
                    '-ss', str(timestamp),
                    '-i', str(video_path),
                    '-vframes', '1',
                    '-q:v', '2',
                    str(output_path),
                ]
                subprocess.run(cmd, capture_output=True, timeout=30)
                if output_path.exists():
                    frames.append({
                        'frame_index': i,
                        'path': str(output_path),
                        'timestamp': timestamp,
                    })
        except Exception as e:
            logger.warning(f"Frame extraction failed: {e}")

        return frames

    async def get_frame(self, video_id: str, frame_index: int) -> Optional[Path]:
        """Get a specific frame path."""
        frame_path = self.temp_dir / f"frame_{video_id}_{frame_index}.png"
        if frame_path.exists():
            return frame_path
        return await self._extract_single_frame(video_id, frame_index)

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

            image_id = params['image_id']
            source_video_id = params.get('source_video_id')

            image_path = self.images_dir / image_id
            if not image_path.exists():
                matches = list(self.images_dir.glob(f"{image_id}*"))
                if not matches:
                    self.tasks[task_id]['status'] = 'failed'
                    self.tasks[task_id]['error'] = f'Image not found: {image_id}'
                    self.tasks[task_id]['message'] = f'Image not found: {image_id}'
                    self.tasks[task_id]['completed_at'] = datetime.now()
                    self._persist()
                    return
                image_path = matches[0]

            source_video_path = None
            if source_video_id:
                source_video_path = self.source_dir / f"{source_video_id}.mp4"
                if not source_video_path.exists():
                    matches = list(self.source_dir.glob(f"{source_video_id}*"))
                    if matches:
                        source_video_path = matches[0]

            self.tasks[task_id]['message'] = 'Generating video...'
            self.tasks[task_id]['progress'] = 0.3

            from PIL import Image
            source_image = Image.open(image_path).convert('RGB')

            from utils.video_animator import VideoAnimator
            animator = VideoAnimator(self.models_dir, self.temp_dir)

            def progress_cb(progress, message):
                self.tasks[task_id]['progress'] = 0.3 + progress * 0.6
                self.tasks[task_id]['message'] = message

            settings = {
                'motion_strength': params.get('motion_strength', 0.7),
                'num_frames': params.get('num_frames', 96),
                'guidance_scale': params.get('guidance_scale', 7.5),
                'num_inference_steps': params.get('num_inference_steps', 40),
                'use_relighting': params.get('use_relighting', False),
                'relight_strength': params.get('relight_strength', 0.5),
            }

            success, message, frames = animator.animate(
                source_image,
                source_video_path if source_video_path else self.temp_dir / 'placeholder.mp4',
                settings=settings,
                progress_callback=progress_cb,
            )

            if self._check_cancelled(task_id):
                return

            if not success or not frames:
                self.tasks[task_id]['status'] = 'failed'
                self.tasks[task_id]['error'] = message
                self.tasks[task_id]['message'] = message
                self.tasks[task_id]['completed_at'] = datetime.now()
                self._persist()
                return

            # Save video
            output_filename = f"{task_id}.mp4"
            output_path = self.videos_dir / output_filename

            # Encode frames to video
            import subprocess
            frames_dir = self.temp_dir / f"frames_{task_id}"
            frames_dir.mkdir(parents=True, exist_ok=True)
            for i, frame in enumerate(frames):
                frame.save(frames_dir / f"frame_{i:04d}.png")

            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(params.get('output_fps', 30)),
                '-i', str(frames_dir / 'frame_%04d.png'),
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                str(output_path),
            ]
            subprocess.run(cmd, capture_output=True, timeout=300)

            self.tasks[task_id]['status'] = 'completed'
            self.tasks[task_id]['progress'] = 1.0
            self.tasks[task_id]['message'] = 'Complete'
            self.tasks[task_id]['completed_at'] = datetime.now()
            self.tasks[task_id]['result'] = {'video_id': output_filename, 'path': str(output_path)}
            self._persist()

        except Exception as e:
            logger.error(f"Video generation error for {task_id}: {e}")
            self.tasks[task_id]['status'] = 'failed'
            self.tasks[task_id]['error'] = str(e)
            self.tasks[task_id]['message'] = str(e)
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
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List generation tasks with optional filtering.

        Args:
            status: Filter by task status (pending, processing, completed, failed, cancelled).
            task_type: Filter by task type (image, video).
            limit: Maximum number of tasks to return (most recent first).
            search: Case-insensitive substring match against task_id, message,
                error, and params.video_id / params.image_id.

        Returns:
            List of task dicts, most recent first.
        """
        tasks = list(self.tasks.values())

        # Sort by created_at desc (most recent first)
        tasks.sort(
            key=lambda t: t.get('created_at') or datetime.min,
            reverse=True,
        )

        # Apply status filter
        if status is not None:
            tasks = [t for t in tasks if t.get('status') == status]

        # Apply type filter
        if task_type is not None:
            tasks = [t for t in tasks if t.get('type') == task_type]

        # Apply search filter (case-insensitive)
        if search is not None and search.strip():
            needle = search.strip().lower()
            filtered = []
            for t in tasks:
                if self._task_matches_search(t, needle):
                    filtered.append(t)
            tasks = filtered

        # Apply limit
        return tasks[:limit]

    @staticmethod
    def _task_matches_search(task: Dict[str, Any], needle: str) -> bool:
        """Return True if a task matches the search needle (case-insensitive)."""
        # task_id
        task_id = task.get('task_id')
        if task_id is not None and needle in str(task_id).lower():
            return True

        # message
        message = task.get('message')
        if message is not None and needle in str(message).lower():
            return True

        # error
        error = task.get('error')
        if error is not None and needle in str(error).lower():
            return True

        # params.video_id / params.image_id
        params = task.get('params')
        if isinstance(params, dict):
            video_id = params.get('video_id')
            if video_id is not None and needle in str(video_id).lower():
                return True
            image_id = params.get('image_id')
            if image_id is not None and needle in str(image_id).lower():
                return True

        return False

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a single task by id."""
        return self.tasks.get(task_id)

    async def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Retry a failed or cancelled task with the same params."""
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

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

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending/processing task."""
        task = self.tasks.get(task_id)
        if task is None:
            return False

        if task.get('status') in ACTIVE_STATUSES:
            task['cancel_requested'] = True
            self._persist()
            return True

        return False

    # =========================================================================
    # Model Management
    # =========================================================================

    async def get_models_status(self) -> Dict[str, Any]:
        """Get status of loaded models."""
        return {
            'models_loaded': self.models_loaded,
            'image_generator_loaded': self._image_generator is not None,
            'video_animator_loaded': self._video_animator is not None,
        }

    async def load_models(self, model_type: str) -> Dict[str, Any]:
        """Pre-load models into GPU memory."""
        if model_type in ('sdxl', 'all'):
            from utils.image_generator import GhibliImageGenerator
            self._image_generator = GhibliImageGenerator(self.models_dir)
            success, msg = self._image_generator.load_models()
            self.models_loaded['sdxl'] = success
            self.models_loaded['controlnet'] = success
            self.models_loaded['lora'] = success
            if not success:
                return {'success': False, 'message': msg}

        if model_type in ('wan2', 'all'):
            from utils.video_animator import VideoAnimator
            self._video_animator = VideoAnimator(self.models_dir, self.temp_dir)
            success, msg = self._video_animator.load_wan_model()
            self.models_loaded['wan2'] = success
            if not success:
                return {'success': False, 'message': msg}

        return {'success': True, 'message': 'Models loaded'}

    async def unload_models(self) -> None:
        """Unload models from GPU memory."""
        if self._image_generator is not None:
            self._image_generator.unload_models()
            self._image_generator = None
        if self._video_animator is not None:
            self._video_animator = None
        for key in self.models_loaded:
            self.models_loaded[key] = False
