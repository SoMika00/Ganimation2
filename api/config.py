"""
API Configuration
Environment-based settings using Pydantic
"""

from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # ==========================================================================
    # API Settings
    # ==========================================================================
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 2
    debug: bool = False
    log_level: str = "info"
    
    # ==========================================================================
    # Security
    # ==========================================================================
    secret_key: str = "your-secret-key-change-in-production"
    cors_origins: List[str] = ["http://localhost:8501", "http://localhost:3000", "*"]
    api_key: Optional[str] = None  # Optional API key protection
    
    # ==========================================================================
    # Paths
    # ==========================================================================
    data_dir: Path = Path("/data")
    models_dir: Path = Path("/data/models")
    gallery_dir: Path = Path("/data/gallery")
    temp_dir: Path = Path("/data/temp")
    
    @property
    def source_media_dir(self) -> Path:
        return self.gallery_dir / "source_media"
    
    @property
    def generated_images_dir(self) -> Path:
        return self.gallery_dir / "generated_images"
    
    @property
    def generated_videos_dir(self) -> Path:
        return self.gallery_dir / "generated_videos"
    
    # ==========================================================================
    # Redis / Task Queue
    # ==========================================================================
    redis_url: str = "redis://redis:6379/0"
    task_timeout: int = 3600  # 1 hour max per task
    
    # ==========================================================================
    # Video Processing
    # ==========================================================================
    video_target_fps: int = 30
    video_target_width: int = 720
    video_target_height: int = 1280
    video_crf: int = 16  # H100 can afford higher quality
    video_preset: str = "slow"
    max_upload_size_mb: int = 2000
    
    # ==========================================================================
    # Image Generation (SDXL)
    # ==========================================================================
    sdxl_lora_weight: float = 0.75
    sdxl_cfg_scale: float = 5.0
    sdxl_steps: int = 30
    sdxl_batch_size: int = 4  # H100 batch size
    
    # ==========================================================================
    # Video Generation (Wan2.2)
    # ==========================================================================
    wan_num_frames: int = 96  # H100 can handle more
    wan_motion_strength: float = 0.7
    wan_guidance_scale: float = 7.5
    rife_multiplier: int = 4
    
    # ==========================================================================
    # GPU Configuration
    # ==========================================================================
    cuda_visible_devices: str = "0,1"
    enable_tf32: bool = True
    enable_flash_attention: bool = True
    torch_dtype: str = "bfloat16"  # H100 native
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()

