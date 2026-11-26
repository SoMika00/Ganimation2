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

# Valid task statuses / types (used for filtering)
VALID_STATUSES = {'pending', 'processing', 'completed', 'failed', 'cancelled'}
VALID_TYPES = {'image', 'video'}


def _iso_to_datetime(value: Any) -> Any:
    """Parse an ISO-format string back into a datetime (best-effort)."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return value
    return value


def _serialize_datetime(value: Any) -> Any:
    """Serialize a datetime (or ISO string) to an ISO-format string."""
    if isinstance(value, datetime):
        return value.isoformat()
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
    # Filtering
    # =========================================================================

    def _filter_tasks(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return all tasks matching the given filters, sorted by created_at
        descending (most recent first).

        - status: exact match on task status (pending/processing/completed/
          failed/cancelled).
        - task_type: exact match on task type (image/video).
        - search: case-insensitive substring match against task_id, message,
          and error fields.
        """
        tasks = list(self.tasks.values())

        if status is not None:
            tasks = [t for t in tasks if t.get('status') == status]

        if task_type is not None:
            tasks = [t for t in tasks if t.get('type') == task_type]

        if search:
            needle = search.lower()
            filtered = []
            for t in tasks:
                haystacks = [
                    str(t.get('task_id') or ''),
                    str(t.get('message') or ''),
                    str(t.get('error') or ''),
                ]
                if any(needle in h.lower() for h in haystacks):
                    filtered.append(t)
            tasks = filtered

        # Sort by created_at desc (most recent first), tolerating missing values
        tasks.sort(
            key=lambda t: t.get('created_at') or datetime.min,
            reverse=True,
        )

        return tasks

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
            elif key in by_type:
                by_type[key]['avg_duration_seconds'] = round(avg, 2)
                by_type[key]['p50_duration_seconds'] = round(p50, 2)
                by_type[key]['max_duration_seconds'] = round(mx, 2)

        return {
            'overall': overall,
            'by_type': by_type,
            'throughput_last_hour': throughput_last_hour,
            'throughput_last_24h': throughput_last_24h,
            'generated_at': now.isoformat(),
        }

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        """Compute a percentile from a list of numeric values."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * (pct / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_values) - 1)
        if f == c:
            return sorted_values[f]
        return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)

    # =========================================================================
    # Task Listing / Export
    # =========================================================================

    async def list_tasks(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List generation tasks with optional filtering and pagination."""
        tasks = self._filter_tasks(status=status, task_type=task_type, search=search)

        total = len(tasks)
        page = tasks[offset:offset + limit]

        items = []
        for task in page:
            items.append(self._serialize_task(task))

        return {
            'items': items,
            'total': total,
            'limit': limit,
            'offset': offset,
        }

    def _serialize_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a task dict for API output (datetimes -> ISO strings)."""
        item = dict(task)
        for field in _DATETIME_FIELDS:
            if field in item:
                item[field] = _serialize_datetime(item[field])
        return item

    def export_tasks(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return all tasks matching the given filters (no pagination), capped at
        MAX_PERSISTED_TASKS, with datetimes serialized to ISO strings.
        """
        tasks = self._filter_tasks(status=status, task_type=task_type, search=search)
        tasks = tasks[:MAX_PERSISTED_TASKS]
        return [self._serialize_task(t) for t in tasks]
