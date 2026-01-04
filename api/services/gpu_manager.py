"""
GPU Manager
Handles GPU detection, optimization, and resource management
Optimized for 2x NVIDIA H100
"""

import torch
from typing import Dict, Any, Optional
from loguru import logger


class GPUManager:
    """
    Manages GPU resources and optimizations
    Optimized for 2x H100 (160GB VRAM total)
    """
    
    def __init__(self):
        self.device = "cpu"
        self.dtype = torch.float32
        self.num_gpus = 0
        self.is_h100 = False
        self.total_vram_gb = 0
        
        self._detect_gpus()
        self._apply_optimizations()
    
    def _detect_gpus(self):
        """Detect and configure GPUs"""
        if not torch.cuda.is_available():
            logger.warning("CUDA not available, using CPU")
            return
        
        self.device = "cuda"
        self.num_gpus = torch.cuda.device_count()
        
        # Calculate total VRAM
        for i in range(self.num_gpus):
            props = torch.cuda.get_device_properties(i)
            self.total_vram_gb += props.total_memory / (1024**3)
            
            logger.info(f"GPU {i}: {props.name} - {props.total_memory / (1024**3):.1f}GB")
        
        # Check for H100 (compute capability 9.0)
        major, minor = torch.cuda.get_device_capability(0)
        if major >= 9:
            self.is_h100 = True
            self.dtype = torch.bfloat16
            logger.info("✅ H100 detected - Using BFloat16")
        elif major >= 8:
            # A100
            self.dtype = torch.float16
            logger.info("A100 detected - Using Float16")
        else:
            self.dtype = torch.float16
    
    def _apply_optimizations(self):
        """Apply GPU-specific optimizations"""
        if not torch.cuda.is_available():
            return
        
        # TF32 for faster matmul (H100/A100)
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        
        # cuDNN optimizations
        torch.backends.cudnn.benchmark = True
        torch.backends.cudnn.deterministic = False
        
        # Flash Attention (H100)
        if self.is_h100:
            if hasattr(torch.backends.cuda, 'enable_flash_sdp'):
                torch.backends.cuda.enable_flash_sdp(True)
                torch.backends.cuda.enable_mem_efficient_sdp(True)
                logger.info("✅ Flash Attention 2 enabled")
        
        logger.info("✅ GPU optimizations applied")
    
    def get_info(self) -> Dict[str, Any]:
        """Get GPU information"""
        info = {
            'device': self.device,
            'dtype': str(self.dtype),
            'num_gpus': self.num_gpus,
            'total_vram_gb': round(self.total_vram_gb, 2),
            'is_h100': self.is_h100,
            'cuda_available': torch.cuda.is_available(),
            'gpus': []
        }
        
        if torch.cuda.is_available():
            for i in range(self.num_gpus):
                props = torch.cuda.get_device_properties(i)
                total = props.total_memory / (1024**3)
                allocated = torch.cuda.memory_allocated(i) / (1024**3)
                cached = torch.cuda.memory_reserved(i) / (1024**3)
                
                info['gpus'].append({
                    'id': i,
                    'name': props.name,
                    'total_gb': round(total, 2),
                    'allocated_gb': round(allocated, 2),
                    'cached_gb': round(cached, 2),
                    'free_gb': round(total - cached, 2),
                })
            
            major, minor = torch.cuda.get_device_capability(0)
            info['compute_capability'] = f"{major}.{minor}"
            info['cuda_version'] = torch.version.cuda
        
        return info
    
    def get_optimal_batch_size(self, model_type: str = "sdxl") -> int:
        """Get optimal batch size based on available VRAM"""
        if not torch.cuda.is_available():
            return 1
        
        free_vram = 0
        for i in range(self.num_gpus):
            props = torch.cuda.get_device_properties(i)
            cached = torch.cuda.memory_reserved(i)
            free_vram += props.total_memory - cached
        
        free_vram_gb = free_vram / (1024**3)
        
        # Estimate based on model type
        if model_type == "sdxl":
            # SDXL ~8GB per image at 1024x1024
            if self.is_h100:
                return min(8, max(1, int(free_vram_gb / 10)))
            return min(4, max(1, int(free_vram_gb / 12)))
        
        elif model_type == "wan2":
            # Wan2.2 ~20GB per video generation
            if self.is_h100:
                return min(4, max(1, int(free_vram_gb / 25)))
            return min(2, max(1, int(free_vram_gb / 30)))
        
        return 1
    
    def clear_cache(self):
        """Clear GPU memory cache"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            logger.info("GPU cache cleared")
    
    def cleanup(self):
        """Cleanup GPU resources"""
        self.clear_cache()
        logger.info("GPU resources cleaned up")
    
    def get_device_for_model(self, model_index: int = 0) -> str:
        """Get device string for model placement"""
        if not torch.cuda.is_available():
            return "cpu"
        
        if self.num_gpus > 1:
            # Distribute across GPUs
            gpu_id = model_index % self.num_gpus
            return f"cuda:{gpu_id}"
        
        return "cuda"
    
    def get_device_map(self) -> Optional[str]:
        """Get device map for model parallelism"""
        if self.num_gpus > 1:
            return "balanced"
        return None

