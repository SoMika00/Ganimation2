"""
ComfyUI Client
Handles communication with ComfyUI API for image generation
"""

import json
import urllib.request
import urllib.parse
import uuid
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image
import io
import base64


class ComfyUIClient:
    """
    Client for ComfyUI API
    Handles workflow execution and image retrieval
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8188):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.client_id = str(uuid.uuid4())
    
    def is_available(self) -> bool:
        """Check if ComfyUI server is running"""
        try:
            req = urllib.request.Request(f"{self.base_url}/system_stats")
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False
    
    def get_system_stats(self) -> Optional[Dict]:
        """Get ComfyUI system stats"""
        try:
            req = urllib.request.Request(f"{self.base_url}/system_stats")
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except:
            return None
    
    def queue_prompt(self, workflow: Dict) -> Optional[str]:
        """Queue a workflow for execution"""
        try:
            data = json.dumps({
                "prompt": workflow,
                "client_id": self.client_id
            }).encode('utf-8')
            
            req = urllib.request.Request(
                f"{self.base_url}/prompt",
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                return result.get('prompt_id')
        except Exception as e:
            print(f"Queue prompt error: {e}")
            return None
    
    def get_history(self, prompt_id: str) -> Optional[Dict]:
        """Get execution history for a prompt"""
        try:
            req = urllib.request.Request(f"{self.base_url}/history/{prompt_id}")
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except:
            return None
    
    def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> Optional[bytes]:
        """Get generated image from ComfyUI"""
        try:
            params = urllib.parse.urlencode({
                "filename": filename,
                "subfolder": subfolder,
                "type": folder_type
            })
            req = urllib.request.Request(f"{self.base_url}/view?{params}")
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read()
        except:
            return None
    
    def upload_image(self, image: Image.Image, name: str = "input.png") -> Optional[str]:
        """Upload image to ComfyUI input folder"""
        try:
            # Convert PIL image to bytes
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
            image_bytes = buffer.getvalue()
            
            # Create multipart form data
            boundary = uuid.uuid4().hex
            body = (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
                f'Content-Type: image/png\r\n\r\n'
            ).encode() + image_bytes + f'\r\n--{boundary}--\r\n'.encode()
            
            req = urllib.request.Request(
                f"{self.base_url}/upload/image",
                data=body,
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
            )
            
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode())
                return result.get('name')
        except Exception as e:
            print(f"Upload error: {e}")
            return None
    
    def wait_for_completion(
        self, 
        prompt_id: str, 
        timeout: int = 300,
        poll_interval: float = 1.0
    ) -> Tuple[bool, Optional[List[Dict]]]:
        """
        Wait for workflow to complete and return output images
        
        Returns:
            (success, list of image info dicts)
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            history = self.get_history(prompt_id)
            
            if history and prompt_id in history:
                outputs = history[prompt_id].get('outputs', {})
                
                # Find image outputs
                images = []
                for node_id, node_output in outputs.items():
                    if 'images' in node_output:
                        for img_info in node_output['images']:
                            images.append(img_info)
                
                if images:
                    return True, images
                
                # Check for errors
                status = history[prompt_id].get('status', {})
                if status.get('status_str') == 'error':
                    return False, None
            
            time.sleep(poll_interval)
        
        return False, None
    
    def generate_ghibli_image(
        self,
        source_image: Image.Image,
        settings: Dict[str, Any],
        progress_callback=None
    ) -> Tuple[bool, str, Optional[Image.Image]]:
        """
        Generate Ghibli-style image using ComfyUI workflow
        """
        if not self.is_available():
            return False, "ComfyUI server not running. Start with: python main.py --listen", None
        
        if progress_callback:
            progress_callback(0.1, "Uploading image to ComfyUI...")
        
        # Upload source image
        input_name = self.upload_image(source_image, f"ganimation_{uuid.uuid4().hex[:8]}.png")
        if not input_name:
            return False, "Failed to upload image to ComfyUI", None
        
        if progress_callback:
            progress_callback(0.2, "Building workflow...")
        
        # Build workflow
        workflow = self._build_ghibli_workflow(input_name, settings)
        
        if progress_callback:
            progress_callback(0.3, "Queuing generation...")
        
        # Queue workflow
        prompt_id = self.queue_prompt(workflow)
        if not prompt_id:
            return False, "Failed to queue workflow", None
        
        if progress_callback:
            progress_callback(0.4, "Generating image...")
        
        # Wait for completion
        success, images = self.wait_for_completion(prompt_id, timeout=300)
        
        if not success or not images:
            return False, "Generation failed or timed out", None
        
        if progress_callback:
            progress_callback(0.9, "Retrieving result...")
        
        # Get first output image
        img_info = images[0]
        image_bytes = self.get_image(
            img_info['filename'],
            img_info.get('subfolder', ''),
            img_info.get('type', 'output')
        )
        
        if not image_bytes:
            return False, "Failed to retrieve generated image", None
        
        result_image = Image.open(io.BytesIO(image_bytes))
        
        if progress_callback:
            progress_callback(1.0, "Complete!")
        
        return True, "Generation successful", result_image
    
    def _build_ghibli_workflow(self, input_image: str, settings: Dict[str, Any]) -> Dict:
        """
        Build ComfyUI workflow for Ghibli-style generation
        SDXL + ControlNet (Depth) + LoRA Ghibli
        """
        # Extract settings
        lora_weight = settings.get('lora_weight', 0.75)
        cfg_scale = settings.get('cfg_scale', 5.0)
        steps = settings.get('steps', 30)
        controlnet_strength = settings.get('controlnet_strength', 0.6)
        seed = settings.get('seed', -1)
        
        if seed == -1:
            import random
            seed = random.randint(0, 2**32 - 1)
        
        # ComfyUI workflow nodes
        workflow = {
            # Load SDXL checkpoint
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "sd_xl_base_1.0.safetensors"
                }
            },
            # Load Ghibli LoRA
            "2": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["1", 0],
                    "clip": ["1", 1],
                    "lora_name": "ghibli_style_sdxl.safetensors",
                    "strength_model": lora_weight,
                    "strength_clip": lora_weight
                }
            },
            # Load input image
            "3": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": input_image
                }
            },
            # Depth preprocessor (ControlNet Aux)
            "4": {
                "class_type": "MiDaS-DepthMapPreprocessor",
                "inputs": {
                    "image": ["3", 0],
                    "a": 6.283185307179586,
                    "bg_threshold": 0.1,
                    "resolution": 1024
                }
            },
            # Load ControlNet
            "5": {
                "class_type": "ControlNetLoader",
                "inputs": {
                    "control_net_name": "diffusers_xl_depth_full.safetensors"
                }
            },
            # Apply ControlNet
            "6": {
                "class_type": "ControlNetApplyAdvanced",
                "inputs": {
                    "positive": ["8", 0],
                    "negative": ["9", 0],
                    "control_net": ["5", 0],
                    "image": ["4", 0],
                    "strength": controlnet_strength,
                    "start_percent": 0.0,
                    "end_percent": 1.0
                }
            },
            # Positive prompt
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "Studio Ghibli style, anime illustration, masterpiece, high quality, detailed, beautiful lighting, soft colors, whimsical, hand-drawn aesthetic",
                    "clip": ["2", 1]
                }
            },
            # Positive with refiner
            "8": {
                "class_type": "CLIPTextEncodeSDXL",
                "inputs": {
                    "text_g": "Studio Ghibli style, anime illustration, masterpiece, high quality, detailed, beautiful lighting, soft colors, whimsical, hand-drawn aesthetic",
                    "text_l": "ghibli style, anime, illustration, detailed",
                    "clip": ["2", 1],
                    "width": 1024,
                    "height": 1024,
                    "crop_w": 0,
                    "crop_h": 0,
                    "target_width": 1024,
                    "target_height": 1024
                }
            },
            # Negative prompt
            "9": {
                "class_type": "CLIPTextEncodeSDXL",
                "inputs": {
                    "text_g": "low quality, bad anatomy, worst quality, low resolution, blurry, distorted, ugly, duplicate, watermark, signature, jpeg artifacts, photorealistic, 3d render",
                    "text_l": "low quality, blurry, ugly",
                    "clip": ["2", 1],
                    "width": 1024,
                    "height": 1024,
                    "crop_w": 0,
                    "crop_h": 0,
                    "target_width": 1024,
                    "target_height": 1024
                }
            },
            # Empty latent
            "10": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": 1024,
                    "height": 1024,
                    "batch_size": 1
                }
            },
            # KSampler
            "11": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["2", 0],
                    "positive": ["6", 0],
                    "negative": ["6", 1],
                    "latent_image": ["10", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg_scale,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                    "denoise": 1.0
                }
            },
            # VAE Decode
            "12": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["11", 0],
                    "vae": ["1", 2]
                }
            },
            # Save Image
            "13": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["12", 0],
                    "filename_prefix": "ganimation_ghibli"
                }
            }
        }
        
        return workflow


def get_comfyui_client(host: str = "127.0.0.1", port: int = 8188) -> ComfyUIClient:
    """Get ComfyUI client instance"""
    return ComfyUIClient(host, port)

