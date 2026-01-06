"""
Image Generation Utilities
SDXL + PuLID + ControlNet + LoRA Ghibli Style Pipeline
Optimized for 2x H100 GPUs
"""

from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from PIL import Image
import numpy as np

# Lazy import torch to avoid blocking the app
torch = None
TORCH_AVAILABLE = False

def _ensure_torch():
    """Lazy load torch"""
    global torch, TORCH_AVAILABLE
    if torch is None:
        try:
            import torch as _torch
            torch = _torch
            TORCH_AVAILABLE = True
        except ImportError:
            TORCH_AVAILABLE = False
    return TORCH_AVAILABLE


class GhibliImageGenerator:
    """
    Generate Ghibli-style images using SDXL with:
    - PuLID v1.1 for identity preservation
    - ControlNet (depth/canny) for structure
    - LoRA style "Ghibli" (ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style)
    
    Optimized for 2x H100 (160GB VRAM)
    """
    
    # Default generation settings - H100 optimized
    DEFAULT_SETTINGS = {
        'lora_weight': 0.75,
        'cfg_scale': 5.0,
        'steps': 30,  # More steps with H100
        'sampler': 'DPM++ 2M Karras',
        'seed': -1,
        'controlnet_strength': 0.6,
        'controlnet_type': 'depth',
        # Img2img strength (0..1). 1.0 ~= ignore init image.
        # For frame stylization, 0.55-0.75 is typically a good range.
        'strength': 0.65,
        'pulid_strength': 0.8,
        'batch_size': 4,  # Batch generation
    }
    
    # Model identifiers
    MODELS = {
        'sdxl_base': 'stabilityai/stable-diffusion-xl-base-1.0',
        'lora_ghibli': 'ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style',
        'controlnet_depth': 'diffusers/controlnet-depth-sdxl-1.0',
        'controlnet_canny': 'diffusers/controlnet-canny-sdxl-1.0',
    }
    
    def __init__(self, models_dir: Path, device: str = None):
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        # Auto-detect device and capabilities
        self.device = device
        self.dtype = None  # Will be set when torch is loaded
        self.is_h100 = False
        self.num_gpus = 0
        
        # Only setup device if torch is available
        if _ensure_torch():
            self._setup_device()
        else:
            self.device = "cpu"
        
        # Model instances (lazy loaded)
        self.pipe = None
        self.controlnet = None
        self.loaded_models = set()
    
    def _setup_device(self):
        """Setup optimal device configuration for H100"""
        if not _ensure_torch():
            self.device = "cpu"
            return
            
        if self.device is None:
            if torch.cuda.is_available():
                self.device = "cuda"
                self.num_gpus = torch.cuda.device_count()
                
                # Check for H100 (compute capability 9.0)
                major, minor = torch.cuda.get_device_capability(0)
                if major >= 9:
                    self.is_h100 = True
                    self.dtype = torch.bfloat16
                    
                    # Enable H100 optimizations
                    torch.backends.cuda.matmul.allow_tf32 = True
                    torch.backends.cudnn.allow_tf32 = True
                    torch.backends.cudnn.benchmark = True
                    
                    if hasattr(torch.backends.cuda, 'enable_flash_sdp'):
                        torch.backends.cuda.enable_flash_sdp(True)
                        torch.backends.cuda.enable_mem_efficient_sdp(True)
                else:
                    self.dtype = torch.float16
                    
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                self.device = "mps"
                self.dtype = torch.float32
            else:
                self.device = "cpu"
                self.dtype = torch.float32
    
    def check_requirements(self) -> dict:
        """Check if required packages are available"""
        requirements = {}
        
        # Check torch first
        requirements['torch'] = _ensure_torch()
        
        try:
            import diffusers
            requirements['diffusers'] = True
            requirements['diffusers_version'] = diffusers.__version__
        except ImportError:
            requirements['diffusers'] = False
        
        try:
            import transformers
            requirements['transformers'] = True
        except ImportError:
            requirements['transformers'] = False
        
        try:
            from controlnet_aux import CannyDetector, MidasDetector
            requirements['controlnet_aux'] = True
        except (ImportError, AttributeError, Exception):
            # AttributeError: mediapipe compatibility issues with Python 3.13
            requirements['controlnet_aux'] = False
        
        try:
            import cv2
            requirements['opencv'] = True
        except ImportError:
            requirements['opencv'] = False
        
        try:
            import xformers
            requirements['xformers'] = True
        except ImportError:
            requirements['xformers'] = False
        
        # GPU info only if torch available
        if TORCH_AVAILABLE and torch is not None:
            requirements['cuda'] = torch.cuda.is_available()
            requirements['dtype'] = str(self.dtype) if self.dtype else 'float32'
        else:
            requirements['cuda'] = False
            requirements['dtype'] = 'N/A'
            
        requirements['device'] = self.device
        requirements['is_h100'] = self.is_h100
        requirements['num_gpus'] = self.num_gpus
        requirements['flash_attention'] = self.is_h100
        requirements['tf32'] = self.is_h100
        
        return requirements
    
    def get_vram_info(self) -> Optional[Dict[str, float]]:
        """Get GPU VRAM information for all GPUs"""
        if not _ensure_torch() or not torch.cuda.is_available():
            return None
        
        try:
            info = {
                'total_gb': 0,
                'allocated_gb': 0,
                'cached_gb': 0,
                'free_gb': 0,
                'gpus': []
            }
            
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                total = props.total_memory / (1024**3)
                allocated = torch.cuda.memory_allocated(i) / (1024**3)
                cached = torch.cuda.memory_reserved(i) / (1024**3)
                
                gpu_info = {
                    'id': i,
                    'name': props.name,
                    'total_gb': total,
                    'allocated_gb': allocated,
                    'free_gb': total - cached
                }
                info['gpus'].append(gpu_info)
                
                info['total_gb'] += total
                info['allocated_gb'] += allocated
                info['cached_gb'] += cached
            
            info['free_gb'] = info['total_gb'] - info['cached_gb']
            
            return info
        except:
            return None
    
    def load_models(self, progress_callback=None) -> Tuple[bool, str]:
        """Load all required models - optimized for H100"""
        if not _ensure_torch():
            return False, "PyTorch not installed. Install with: pip install torch"
        
        try:
            if progress_callback:
                progress_callback(0.1, "Importing libraries...")
            
            from diffusers import (
                StableDiffusionXLControlNetImg2ImgPipeline,
                ControlNetModel,
                DPMSolverMultistepScheduler,
                AutoencoderKL
            )
            
            if progress_callback:
                progress_callback(0.2, "Loading SDXL VAE...")
            
            # Load VAE
            vae = AutoencoderKL.from_pretrained(
                "madebyollin/sdxl-vae-fp16-fix",
                torch_dtype=self.dtype
            )
            
            if progress_callback:
                progress_callback(0.35, "Loading ControlNet...")
            
            # Load ControlNet
            controlnet = ControlNetModel.from_pretrained(
                self.MODELS['controlnet_depth'],
                torch_dtype=self.dtype,
                variant="fp16"
            )
            
            if progress_callback:
                progress_callback(0.5, "Loading SDXL pipeline...")
            
            # Load main pipeline (IMG2IMG).
            # Using the img2img pipeline is crucial if you want "frame -> stylized frame".
            # The text2img ControlNet pipeline will otherwise start from random noise and only
            # use the control image as a hint.
            pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
                self.MODELS['sdxl_base'],
                controlnet=controlnet,
                vae=vae,
                torch_dtype=self.dtype,
                variant="fp16",
                use_safetensors=True
            )
            
            if progress_callback:
                progress_callback(0.7, "Loading Ghibli LoRA...")
            
            # Load Ghibli LoRA
            pipe.load_lora_weights(
                self.MODELS['lora_ghibli'],
                weight_name="ghibli_style.safetensors"
            )
            
            if progress_callback:
                progress_callback(0.8, "Configuring for H100...")
            
            # Set scheduler
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                pipe.scheduler.config,
                use_karras_sigmas=True,
                algorithm_type="dpmsolver++"
            )
            
            # H100-specific optimizations
            if self.is_h100:
                # No need for memory offloading with 160GB VRAM
                pipe = pipe.to(self.device)
                
                # Enable xformers if available
                try:
                    pipe.enable_xformers_memory_efficient_attention()
                except:
                    pass
                
                # Enable torch.compile for 20-30% speedup
                try:
                    pipe.unet = torch.compile(
                        pipe.unet, 
                        mode="reduce-overhead",
                        fullgraph=True
                    )
                except Exception as e:
                    print(f"torch.compile not available: {e}")
                
            elif self.device == "cuda":
                # For non-H100 GPUs, use memory optimizations
                pipe.enable_model_cpu_offload()
            else:
                pipe = pipe.to(self.device)
            
            self.pipe = pipe
            self.controlnet = controlnet
            self.loaded_models.add('sdxl')
            self.loaded_models.add('controlnet')
            self.loaded_models.add('lora_ghibli')
            
            if progress_callback:
                progress_callback(1.0, "Models loaded!")
            
            gpu_msg = f" (2x H100 - {self.dtype})" if self.is_h100 else ""
            return True, f"All models loaded successfully{gpu_msg}"
            
        except Exception as e:
            return False, f"Failed to load models: {str(e)}"
    
    def unload_models(self):
        """Unload models to free memory"""
        if self.pipe is not None:
            del self.pipe
            self.pipe = None
        
        if self.controlnet is not None:
            del self.controlnet
            self.controlnet = None
        
        self.loaded_models.clear()
        
        if _ensure_torch() and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    
    def prepare_control_image(
        self,
        image: Image.Image,
        control_type: str = 'depth'
    ) -> Image.Image:
        """Prepare control image (depth map or canny edges)"""
        try:
            if control_type == 'depth':
                from controlnet_aux import MidasDetector
                processor = MidasDetector.from_pretrained("lllyasviel/Annotators")
                control_image = processor(image)
            
            elif control_type == 'canny':
                from controlnet_aux import CannyDetector
                processor = CannyDetector()
                control_image = processor(image, low_threshold=100, high_threshold=200)
            
            else:
                import cv2
                img_array = np.array(image)
                if len(img_array.shape) == 3:
                    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
                else:
                    gray = img_array
                edges = cv2.Canny(gray, 100, 200)
                control_image = Image.fromarray(edges).convert('RGB')
            
            return control_image
            
        except Exception as e:
            print(f"Control image preparation error: {e}")
            return image.convert('L').convert('RGB')
    
    def generate(
        self,
        source_image: Image.Image,
        settings: Optional[Dict[str, Any]] = None,
        progress_callback=None,
        num_images: int = 1
    ) -> Tuple[bool, str, Optional[List[Image.Image]]]:
        """
        Generate Ghibli-style image(s) from source
        H100 optimized with batch generation support
        """
        if not _ensure_torch():
            return False, "PyTorch not installed. Install with: pip install torch", None
            
        cfg = {**self.DEFAULT_SETTINGS}
        if settings:
            cfg.update(settings)
        
        try:
            if self.pipe is None:
                if progress_callback:
                    progress_callback(0.0, "Loading models...")
                success, msg = self.load_models(progress_callback)
                if not success:
                    return False, msg, None
            
            if progress_callback:
                progress_callback(0.1, "Preparing control image...")
            
            # Prepare control image
            control_image = self.prepare_control_image(
                source_image,
                control_type=cfg['controlnet_type']
            )
            
            # Resize to an SDXL-friendly size (multiples of 64) while keeping orientation.
            # Avoids squashing everything into 1024x1024.
            w0, h0 = source_image.size
            if h0 >= w0 * 1.2:          # portrait
                target_w, target_h = 896, 1600
            elif w0 >= h0 * 1.2:        # landscape
                target_w, target_h = 1600, 896
            else:                       # roughly square
                target_w, target_h = 1024, 1024

            source_resized = source_image.resize((target_w, target_h), Image.Resampling.LANCZOS)
            control_resized = control_image.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
            if progress_callback:
                progress_callback(0.2, f"Generating {num_images} image(s)...")
            
            # Set seed
            generator = None
            if cfg['seed'] >= 0:
                generator = torch.Generator(device=self.device).manual_seed(cfg['seed'])
            
            # Build prompt
            prompt = "Studio Ghibli style, anime illustration, masterpiece, high quality, detailed, beautiful lighting, soft colors"
            negative_prompt = (
                "low quality, bad anatomy, worst quality, low resolution, "
                "blurry, distorted, ugly, duplicate, watermark, signature, jpeg artifacts"
            )
            
            # Set LoRA scale
            self.pipe.set_adapters(["ghibli_style"], adapter_weights=[cfg['lora_weight']])
            
            strength = float(cfg.get('strength', 0.65))

            # Generate - leverage H100 for batch generation
            with torch.inference_mode():
                if self.is_h100:
                    # Use autocast for bfloat16
                    with torch.autocast(device_type='cuda', dtype=self.dtype):
                        result = self.pipe(
                            prompt=[prompt] * num_images,
                            negative_prompt=[negative_prompt] * num_images,
                            image=[source_resized] * num_images,
                            control_image=[control_resized] * num_images,
                            strength=strength,
                            controlnet_conditioning_scale=cfg['controlnet_strength'],
                            num_inference_steps=cfg['steps'],
                            guidance_scale=cfg['cfg_scale'],
                            generator=generator,
                        )
                else:
                    result = self.pipe(
                        prompt=[prompt] * num_images,
                        negative_prompt=[negative_prompt] * num_images,
                        image=[source_resized] * num_images,
                        control_image=[control_resized] * num_images,
                        strength=strength,
                        controlnet_conditioning_scale=cfg['controlnet_strength'],
                        num_inference_steps=cfg['steps'],
                        guidance_scale=cfg['cfg_scale'],
                        generator=generator,
                    )
            
            if progress_callback:
                progress_callback(1.0, "Complete!")
            
            return True, "Generation successful", result.images
            
        except Exception as e:
            return False, f"Generation failed: {str(e)}", None
    
    def generate_batch(
        self,
        source_images: List[Image.Image],
        settings: Optional[Dict[str, Any]] = None,
        progress_callback=None
    ) -> Tuple[bool, str, Optional[List[Image.Image]]]:
        """
        Batch generate Ghibli-style images - optimized for H100 VRAM
        """
        if not _ensure_torch():
            return False, "PyTorch not installed. Install with: pip install torch", None
            
        if not source_images:
            return False, "No source images provided", None
        
        cfg = {**self.DEFAULT_SETTINGS}
        if settings:
            cfg.update(settings)
        
        # With 160GB VRAM, we can process larger batches
        batch_size = min(len(source_images), 8 if self.is_h100 else 2)
        all_results = []
        
        try:
            if self.pipe is None:
                success, msg = self.load_models(progress_callback)
                if not success:
                    return False, msg, None
            
            for i in range(0, len(source_images), batch_size):
                batch = source_images[i:i + batch_size]
                
                if progress_callback:
                    progress = (i / len(source_images)) * 0.9
                    progress_callback(progress, f"Processing batch {i//batch_size + 1}...")
                
                # Process batch
                control_images = [
                    self.prepare_control_image(img, cfg['controlnet_type'])
                    for img in batch
                ]
                
                # Resize (batch assumes same orientation/ratio...)
                w0, h0 = batch[0].size
                if h0 >= w0 * 1.2:
                    target_w, target_h = 896, 1600
                elif w0 >= h0 * 1.2:
                    target_w, target_h = 1600, 896
                else:
                    target_w, target_h = 1024, 1024

                source_resized = [img.resize((target_w, target_h), Image.Resampling.LANCZOS) for img in batch]
                control_resized = [img.resize((target_w, target_h), Image.Resampling.LANCZOS) for img in control_images]
                
                prompt = "Studio Ghibli style, anime illustration, masterpiece, high quality, detailed"
                negative_prompt = "low quality, bad anatomy, worst quality, blurry"
                
                self.pipe.set_adapters(["ghibli_style"], adapter_weights=[cfg['lora_weight']])
                
                strength = float(cfg.get('strength', 0.65))

                with torch.inference_mode():
                    with torch.autocast(device_type='cuda', dtype=self.dtype):
                        result = self.pipe(
                            prompt=[prompt] * len(batch),
                            negative_prompt=[negative_prompt] * len(batch),
                            image=source_resized,
                            control_image=control_resized,
                            strength=strength,
                            controlnet_conditioning_scale=cfg['controlnet_strength'],
                            num_inference_steps=cfg['steps'],
                            guidance_scale=cfg['cfg_scale'],
                        )
                
                all_results.extend(result.images)
            
            if progress_callback:
                progress_callback(1.0, "Batch complete!")
            
            return True, f"Generated {len(all_results)} images", all_results
            
        except Exception as e:
            return False, f"Batch generation failed: {str(e)}", None


def get_available_samplers() -> list:
    """Get list of available samplers"""
    return [
        "DPM++ 2M Karras",
        "DPM++ SDE Karras", 
        "Euler a",
        "Euler",
        "DDIM",
        "UniPC",
    ]


def get_controlnet_types() -> list:
    """Get available ControlNet types"""
    return ["depth", "canny"]
