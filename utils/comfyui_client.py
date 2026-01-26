"""
ComfyUI Client
Handles communication with ComfyUI API for image generation
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import uuid
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from PIL import Image
import io
import base64
import shutil


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
        self.last_error: Optional[str] = None
    
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

    def get_object_info(self) -> Optional[Dict[str, Any]]:
        """Return ComfyUI object info (node types and input schemas)."""
        try:
            req = urllib.request.Request(f"{self.base_url}/object_info")
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode())
        except:
            return None

    def workflow_convert(self, workflow_ui: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a UI-format workflow JSON to API prompt format via /workflow/convert."""
        try:
            data = json.dumps(workflow_ui).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/workflow/convert",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            self.last_error = f"HTTP {getattr(e, 'code', 'unknown')} {getattr(e, 'reason', '')}: {body}".strip()
            print(f"Workflow convert error: {self.last_error}")
            return None
        except Exception as e:
            self.last_error = str(e)
            print(f"Workflow convert error: {self.last_error}")
            return None

    def load_workflow_ui_from_path(self, path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _find_first_node_by_class_type(
        self, prompt: Dict[str, Any], class_type: str
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        for node_id, node in prompt.items():
            if isinstance(node, dict) and node.get("class_type") == class_type:
                return str(node_id), node
        return None

    def _find_first_input_key(self, prompt: Dict[str, Any], class_type: str, input_key: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        for node_id, node in prompt.items():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") != class_type:
                continue
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and input_key in inputs:
                return str(node_id), node
        return None

    def extract_i2i_gibly_defaults(self, prompt: Dict[str, Any]) -> Dict[str, Any]:
        """Extract default slider values from the converted API prompt."""
        defaults: Dict[str, Any] = {
            "strength_model": 0.9,
            "strength_clip": 1.0,
            "guidance": 2.7,
            "steps": 28,
            "cfg": 1.0,
        }

        lora = self._find_first_node_by_class_type(prompt, "LoraLoader")
        if lora:
            _, node = lora
            inputs = node.get("inputs", {})
            if isinstance(inputs, dict):
                if "strength_model" in inputs:
                    defaults["strength_model"] = float(inputs["strength_model"])
                if "strength_clip" in inputs:
                    defaults["strength_clip"] = float(inputs["strength_clip"])

        guidance = self._find_first_input_key(prompt, "FluxGuidance", "guidance")
        if guidance:
            _, node = guidance
            defaults["guidance"] = float(node["inputs"].get("guidance", defaults["guidance"]))

        sampler = self._find_first_input_key(prompt, "KSampler", "steps")
        if sampler:
            _, node = sampler
            defaults["steps"] = int(node["inputs"].get("steps", defaults["steps"]))
            try:
                if "cfg" in node.get("inputs", {}):
                    defaults["cfg"] = float(node["inputs"].get("cfg", defaults["cfg"]))
            except Exception:
                pass

        return defaults

    def extract_i2i_gibly_prompt_text(self, prompt: Dict[str, Any]) -> Optional[str]:
        node = self._find_first_input_key(prompt, "CLIPTextEncode", "text")
        if not node:
            return None
        _, n = node
        try:
            return str(n.get("inputs", {}).get("text"))
        except Exception:
            return None

    def _patch_i2i_gibly_prompt(
        self,
        prompt: Dict[str, Any],
        *,
        image1_name: str,
        image2_name: str,
        text: Optional[str],
        seed: int,
        strength_model: float,
        strength_clip: float,
        guidance: float,
        cfg: float,
        steps: int,
        filename_prefix: str,
    ) -> None:
        # LoadImage nodes (two images)
        load_nodes = [
            (nid, n)
            for nid, n in prompt.items()
            if isinstance(n, dict) and n.get("class_type") == "LoadImage"
        ]
        if len(load_nodes) >= 1:
            load_nodes[0][1].setdefault("inputs", {})["image"] = image1_name
        if len(load_nodes) >= 2:
            load_nodes[1][1].setdefault("inputs", {})["image"] = image2_name

        # Text (optional override)
        if text is not None and str(text).strip() != "":
            text_node = self._find_first_input_key(prompt, "CLIPTextEncode", "text")
            if text_node:
                _, node = text_node
                node.setdefault("inputs", {})["text"] = str(text)

        # LoRA strengths
        lora_node = self._find_first_node_by_class_type(prompt, "LoraLoader")
        if lora_node:
            _, node = lora_node
            node.setdefault("inputs", {})["strength_model"] = float(strength_model)
            node.setdefault("inputs", {})["strength_clip"] = float(strength_clip)

        # Guidance
        guidance_node = self._find_first_input_key(prompt, "FluxGuidance", "guidance")
        if guidance_node:
            _, node = guidance_node
            node.setdefault("inputs", {})["guidance"] = float(guidance)

        # Steps + seed
        sampler_node = self._find_first_node_by_class_type(prompt, "KSampler")
        if sampler_node:
            _, node = sampler_node
            node.setdefault("inputs", {})["steps"] = int(steps)
            node.setdefault("inputs", {})["seed"] = int(seed)
            try:
                if "cfg" in node.get("inputs", {}):
                    node["inputs"]["cfg"] = float(cfg)
            except Exception:
                pass

        # SaveImage filename
        save_node = self._find_first_input_key(prompt, "SaveImage", "filename_prefix")
        if save_node:
            _, node = save_node
            node.setdefault("inputs", {})["filename_prefix"] = filename_prefix

    def generate_i2i_gibly(
        self,
        *,
        image1: Image.Image,
        image2: Image.Image,
        workflow_ui_path: Path,
        text: Optional[str],
        strength_model: float,
        strength_clip: float,
        guidance: float,
        cfg: float,
        steps: int,
        seeds: List[int],
        filename_prefix_base: str = "ganimation_i2i_gibly",
        progress_callback=None,
    ) -> Tuple[bool, str, Optional[List[Image.Image]]]:
        if not self.is_available():
            return False, "ComfyUI server not running.", None

        if progress_callback:
            progress_callback(0.05, "Loading workflow...")

        workflow_ui = self.load_workflow_ui_from_path(workflow_ui_path)

        try:
            nodes = workflow_ui.get("nodes") if isinstance(workflow_ui, dict) else None
        except Exception:
            nodes = None
        if not nodes:
            return False, f"Workflow JSON appears empty (no nodes): {workflow_ui_path}", None

        if progress_callback:
            progress_callback(0.10, "Converting workflow (UI -> API)...")

        prompt_template = self.workflow_convert(workflow_ui)
        if not prompt_template:
            details = self.last_error
            return False, f"Failed to convert workflow via /workflow/convert: {details or ''}".strip(), None

        load_image_nodes = [
            (nid, n)
            for nid, n in prompt_template.items()
            if isinstance(n, dict) and n.get("class_type") == "LoadImage"
        ]
        if not load_image_nodes:
            return False, "Converted workflow has no LoadImage nodes to receive input image(s)", None

        if progress_callback:
            progress_callback(0.15, "Uploading images...")

        image1_name = self.upload_image(image1, f"i2i_gibly_1_{uuid.uuid4().hex[:8]}.png")
        if not image1_name:
            return False, "Failed to upload image1 to ComfyUI", None

        if len(load_image_nodes) >= 2:
            image2_name = self.upload_image(image2, f"i2i_gibly_2_{uuid.uuid4().hex[:8]}.png")
            if not image2_name:
                return False, "Failed to upload image2 to ComfyUI", None
        else:
            image2_name = image1_name

        results: List[Image.Image] = []
        total = max(1, len(seeds))
        for i, seed in enumerate(seeds):
            if progress_callback:
                progress_callback(0.20 + 0.60 * (i / total), f"Queuing variant {i+1}/{total} (seed {seed})...")

            prompt = json.loads(json.dumps(prompt_template))
            filename_prefix = f"{filename_prefix_base}_{i+1:02d}"
            self._patch_i2i_gibly_prompt(
                prompt,
                image1_name=image1_name,
                image2_name=image2_name,
                text=text,
                seed=int(seed),
                strength_model=float(strength_model),
                strength_clip=float(strength_clip),
                guidance=float(guidance),
                cfg=float(cfg),
                steps=int(steps),
                filename_prefix=filename_prefix,
            )

            prompt_id = self.queue_prompt(prompt)
            if not prompt_id:
                details = self.last_error
                return False, f"Failed to queue workflow: {details or ''}".strip(), None

            ok, images = self.wait_for_completion(prompt_id, timeout=600)
            if not ok or not images:
                return False, "Generation failed or timed out", None

            for img_info in images:
                image_bytes = self.get_image(
                    img_info["filename"],
                    img_info.get("subfolder", ""),
                    img_info.get("type", "output"),
                )
                if not image_bytes:
                    continue
                results.append(Image.open(io.BytesIO(image_bytes)))

        if not results:
            return False, "Failed to retrieve generated image(s)", None

        if progress_callback:
            progress_callback(1.0, "Complete!")

        return True, "Generation successful", results

    def supports_pulid(self) -> bool:
        """Check if PuLID custom nodes appear to be installed on the ComfyUI server."""
        info = self.get_object_info()
        if not info:
            return False
        required = {
            "PulidModelLoader",
            "PulidInsightFaceLoader",
            "PulidEvaClipLoader",
            "ApplyPulid",
        }
        return required.issubset(set(info.keys()))

    def supports_controlnet_preprocessors(self) -> bool:
        """Check if common ControlNet preprocessor nodes appear to be installed."""
        info = self.get_object_info()
        if not info:
            return False
        required = {
            "MiDaS-DepthMapPreprocessor",
            "CannyEdgePreprocessor",
        }
        return required.issubset(set(info.keys()))
    
    def queue_prompt(self, workflow: Dict) -> Optional[str]:
        """Queue a workflow for execution"""
        try:
            self.last_error = None
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
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode('utf-8', errors='replace')
            except Exception:
                body = ""
            self.last_error = f"HTTP {getattr(e, 'code', 'unknown')} {getattr(e, 'reason', '')}: {body}".strip()
            print(f"Queue prompt error: {self.last_error}")
            return None
        except urllib.error.URLError as e:
            self.last_error = f"URL error: {e}"
            print(f"Queue prompt error: {self.last_error}")
            return None
        except Exception as e:
            self.last_error = str(e)
            print(f"Queue prompt error: {self.last_error}")
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

    def get_file(self, filename: str, subfolder: str = "", folder_type: str = "output") -> Optional[bytes]:
        """Download any output file (e.g., mp4) from ComfyUI via /view."""
        try:
            params = urllib.parse.urlencode({
                "filename": filename,
                "subfolder": subfolder,
                "type": folder_type,
            })
            req = urllib.request.Request(f"{self.base_url}/view?{params}")
            with urllib.request.urlopen(req, timeout=300) as response:
                return response.read()
        except:
            return None

    def wait_for_completion_outputs(
        self,
        prompt_id: str,
        timeout: int = 900,
        poll_interval: float = 1.0,
    ) -> Tuple[bool, Dict[str, List[Dict[str, Any]]]]:
        """Wait for workflow to complete and return collected outputs.

        Returns:
            (success, {"images": [...], "videos": [...]})
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            history = self.get_history(prompt_id)
            if history and prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})

                images: List[Dict[str, Any]] = []
                videos: List[Dict[str, Any]] = []
                for _, node_output in outputs.items():
                    if not isinstance(node_output, dict):
                        continue
                    if "images" in node_output:
                        for img_info in node_output["images"]:
                            images.append(img_info)
                    if "videos" in node_output:
                        for vid_info in node_output["videos"]:
                            videos.append(vid_info)

                if images or videos:
                    return True, {"images": images, "videos": videos}

                status = history[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    return False, {"images": [], "videos": []}

            time.sleep(poll_interval)

        return False, {"images": [], "videos": []}

    def stage_input_video(
        self,
        source_video_path: Path,
        *,
        comfyui_input_dir: Path,
        target_name: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Copy a local video file into the ComfyUI input directory.

        ComfyUI's VHS LoadVideo node expects a filename available inside its input folder.

        Returns:
            (success, message, staged_filename)
        """
        try:
            source_video_path = Path(source_video_path)
            if not source_video_path.exists():
                return False, f"Video not found: {source_video_path}", None

            comfyui_input_dir = Path(comfyui_input_dir)
            comfyui_input_dir.mkdir(parents=True, exist_ok=True)

            name = target_name or source_video_path.name
            dest = comfyui_input_dir / name
            if not dest.exists():
                shutil.copy2(str(source_video_path), str(dest))
            return True, "Staged", dest.name
        except Exception as e:
            return False, f"Failed to stage video: {e}", None

    def _patch_animate_mix_prompt(
        self,
        prompt: Dict[str, Any],
        *,
        video_filename: str,
        reference_image_name: str,
        seed: int,
        steps: int,
        cfg: float,
        segment_length: int,
        overlap_frames: int,
        mask_dilate: int,
        points_positive: List[Dict[str, int]],
        points_negative: List[Dict[str, int]],
        filename_prefix: str,
        relight_strength: Optional[float],
    ) -> None:
        # Video file
        load_video = prompt.get("145")
        if isinstance(load_video, dict) and load_video.get("class_type") == "LoadVideo":
            load_video.setdefault("inputs", {})["file"] = video_filename

        # Reference image
        load_img = prompt.get("10")
        if isinstance(load_img, dict) and load_img.get("class_type") == "LoadImage":
            load_img.setdefault("inputs", {})["image"] = reference_image_name

        # Steps/cfg/seed for both samplers
        for nid in ("232:63", "242:91"):
            node = prompt.get(nid)
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                node.setdefault("inputs", {})["steps"] = int(steps)
                node.setdefault("inputs", {})["cfg"] = float(cfg)
                node.setdefault("inputs", {})["seed"] = int(seed)

        # Segment length and overlap/conditioning frames
        for nid in ("232:62", "242:90"):
            node = prompt.get(nid)
            if isinstance(node, dict) and node.get("class_type") == "WanAnimateToVideo":
                node.setdefault("inputs", {})["length"] = int(segment_length)
                node.setdefault("inputs", {})["continue_motion_max_frames"] = int(overlap_frames)

        # Mask dilate
        grow = prompt.get("274")
        if isinstance(grow, dict) and grow.get("class_type") == "GrowMask":
            grow.setdefault("inputs", {})["expand"] = int(mask_dilate)

        # Points
        points = prompt.get("229")
        if isinstance(points, dict) and points.get("class_type") == "PointsEditor":
            pos = [{"x": int(p["x"]), "y": int(p["y"])} for p in points_positive]
            neg = [{"x": int(p["x"]), "y": int(p["y"])} for p in points_negative]
            points.setdefault("inputs", {})["points_store"] = json.dumps({"positive": pos, "negative": neg}, separators=(",", ":"))
            points["inputs"]["coordinates"] = json.dumps(pos, separators=(",", ":"))
            points["inputs"]["neg_coordinates"] = json.dumps(neg, separators=(",", ":"))

        # SaveVideo prefix
        for nid in ("19", "243"):
            node = prompt.get(nid)
            if isinstance(node, dict) and node.get("class_type") == "SaveVideo":
                node.setdefault("inputs", {})["filename_prefix"] = filename_prefix

        # Optional relight LoRA strength
        relight = prompt.get("99")
        if isinstance(relight, dict) and relight.get("class_type") == "LoraLoaderModelOnly":
            relight.setdefault("inputs", {})["strength_model"] = float(relight_strength) if relight_strength is not None else 0.0

    def generate_animate_mix(
        self,
        *,
        reference_image: Image.Image,
        reference_video_path: Path,
        comfyui_input_dir: Path,
        workflow_ui_path: Path,
        steps: int,
        cfg: float,
        segment_length: int,
        overlap_frames: int,
        mask_dilate: int,
        points_positive: List[Dict[str, int]],
        points_negative: List[Dict[str, int]],
        seeds: List[int],
        filename_prefix_base: str = "ganimation_animate_mix",
        relight_strength: Optional[float] = None,
        progress_callback=None,
    ) -> Tuple[bool, str, Optional[List[Tuple[str, bytes]]]]:
        if not self.is_available():
            return False, "ComfyUI server not running.", None

        if progress_callback:
            progress_callback(0.05, "Loading workflow...")

        workflow_ui = self.load_workflow_ui_from_path(workflow_ui_path)

        if progress_callback:
            progress_callback(0.10, "Converting workflow (UI -> API)...")

        prompt_template = self.workflow_convert(workflow_ui)
        if not prompt_template:
            details = self.last_error
            return False, f"Failed to convert workflow via /workflow/convert: {details or ''}".strip(), None

        if progress_callback:
            progress_callback(0.15, "Staging video into ComfyUI input...")

        ok, msg, staged_video_name = self.stage_input_video(
            Path(reference_video_path),
            comfyui_input_dir=Path(comfyui_input_dir),
        )
        if not ok or not staged_video_name:
            return False, msg, None

        if progress_callback:
            progress_callback(0.20, "Uploading reference image...")

        ref_img_name = self.upload_image(reference_image, f"animate_mix_ref_{uuid.uuid4().hex[:8]}.png")
        if not ref_img_name:
            return False, "Failed to upload reference image to ComfyUI", None

        results: List[Tuple[str, bytes]] = []
        total = max(1, len(seeds))
        for i, seed in enumerate(seeds):
            if progress_callback:
                progress_callback(0.25 + 0.60 * (i / total), f"Queuing variant {i+1}/{total} (seed {seed})...")

            prompt = json.loads(json.dumps(prompt_template))
            filename_prefix = f"{filename_prefix_base}_{i+1:02d}_{int(time.time())}"
            self._patch_animate_mix_prompt(
                prompt,
                video_filename=staged_video_name,
                reference_image_name=ref_img_name,
                seed=int(seed),
                steps=int(steps),
                cfg=float(cfg),
                segment_length=int(segment_length),
                overlap_frames=int(overlap_frames),
                mask_dilate=int(mask_dilate),
                points_positive=points_positive,
                points_negative=points_negative,
                filename_prefix=filename_prefix,
                relight_strength=relight_strength,
            )

            prompt_id = self.queue_prompt(prompt)
            if not prompt_id:
                details = self.last_error
                return False, f"Failed to queue workflow: {details or ''}".strip(), None

            ok, outs = self.wait_for_completion_outputs(prompt_id, timeout=1800)
            if not ok:
                return False, "Generation failed or timed out", None

            videos = outs.get("videos", [])
            if not videos:
                return False, "No video outputs returned by workflow", None

            # Take first returned video
            vid = videos[0]
            file_bytes = self.get_file(
                vid.get("filename"),
                vid.get("subfolder", ""),
                vid.get("type", "output"),
            )
            if not file_bytes:
                return False, "Failed to download generated video", None

            results.append((filename_prefix, file_bytes))

        if progress_callback:
            progress_callback(1.0, "Complete!")

        return True, "Generation successful", results
    
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
    ) -> Tuple[bool, str, Optional[List[Image.Image]]]:
        """
        Generate Ghibli-style image using ComfyUI workflow
        """
        if not self.is_available():
            return False, "ComfyUI server not running. Start with: python main.py --listen", None

        controlnet_depth_enabled = bool(settings.get('controlnet_depth_enabled', True))
        controlnet_canny_enabled = bool(settings.get('controlnet_canny_enabled', True))
        if (controlnet_depth_enabled or controlnet_canny_enabled) and not self.supports_controlnet_preprocessors():
            return False, "ControlNet preprocessors not found in ComfyUI. Install comfyui_controlnet_aux (Fannovel16) in ComfyUI/custom_nodes and restart ComfyUI.", None
        
        if progress_callback:
            progress_callback(0.1, "Uploading image to ComfyUI...")
        
        # Upload source image
        input_name = self.upload_image(source_image, f"ganimation_{uuid.uuid4().hex[:8]}.png")
        if not input_name:
            return False, "Failed to upload image to ComfyUI", None

        pulid_enabled = bool(settings.get('pulid_enabled', False))
        if pulid_enabled:
            if not self.supports_pulid():
                return False, "PuLID is enabled in UI but PuLID nodes were not found in ComfyUI. Install PuLID_ComfyUI (cubiq) and restart ComfyUI.", None

            id_image = settings.get('pulid_id_image')
            if id_image is None:
                id_image = source_image

            if progress_callback:
                progress_callback(0.15, "Uploading PuLID identity image...")

            pulid_input_name = self.upload_image(id_image, f"ganimation_pulid_{uuid.uuid4().hex[:8]}.png")
            if not pulid_input_name:
                return False, "Failed to upload PuLID identity image to ComfyUI", None

            settings['pulid_input_name'] = pulid_input_name
        
        if progress_callback:
            progress_callback(0.2, "Building workflow...")
        
        # Build workflow
        workflow = self._build_ghibli_workflow(input_name, settings)
        
        if progress_callback:
            progress_callback(0.3, "Queuing generation...")
        
        # Queue workflow
        prompt_id = self.queue_prompt(workflow)
        if not prompt_id:
            details = self.last_error
            if details:
                return False, f"Failed to queue workflow: {details}", None
            return False, "Failed to queue workflow", None
        
        if progress_callback:
            progress_callback(0.4, "Generating image...")
        
        # Wait for completion
        success, images = self.wait_for_completion(prompt_id, timeout=300)
        
        if not success or not images:
            return False, "Generation failed or timed out", None
        
        if progress_callback:
            progress_callback(0.9, "Retrieving result...")
        
        results: List[Image.Image] = []
        for img_info in images:
            image_bytes = self.get_image(
                img_info['filename'],
                img_info.get('subfolder', ''),
                img_info.get('type', 'output')
            )
            if not image_bytes:
                continue
            results.append(Image.open(io.BytesIO(image_bytes)))

        if not results:
            return False, "Failed to retrieve generated image(s)", None
        
        if progress_callback:
            progress_callback(1.0, "Complete!")
        
        return True, "Generation successful", results
    
    def _build_ghibli_workflow(self, input_image: str, settings: Dict[str, Any]) -> Dict:
        """
        Build ComfyUI workflow for Ghibli-style generation
        SDXL + ControlNet (Depth) + LoRA Ghibli
        """
        # Extract settings
        # NOTE:
        # Your previous workflow was basically *text-to-image*:
        #   - it used EmptyLatentImage (1024x1024)
        #   - and KSampler denoise=1.0
        # This means the input frame was not used as an init image at all (only a
        # depth-map hint), so the model "invents" the whole image -> huge drift + often ugly.
        #
        # For frame stylization you want an *img2img* workflow:
        #   LoadImage -> VAEEncode -> KSampler (denoise ~0.5-0.75)
        # while optionally keeping ControlNet for structure.

        lora_weight = settings.get('lora_weight', 0.75)
        cfg_scale = settings.get('cfg_scale', 5.0)
        steps = settings.get('steps', 30)
        controlnet_depth_enabled = bool(settings.get('controlnet_depth_enabled', True))
        controlnet_canny_enabled = bool(settings.get('controlnet_canny_enabled', True))

        controlnet_depth_strength = float(settings.get('controlnet_depth_strength', 0.6))
        controlnet_depth_start = float(settings.get('controlnet_depth_start', 0.0))
        controlnet_depth_end = float(settings.get('controlnet_depth_end', 1.0))

        controlnet_canny_strength = float(settings.get('controlnet_canny_strength', 0.35))
        controlnet_canny_start = float(settings.get('controlnet_canny_start', 0.0))
        controlnet_canny_end = float(settings.get('controlnet_canny_end', 1.0))

        canny_low_threshold = int(settings.get('canny_low_threshold', 100))
        canny_high_threshold = int(settings.get('canny_high_threshold', 200))
        denoise = settings.get('denoise', 0.65)  # img2img strength (lower = more faithful to the frame)
        width = int(settings.get('width', 1024))
        height = int(settings.get('height', 1024))
        depth_resolution = int(settings.get('depth_resolution', max(width, height)))
        lora_name = settings.get(
            'lora_name',
            'StudioGhibli.Redmond-StdGBRRedmAF-StudioGhibli.safetensors'
        )
        pulid_enabled = bool(settings.get('pulid_enabled', False))
        pulid_input_name = settings.get('pulid_input_name')
        pulid_file = settings.get('pulid_file', 'pulid_v1.1.safetensors')
        pulid_method = settings.get('pulid_method', 'fidelity')
        pulid_weight = float(settings.get('pulid_weight', 0.8))
        pulid_start = float(settings.get('pulid_start', 0.0))
        pulid_end = float(settings.get('pulid_end', 1.0))
        pulid_provider = settings.get('pulid_provider', 'CUDA')
        prompt = settings.get(
            'prompt',
            "StdGBRedmAF, Studio Ghibli, anime illustration, masterpiece, high quality, detailed, beautiful lighting, soft colors, whimsical, hand-drawn aesthetic",
        )
        negative_prompt = settings.get(
            'negative_prompt',
            "low quality, bad anatomy, worst quality, low resolution, blurry, distorted, ugly, duplicate, watermark, signature, jpeg artifacts, photorealistic, 3d render",
        )
        seed = settings.get('seed', -1)
        num_variations = int(settings.get('num_variations', 1))
        seeds = settings.get('seeds')

        if seeds is None:
            if seed == -1:
                import random
                seed = random.randint(0, 2**32 - 1)
            seeds = [int(seed) + i for i in range(num_variations)]
        else:
            seeds = [int(s) for s in seeds]
            num_variations = len(seeds)

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
                    "lora_name": lora_name,
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
            # Positive prompt
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": prompt,
                    "clip": ["2", 1]
                }
            },
            # Positive with refiner
            "8": {
                "class_type": "CLIPTextEncodeSDXL",
                "inputs": {
                    "text_g": prompt,
                    "text_l": "ghibli style, anime, illustration, detailed",
                    "clip": ["2", 1],
                    "width": width,
                    "height": height,
                    "crop_w": 0,
                    "crop_h": 0,
                    "target_width": width,
                    "target_height": height
                }
            },
            # Negative prompt
            "9": {
                "class_type": "CLIPTextEncodeSDXL",
                "inputs": {
                    "text_g": negative_prompt,
                    "text_l": "low quality, blurry, ugly",
                    "clip": ["2", 1],
                    "width": width,
                    "height": height,
                    "crop_w": 0,
                    "crop_h": 0,
                    "target_width": width,
                    "target_height": height
                }
            },
            # Encode the input frame into the latent space (img2img)
            "10": {
                "class_type": "VAEEncode",
                "inputs": {
                    "pixels": ["3", 0],
                    "vae": ["1", 2]
                }
            },
        }

        current_positive = ["8", 0]
        current_negative = ["9", 0]

        if controlnet_depth_enabled:
            workflow["4"] = {
                "class_type": "MiDaS-DepthMapPreprocessor",
                "inputs": {
                    "image": ["3", 0],
                    "a": 6.283185307179586,
                    "bg_threshold": 0.1,
                    "resolution": depth_resolution,
                },
            }
            workflow["5"] = {
                "class_type": "ControlNetLoader",
                "inputs": {
                    "control_net_name": "diffusers_xl_depth_full.safetensors"
                }
            }
            workflow["6"] = {
                "class_type": "ControlNetApplyAdvanced",
                "inputs": {
                    "positive": current_positive,
                    "negative": current_negative,
                    "control_net": ["5", 0],
                    "image": ["4", 0],
                    "strength": controlnet_depth_strength,
                    "start_percent": controlnet_depth_start,
                    "end_percent": controlnet_depth_end,
                }
            }
            current_positive = ["6", 0]
            current_negative = ["6", 1]

        if controlnet_canny_enabled:
            workflow["20"] = {
                "class_type": "CannyEdgePreprocessor",
                "inputs": {
                    "image": ["3", 0],
                    "low_threshold": canny_low_threshold,
                    "high_threshold": canny_high_threshold,
                    "resolution": depth_resolution,
                },
            }
            workflow["21"] = {
                "class_type": "ControlNetLoader",
                "inputs": {
                    "control_net_name": "diffusers_xl_canny_full.safetensors"
                }
            }
            workflow["22"] = {
                "class_type": "ControlNetApplyAdvanced",
                "inputs": {
                    "positive": current_positive,
                    "negative": current_negative,
                    "control_net": ["21", 0],
                    "image": ["20", 0],
                    "strength": controlnet_canny_strength,
                    "start_percent": controlnet_canny_start,
                    "end_percent": controlnet_canny_end,
                }
            }
            current_positive = ["22", 0]
            current_negative = ["22", 1]

        if pulid_enabled:
            if not pulid_input_name:
                raise ValueError("PuLID is enabled but pulid_input_name is missing. It should be set by generate_ghibli_image().")

            workflow["14"] = {
                "class_type": "LoadImage",
                "inputs": {
                    "image": pulid_input_name
                }
            }

            workflow["15"] = {
                "class_type": "PulidModelLoader",
                "inputs": {
                    "pulid_file": pulid_file
                }
            }

            workflow["16"] = {
                "class_type": "PulidInsightFaceLoader",
                "inputs": {
                    "provider": pulid_provider
                }
            }

            workflow["17"] = {
                "class_type": "PulidEvaClipLoader",
                "inputs": {}
            }

            workflow["18"] = {
                "class_type": "ApplyPulid",
                "inputs": {
                    "model": ["2", 0],
                    "pulid": ["15", 0],
                    "eva_clip": ["17", 0],
                    "face_analysis": ["16", 0],
                    "image": ["14", 0],
                    "method": pulid_method,
                    "weight": pulid_weight,
                    "start_at": pulid_start,
                    "end_at": pulid_end,
                }
            }

            model_for_sampling = ["18", 0]
        else:
            model_for_sampling = ["2", 0]

        for i, seed_i in enumerate(seeds):
            k_id = str(100 + i * 3)
            d_id = str(101 + i * 3)
            s_id = str(102 + i * 3)
            workflow[k_id] = {
                "class_type": "KSampler",
                "inputs": {
                    "model": model_for_sampling,
                    "positive": current_positive,
                    "negative": current_negative,
                    "latent_image": ["10", 0],
                    "seed": int(seed_i),
                    "steps": steps,
                    "cfg": cfg_scale,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                    "denoise": denoise,
                }
            }
            workflow[d_id] = {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": [k_id, 0],
                    "vae": ["1", 2]
                }
            }
            workflow[s_id] = {
                "class_type": "SaveImage",
                "inputs": {
                    "images": [d_id, 0],
                    "filename_prefix": "ganimation_ghibli"
                }
            }
        
        return workflow


def get_comfyui_client(host: str = "127.0.0.1", port: int = 8188) -> ComfyUIClient:
    """Get ComfyUI client instance"""
    return ComfyUIClient(host, port)

