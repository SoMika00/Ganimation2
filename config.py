"""
Ganimation Studio Configuration
Central configuration for all settings and paths
Optimized for 2x NVIDIA H100 (160GB VRAM)
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import json
import torch


# ============================================================================
# GPU Configuration for 2x H100
# ============================================================================

def get_gpu_config() -> Dict[str, Any]:
    """Detect and configure GPUs optimally for H100"""
    config = {
        'device': 'cpu',
        'dtype': torch.float32,
        'num_gpus': 0,
        'total_vram_gb': 0,
        'is_h100': False,
        'enable_flash_attention': False,
        'enable_tf32': False,
        'multi_gpu': False,
    }
    
    if torch.cuda.is_available():
        config['num_gpus'] = torch.cuda.device_count()
        config['device'] = 'cuda'
        
        # Calculate total VRAM
        total_vram = 0
        for i in range(config['num_gpus']):
            total_vram += torch.cuda.get_device_properties(i).total_memory
        config['total_vram_gb'] = total_vram / (1024**3)
        
        # Check for H100 (compute capability 9.0)
        major, minor = torch.cuda.get_device_capability(0)
        if major >= 9:
            config['is_h100'] = True
            config['enable_flash_attention'] = True
            config['enable_tf32'] = True
            config['dtype'] = torch.bfloat16  # H100 is optimized for bfloat16
        elif major >= 8:
            # A100 or similar
            config['dtype'] = torch.float16
            config['enable_tf32'] = True
        else:
            config['dtype'] = torch.float16
        
        # Multi-GPU setup
        if config['num_gpus'] > 1:
            config['multi_gpu'] = True
    
    return config

GPU_CONFIG = get_gpu_config()


# ============================================================================
# Dataclass Configurations
# ============================================================================

@dataclass
class VideoConfig:
    """Video processing configuration"""
    target_fps: int = 30
    target_width: int = 720
    target_height: int = 1280  # 9:16 shorts format
    fallback_width: int = 480
    fallback_height: int = 854
    
    # Encoding settings - optimized for quality with H100 power
    video_codec: str = "libx264"
    crf: int = 16  # Higher quality with 2x H100
    preset: str = "slow"  # Better quality, we have the compute
    pixel_format: str = "yuv420p"
    
    # Audio settings
    audio_codec: str = "aac"
    audio_bitrate: str = "256k"  # Higher audio quality


@dataclass
class ImageGenConfig:
    """Image generation (SDXL) configuration - H100 optimized"""
    # LoRA settings
    lora_model: str = "ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style"
    lora_weight: float = 0.75
    lora_trigger: str = "Studio Ghibli style"
    
    # Sampling settings - can afford more steps with H100
    cfg_scale: float = 5.0
    steps: int = 30  # More steps for quality
    sampler: str = "DPM++ 2M Karras"
    
    # ControlNet settings
    controlnet_type: str = "depth"
    controlnet_strength: float = 0.6
    
    # Output settings - H100 can handle full resolution
    output_size: tuple = (1024, 1024)
    
    # Batch processing - leverage H100 VRAM
    batch_size: int = 4  # Can generate multiple variations at once
    
    # H100 specific
    use_flash_attention: bool = GPU_CONFIG['enable_flash_attention']
    dtype: str = "bfloat16" if GPU_CONFIG['is_h100'] else "float16"
    compile_model: bool = True  # torch.compile for H100
    
    # Prompts
    base_prompt: str = "Studio Ghibli style, anime illustration, masterpiece, high quality, detailed, beautiful lighting"
    negative_prompt: str = "low quality, bad anatomy, worst quality, low resolution, blurry, distorted, ugly, duplicate, watermark, signature, jpeg artifacts"


@dataclass
class VideoGenConfig:
    """Video generation (Wan2.2) configuration - H100 optimized"""
    # Animation settings - more frames with H100
    motion_strength: float = 0.7
    num_frames: int = 96  # Double frames with H100 power
    guidance_scale: float = 7.5
    num_inference_steps: int = 40  # More steps for quality
    
    # Relighting LoRA
    use_relighting: bool = False
    relight_strength: float = 0.5
    
    # Post-processing - enable all with H100
    use_rife: bool = True
    rife_multiplier: int = 4  # 4x interpolation for smooth 120fps capable
    use_upscale: bool = True  # Enable upscaling
    upscale_factor: int = 2
    merge_audio: bool = True
    
    # Output settings
    output_fps: int = 30
    output_crf: int = 16  # Higher quality
    output_preset: str = "slow"  # Better compression
    
    # H100 specific
    use_flash_attention: bool = GPU_CONFIG['enable_flash_attention']
    dtype: str = "bfloat16" if GPU_CONFIG['is_h100'] else "float16"
    multi_gpu: bool = GPU_CONFIG['multi_gpu']


@dataclass
class PathConfig:
    """Path configuration"""
    root: Path = field(default_factory=lambda: Path(__file__).parent)
    
    @property
    def gallery(self) -> Path:
        return self.root / "gallery"
    
    @property
    def source_media(self) -> Path:
        return self.gallery / "source_media"
    
    @property
    def generated_images(self) -> Path:
        return self.gallery / "generated_images"
    
    @property
    def generated_videos(self) -> Path:
        return self.gallery / "generated_videos"
    
    @property
    def temp(self) -> Path:
        return self.root / "temp"
    
    @property
    def models(self) -> Path:
        return self.root / "models"
    
    def ensure_directories(self):
        """Create all required directories"""
        for path in [
            self.source_media,
            self.generated_images,
            self.generated_videos,
            self.temp,
            self.models,
            self.models / "wan2.2",
            self.models / "rife",
            self.models / "realesrgan",
        ]:
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class H100Config:
    """H100-specific optimizations"""
    # Memory settings
    enable_model_cpu_offload: bool = False  # Not needed with 160GB VRAM
    enable_sequential_cpu_offload: bool = False
    enable_attention_slicing: bool = False  # Not needed
    enable_vae_slicing: bool = False
    enable_vae_tiling: bool = False
    
    # Performance settings
    enable_xformers: bool = True
    enable_flash_attention_2: bool = True
    enable_torch_compile: bool = True
    compile_mode: str = "reduce-overhead"  # or "max-autotune"
    
    # TF32 for matrix operations
    enable_tf32: bool = True
    
    # Multi-GPU
    use_device_map: str = "balanced"  # Distribute across GPUs
    
    # Batch sizes (leverage VRAM)
    image_batch_size: int = 4
    video_batch_size: int = 2
    
    # Cache settings
    enable_model_cache: bool = True
    cache_dir: str = "~/.cache/huggingface"


@dataclass 
class AppConfig:
    """Main application configuration"""
    video: VideoConfig = field(default_factory=VideoConfig)
    image_gen: ImageGenConfig = field(default_factory=ImageGenConfig)
    video_gen: VideoGenConfig = field(default_factory=VideoGenConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    h100: H100Config = field(default_factory=H100Config)
    
    # App settings
    app_name: str = "Ganimation Studio"
    app_version: str = "1.0.0"
    theme: str = "dark"
    
    # GPU info
    gpu_config: Dict = field(default_factory=lambda: GPU_CONFIG)
    
    def save(self, path: Optional[Path] = None):
        """Save configuration to JSON file"""
        if path is None:
            path = self.paths.root / "config.json"
        
        config_dict = {
            'video': {
                'target_fps': self.video.target_fps,
                'target_width': self.video.target_width,
                'target_height': self.video.target_height,
                'crf': self.video.crf,
                'preset': self.video.preset,
            },
            'image_gen': {
                'lora_weight': self.image_gen.lora_weight,
                'cfg_scale': self.image_gen.cfg_scale,
                'steps': self.image_gen.steps,
                'sampler': self.image_gen.sampler,
                'controlnet_type': self.image_gen.controlnet_type,
                'controlnet_strength': self.image_gen.controlnet_strength,
                'batch_size': self.image_gen.batch_size,
            },
            'video_gen': {
                'motion_strength': self.video_gen.motion_strength,
                'num_frames': self.video_gen.num_frames,
                'guidance_scale': self.video_gen.guidance_scale,
                'num_inference_steps': self.video_gen.num_inference_steps,
                'use_rife': self.video_gen.use_rife,
                'rife_multiplier': self.video_gen.rife_multiplier,
                'use_upscale': self.video_gen.use_upscale,
            },
            'h100': {
                'enable_flash_attention_2': self.h100.enable_flash_attention_2,
                'enable_torch_compile': self.h100.enable_torch_compile,
                'enable_tf32': self.h100.enable_tf32,
            },
            'app': {
                'theme': self.theme,
            },
            'gpu': self.gpu_config
        }
        
        with open(path, 'w') as f:
            json.dump(config_dict, f, indent=2)
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> 'AppConfig':
        """Load configuration from JSON file"""
        config = cls()
        
        if path is None:
            path = config.paths.root / "config.json"
        
        if path.exists():
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                
                # Update configs from file
                for section in ['video', 'image_gen', 'video_gen', 'h100']:
                    if section in data:
                        target = getattr(config, section)
                        for key, value in data[section].items():
                            if hasattr(target, key):
                                setattr(target, key, value)
                
                if 'app' in data and 'theme' in data['app']:
                    config.theme = data['app']['theme']
                
            except Exception as e:
                print(f"Error loading config: {e}")
        
        return config


# Global config instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the global configuration instance"""
    global _config
    if _config is None:
        _config = AppConfig.load()
        _config.paths.ensure_directories()
        
        # Apply H100 optimizations
        if _config.gpu_config.get('is_h100'):
            _apply_h100_optimizations()
    
    return _config


def _apply_h100_optimizations():
    """Apply H100-specific PyTorch optimizations"""
    import torch
    
    # Enable TF32 for matmul and convolutions
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    
    # Set optimal cudnn settings
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.deterministic = False
    
    # Enable flash attention if available
    if hasattr(torch.nn.functional, 'scaled_dot_product_attention'):
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
    
    print("✅ H100 optimizations applied: TF32, Flash Attention, cuDNN benchmark")


def reload_config():
    """Reload configuration from file"""
    global _config
    _config = AppConfig.load()
    _config.paths.ensure_directories()
    return _config


# Model download URLs
MODEL_URLS = {
    'sdxl_base': 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0',
    'lora_ghibli': 'https://huggingface.co/ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style',
    'controlnet_depth': 'https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0',
    'controlnet_canny': 'https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0',
    'rife': 'https://github.com/megvii-research/ECCV2022-RIFE',
    'realesrgan': 'https://github.com/xinntao/Real-ESRGAN',
}


# H100 Performance Tips
H100_TIPS = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                    🚀 H100 OPTIMIZATION GUIDE                             ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                           ║
║  Your 2x H100 setup provides:                                             ║
║  • 160GB total VRAM - Load full models without offloading                 ║
║  • BFloat16 native support - Better precision than FP16                   ║
║  • Flash Attention 2 - 3-4x faster attention computation                  ║
║  • TF32 Tensor Cores - 8x faster than FP32 on matrix ops                  ║
║  • Hopper architecture - Latest CUDA optimizations                        ║
║                                                                           ║
║  Recommended settings:                                                    ║
║  • Batch size: 4+ for image generation                                    ║
║  • Video frames: 96+ per generation                                       ║
║  • RIFE multiplier: 4x for silky smooth output                            ║
║  • Enable upscaling: Yes, you have the power                              ║
║  • torch.compile: Enabled for 20-30% speedup                              ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""
