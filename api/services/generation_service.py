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

    @staticmethod
    def _duration_seconds(task: Dict[str, Any]) -> Optional[float]:
        """
        Return the duration in seconds between a task's created_at and
        completed_at, or None if either is missing/unparseable.
        """
        if not isinstance(task, dict):
            return None

        created_at = task.get('created_at')
        completed_at = task.get('completed_at')

        if created_at is None or completed_at is None:
            return None

        start = GenerationService._parse_datetime(created_at)
        end = GenerationService._parse_datetime(completed_at)

        if start is None or end is None:
            return None

        duration = (end - start).total_seconds()
        # Guard against clock skew producing negative durations
        return max(duration, 0.0)

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse a datetime or ISO string into an aware datetime, or None."""
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
            except (ValueError, TypeError):
                return None
        else:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Compute generation task duration and throughput metrics.

        Returns per-type (image/video) and overall counts plus duration
        statistics over tasks that have parseable created_at/completed_at,
        and throughput windows (last hour / last 24h). Never raises on
        malformed entries.
        """
        def _empty_type() -> Dict[str, Any]:
            return {
                'completed_count': 0,
                'failed_count': 0,
                'cancelled_count': 0,
                'avg_duration_seconds': 0.0,
                'p50_duration_seconds': 0.0,
                'max_duration_seconds': 0.0,
            }

        by_type = {
            'image': _empty_type(),
            'video': _empty_type(),
        }
        overall = _empty_type()

        # Duration buckets for percentile computation
        durations: Dict[str, List[float]] = {
            'image': [],
            'video': [],
            'overall': [],
        }

        now = datetime.now(timezone.utc)
        throughput_last_hour = 0
        throughput_last_24h = 0

        for task in self.tasks.values():
            if not isinstance(task, dict):
                continue

            status = task.get('status')
            task_type = task.get('type')

            # Count terminal statuses per type and overall
            if status == 'completed':
                if task_type in by_type:
                    by_type[task_type]['completed_count'] += 1
                overall['completed_count'] += 1
            elif status == 'failed':
                if task_type in by_type:
                    by_type[task_type]['failed_count'] += 1
                overall['failed_count'] += 1
            elif status == 'cancelled':
                if task_type in by_type:
                    by_type[task_type]['cancelled_count'] += 1
                overall['cancelled_count'] += 1

            # Duration stats only for tasks with both timestamps parseable
            duration = self._duration_seconds(task)
            if duration is not None:
                if task_type in durations:
                    durations[task_type].append(duration)
                durations['overall'].append(duration)

            # Throughput: count tasks completed within the window
            completed_at = self._parse_datetime(task.get('completed_at'))
            if completed_at is not None:
                age = (now - completed_at).total_seconds()
                if 0 <= age <= 3600:
                    throughput_last_hour += 1
                if 0 <= age <= 86400:
                    throughput_last_24h += 1

        # Compute duration stats for each bucket
        for key, bucket in durations.items():
            if not bucket:
                continue
            avg = sum(bucket) / len(bucket)
            p50 = self._percentile(bucket, 50)
            mx = max(bucket)
            if key == 'overall':
                overall['avg_duration_seconds'] = round(avg, 2)
                overall['p50_duration_seconds'] = round(p50, 2)
                overall['max_duration_seconds'] = round(mx, 2)
            else:
                by_type[key]['avg_duration_seconds'] = round(avg, 2)
                by_type[key]['p50_duration_seconds'] = round(p50, 2)
                by_type[key]['max_duration_seconds'] = round(mx, 2)

        total = sum(by_type[t]['completed_count'] + by_type[t]['failed_count'] + by_type[t]['cancelled_count'] for t in by_type)

        return {
            'total': total,
            'by_type': by_type,
            'overall': overall,
            'throughput_last_hour': throughput_last_hour,
            'throughput_last_24h': throughput_last_24h,
            'generated_at': now.isoformat(),
        }

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        """Return the pct-th percentile of a list of numbers (nearest-rank)."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        idx = max(0, int(round((pct / 100.0) * len(sorted_values))) - 1)
        return sorted_values[idx]

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
            task['duration_seconds'] = self._duration_seconds(task)
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
                self.tasks[task_id]['duration_seconds'] = self._duration_seconds(self.tasks[task_id])
                self._persist()
                return

            # ... rest of image generation pipeline ...
            # (unchanged; completion/failure paths below also set duration)

        except Exception as e:
            logger.error(f"Image generation error for {task_id}: {e}")
            task = self.tasks.get(task_id)
            if task:
                task['status'] = 'failed'
                task['error'] = str(e)
                task['completed_at'] = datetime.now()
                task['duration_seconds'] = self._duration_seconds(task)
                self._persist()

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

        # Start async task
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

            # ... video generation pipeline ...
            # (unchanged; completion/failure paths below also set duration)

        except Exception as e:
            logger.error(f"Video generation error for {task_id}: {e}")
            task = self.tasks.get(task_id)
            if task:
                task['status'] = 'failed'
                task['error'] = str(e)
                task['completed_at'] = datetime.now()
                task['duration_seconds'] = self._duration_seconds(task)
                self._persist()
