"""
System Router
System information, GPU status, and ComfyUI connectivity endpoints
"""

import time
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.services.gpu_manager import GPUManager


router = APIRouter()
gpu_manager = GPUManager()


# =============================================================================
# ComfyUI connectivity preflight (cached ~10s)
# =============================================================================

# In-process cache for the ComfyUI preflight result.
_comfyui_cache: Dict[str, Any] = {
    'timestamp': 0.0,
    'result': None,
}
_COMFYUI_CACHE_TTL = 10.0


def _get_comfyui_status() -> Dict[str, Any]:
    """
    Query ComfyUI connectivity and capabilities.

    Never raises: any network/parse error is captured and reported as
    ``available: false`` with a human-readable message.
    """
    from utils.comfyui_client import ComfyUIClient

    client = ComfyUIClient()
    host = client.host
    port = client.port

    try:
        available = client.is_available()
        if not available:
            return {
                'available': False,
                'host': host,
                'port': port,
                'system_stats': None,
                'capabilities': {
                    'pulid': False,
                    'controlnet_preprocessors': False,
                },
                'message': 'ComfyUI is unreachable. Start it with ./run.sh.',
            }

        system_stats = client.get_system_stats()
        capabilities = {
            'pulid': client.supports_pulid(),
            'controlnet_preprocessors': client.supports_controlnet_preprocessors(),
        }

        return {
            'available': True,
            'host': host,
            'port': port,
            'system_stats': system_stats,
            'capabilities': capabilities,
            'message': 'ComfyUI is connected.',
        }

    except Exception as e:
        logger.warning(f"ComfyUI preflight error: {e}")
        return {
            'available': False,
            'host': host,
            'port': port,
            'system_stats': None,
            'capabilities': {
                'pulid': False,
                'controlnet_preprocessors': False,
            },
            'message': f'ComfyUI is unreachable: {e}',
        }


@router.get("/system/comfyui")
async def get_comfyui_status():
    """
    Preflight check for ComfyUI connectivity.

    Returns HTTP 200 with a stable JSON shape regardless of whether ComfyUI
    is reachable. Results are cached in-process for ~10 seconds to avoid
    hammering ComfyUI when the sidebar polls.
    """
    now = time.time()
    cached = _comfyui_cache['result']
    if cached is not None and (now - _comfyui_cache['timestamp']) < _COMFYUI_CACHE_TTL:
        return cached

    result = _get_comfyui_status()
    _comfyui_cache['timestamp'] = now
    _comfyui_cache['result'] = result
    return result


# =============================================================================
# System Info
# =============================================================================

@router.get("/system/info")
async def get_system_info():
    """Get system information"""
    return {
        'name': 'Ganimation Studio API',
        'version': '1.0.0',
        'gpu': gpu_manager.get_info(),
    }


@router.get("/system/gpu")
async def get_gpu_status():
    """Get GPU status"""
    return gpu_manager.get_info()


@router.post("/system/gpu/clear-cache")
async def clear_gpu_cache():
    """Clear GPU memory cache"""
    gpu_manager.clear_cache()
    return {'success': True, 'message': 'GPU cache cleared'}
