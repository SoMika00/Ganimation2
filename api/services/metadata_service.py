"""
Metadata Service
Writes and reads JSON sidecar files for generated media items.

Each generated image/video gets a ``<item_id>.json`` sidecar stored next to
its media file (e.g. ``gallery/generated_images/abc123.png`` +
``gallery/generated_images/abc123.json``). Writes are atomic (temp file +
``os.replace``) and reads tolerate missing/corrupt JSON.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from api.config import settings


# Map a media type string to its configured directory.
_MEDIA_DIRS = {
    "image": settings.generated_images_dir,
    "video": settings.generated_videos_dir,
}


def _dir_for_type(media_type: str) -> Path:
    """Return the directory for a media type, raising on unknown types."""
    try:
        return _MEDIA_DIRS[media_type]
    except KeyError:
        raise ValueError(f"Unknown media type: {media_type}")


def _sidecar_path(media_type: str, item_id: str) -> Path:
    """Return the sidecar path for a media item."""
    directory = _dir_for_type(media_type)
    return directory / f"{item_id}.json"


def write_metadata(media_type: str, item_id: str, data: Dict[str, Any]) -> None:
    """
    Atomically write a metadata sidecar for a media item.

    The data is first written to a temporary file in the same directory and
    then moved into place with ``os.replace`` so readers never observe a
    partially-written file.
    """
    directory = _dir_for_type(media_type)
    directory.mkdir(parents=True, exist_ok=True)

    final_path = _sidecar_path(media_type, item_id)
    tmp_path = directory / f"{item_id}.json.tmp"

    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, final_path)
    except OSError as e:
        logger.warning(f"Failed to write metadata for {media_type}/{item_id}: {e}")
        # Best-effort cleanup of the temp file.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def read_metadata(media_type: str, item_id: str) -> Optional[Dict[str, Any]]:
    """
    Read a metadata sidecar for a media item.

    Returns ``None`` (and logs a warning) when the sidecar is missing or
    contains corrupt JSON, instead of raising.
    """
    path = _sidecar_path(media_type, item_id)

    if not path.exists():
        return None

    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"Metadata for {media_type}/{item_id} is not a JSON object")
            return None
        return data
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning(f"Failed to read metadata for {media_type}/{item_id}: {e}")
        return None


def delete_metadata(media_type: str, item_id: str) -> bool:
    """
    Delete a metadata sidecar for a media item.

    Returns ``True`` if a sidecar was removed, ``False`` otherwise.
    """
    path = _sidecar_path(media_type, item_id)
    try:
        if path.exists():
            path.unlink()
            return True
        return False
    except OSError as e:
        logger.warning(f"Failed to delete metadata for {media_type}/{item_id}: {e}")
        return False
