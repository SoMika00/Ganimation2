"""
Storage Service
Computes disk usage and storage health for configured directories.
"""

import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.config import settings


# Thresholds for storage health status
WARNING_THRESHOLD = 85.0
CRITICAL_THRESHOLD = 95.0

# Valid cleanup target names
VALID_CLEANUP_TARGETS = {'temp', 'generated_images', 'generated_videos'}


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

    def _target_directories(self, targets: Optional[List[str]]) -> List[Path]:
        """Resolve cleanup target names to directory paths."""
        if targets is None:
            targets = ["temp"]

        mapping = {
            "temp": settings.temp_dir,
            "generated_images": settings.generated_images_dir,
            "generated_videos": settings.generated_videos_dir,
        }

        directories: List[Path] = []
        for target in targets:
            path = mapping.get(target)
            if path is not None:
                directories.append(Path(path))
        return directories

    def cleanup(
        self,
        dry_run: bool = True,
        older_than_hours: int = 24,
        targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Delete stale files from configured directories.

        Scans the configured directories (default: temp_dir only, plus
        optionally generated_images_dir / generated_videos_dir when named in
        targets). Deletes files whose mtime is older than older_than_hours.
        Never deletes .gitkeep files or directories.

        Returns a structured dict with deleted_count, freed_bytes, freed_human,
        files, errors, and generated_at. Never raises.
        """
        cutoff = time.time() - (older_than_hours * 3600)
        directories = self._target_directories(targets)

        files: List[Dict[str, Any]] = []
        errors: List[str] = []
        deleted_count = 0
        deleted_bytes = 0

        for directory in directories:
            try:
                if not directory.exists():
                    continue
                for entry in os.scandir(directory):
                    try:
                        if entry.name == ".gitkeep":
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue

                        try:
                            stat = entry.stat()
                        except OSError as e:
                            errors.append(f"{entry.path}: {e}")
                            continue

                        if stat.st_mtime >= cutoff:
                            continue

                        size_bytes = stat.st_size
                        files.append({
                            "path": entry.path,
                            "size_bytes": size_bytes,
                            "size_human": self._human_bytes(size_bytes),
                            "mtime": datetime.fromtimestamp(
                                stat.st_mtime, tz=timezone.utc
                            ).isoformat(),
                        })
                        deleted_count += 1
                        deleted_bytes += size_bytes

                        if not dry_run:
                            try:
                                os.remove(entry.path)
                            except OSError as e:
                                errors.append(f"{entry.path}: {e}")
                                deleted_count -= 1
                                deleted_bytes -= size_bytes
                                files.pop()
                    except OSError as e:
                        errors.append(f"{entry.path}: {e}")
            except OSError as e:
                errors.append(f"{directory}: {e}")

        return {
            "dry_run": dry_run,
            "deleted_count": deleted_count,
            "deleted_bytes": deleted_bytes,
            "deleted_human": self._human_bytes(deleted_bytes),
            "freed_bytes": deleted_bytes,
            "freed_human": self._human_bytes(deleted_bytes),
            "files": files,
            "errors": errors,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
