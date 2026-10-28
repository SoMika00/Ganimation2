"""
Storage Service
Computes disk usage and storage health for configured directories.
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.config import settings


# Thresholds for storage health status
WARNING_THRESHOLD = 85.0
CRITICAL_THRESHOLD = 95.0


class StorageService:
    """Compute disk usage summaries for configured directories."""

    def __init__(self, directories: Optional[List[Path]] = None):
        if directories is None:
            directories = [
                settings.source_media_dir,
                settings.generated_images_dir,
                settings.generated_videos_dir,
                settings.temp_dir,
                settings.models_dir,
            ]
        self.directories = [Path(d) for d in directories]

    @staticmethod
    def _human_bytes(num: float) -> str:
        """Format a byte count into a human-readable string (e.g. '1.2 GB')."""
        if num is None:
            return "0 B"
        num = float(num)
        if num < 0:
            num = 0.0
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        value = num
        unit = units[0]
        for u in units:
            if abs(value) < 1024.0 or u == units[-1]:
                unit = u
                break
            value /= 1024.0
        if unit == "B":
            return f"{int(value)} B"
        return f"{value:.1f} {unit}"

    @staticmethod
    def _walk_directory(path: Path) -> Dict[str, Any]:
        """
        Walk a directory and return file_count and total_bytes.

        Never raises: missing directories and permission errors are tolerated
        and reported as zero counts.
        """
        result = {"file_count": 0, "total_bytes": 0}
        try:
            if not path.exists():
                return result
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        result["file_count"] += 1
                        try:
                            result["total_bytes"] += entry.stat().st_size
                        except OSError:
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        sub = StorageService._walk_directory(Path(entry.path))
                        result["file_count"] += sub["file_count"]
                        result["total_bytes"] += sub["total_bytes"]
                except OSError:
                    continue
        except OSError:
            pass
        return result

    def _directory_summary(self, path: Path) -> Dict[str, Any]:
        """Build a per-directory summary entry."""
        path = Path(path)
        exists = False
        unreadable = False
        try:
            exists = path.exists()
        except OSError:
            exists = False
            unreadable = True

        walk = {"file_count": 0, "total_bytes": 0}
        if exists and not unreadable:
            walk = self._walk_directory(path)

        total_bytes = walk["total_bytes"]
        file_count = walk["file_count"]

        free_bytes = 0
        total_disk_bytes = 0
        used_percent = 0.0
        try:
            usage = shutil.disk_usage(str(path))
            total_disk_bytes = usage.total
            free_bytes = usage.free
            used = usage.total - usage.free
            used_percent = (used / usage.total * 100.0) if usage.total > 0 else 0.0
        except OSError:
            unreadable = True

        return {
            "path": str(path),
            "exists": exists,
            "file_count": file_count,
            "total_bytes": total_bytes,
            "total_human": self._human_bytes(total_bytes),
            "free_bytes": free_bytes,
            "free_human": self._human_bytes(free_bytes),
            "total_disk_bytes": total_disk_bytes,
            "used_percent": round(used_percent, 2),
            "unreadable": unreadable,
        }

    def get_storage_summary(self) -> Dict[str, Any]:
        """
        Compute a full storage summary for all configured directories.

        Returns a dict with per-directory entries, a top-level status, and a
        generated_at ISO timestamp. Never raises.
        """
        directories: List[Dict[str, Any]] = []
        status = "ok"

        for path in self.directories:
            entry = self._directory_summary(path)
            directories.append(entry)

            if not entry["exists"] or entry["unreadable"]:
                status = "critical"
            elif entry["used_percent"] >= CRITICAL_THRESHOLD:
                status = "critical"
            elif entry["used_percent"] >= WARNING_THRESHOLD and status == "ok":
                status = "warning"

        return {
            "status": status,
            "directories": directories,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
