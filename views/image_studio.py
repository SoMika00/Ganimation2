'''
Image Studio Page
Generate Ghibli-style frames using ComfyUI (SDXL + ControlNet + LoRA)
'''

import streamlit as st
from pathlib import Path
from PIL import Image
import time
import io
import random
import os
import requests

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.video_processor import VideoProcessor
from utils.comfyui_client import ComfyUIClient

API_BASE = os.getenv("API_URL", "http://localhost:8000/api/v1")


def fetch_tasks():
    try:
        resp = requests.get(f"{API_BASE}/generation/tasks", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def cancel_task_api(task_id: str):
    try:
        resp = requests.delete(f"{API_BASE}/generation/tasks/{task_id}", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def render():
    """Render the Image Studio page"""
    
    st.markdown("""
    <h1 class="main-title">🎨 Image Studio</h1>
    <p class="subtitle">Transform video frames into Ghibli-style artwork</p>
    """, unsafe_allow_html=True)
    
    # Initialize paths
    gallery_root = Path(__file__).parent.parent / "gallery"
    source_media = gallery_root / "source_media"
    generated_images = gallery_root / "generated_images"
    temp_dir = Path(__file__).parent.parent / "temp"
    
    # Ensure directories exist
    generated_images.mkdir(parents=True, exist_ok=True)
    
    # Initialize processors
    video_processor = VideoProcessor(temp_dir, source_media)
    comfyui_host = os.getenv("COMFYUI_HOST", "127.0.0.1")
    comfyui_port = int(os.getenv("COMFYUI_PORT", "8188"))
    comfyui = ComfyUIClient(host=comfyui_host, port=comfyui_port)
    
    # Check ComfyUI status
    comfyui_available = comfyui.is_available()
    pulid_available = False
    if comfyui_available:
        try:
            pulid_available = comfyui.supports_pulid()
        except Exception:
            pulid_available = False
    
    # System status
    with st.expander("🔧 System Status", expanded=not comfyui_available):
        col1, col2 = st.columns(2)
        
        with col1:
            if comfyui_available:
                st.success("✅ **ComfyUI** Connected")
                stats = comfyui.get_system_stats()
                if stats:
                    devices = stats.get('devices', [])
                    for i, device in enumerate(devices):
                        name = device.get('name', 'Unknown')
                        vram_total = device.get('vram_total', 0) / (1024**3)
                        vram_free = device.get('vram_free', 0) / (1024**3)
                        st.caption(f"GPU {i}: {name} ({vram_free:.1f}/{vram_total:.1f} GB free)")
            else:
                st.error("❌ **ComfyUI** Not running")
        
        with col2:
            pipeline_msg = "**Pipeline:** SDXL + ControlNet + LoRA Ghibli"
            if pulid_available:
                pipeline_msg += " + PuLID"
            st.markdown(pipeline_msg)
            if comfyui_available and not pulid_available:
                st.caption("PuLID nodes not detected in ComfyUI (install PuLID_ComfyUI to enable identity preservation).")
        
        if not comfyui_available:
            st.warning("""
            ⚠️ **ComfyUI n'est pas lancé !**
            
            Pour utiliser Image Studio, lance ComfyUI dans un autre terminal :
            
            ```bash
            cd /home/mika/ComfyUI
            python main.py --listen --port 8188
            ```
            
            Si c'est la première fois, télécharge d'abord les modèles :
            ```bash
            cd /home/mika/Ganimation2
            ./scripts/download_models.sh
            ```
            """)
    
    st.markdown("---")
    
    # Tasks overview section
    st.markdown("### 📋 Generation Tasks")
    tasks = fetch_tasks()
    if tasks:
        for task in tasks:
            cols = st.columns([3, 2, 2, 2, 1])
            cols[0].write(f"{task.get('type', '?')} | {task.get('status', '?')}")
            cols[1].write(f"Progress: {task.get('progress', 0):.0%}")
            cols[2].write(task.get('created_at', ''))
            if task.get('status') in ('pending', 'processing'):
                if cols[3].button("Cancel", key=f"cancel_{task['task_id']}"):
                    if cancel_task_api(task['task_id']):
                        st.success("Task cancelled")
                        st.rerun()
                    else:
                        st.error("Failed to cancel")
            else:
                cols[3].write(task.get('message', ''))
            cols[4].write(task.get('task_id', '')[:8])
    else:
        st.caption("No active tasks.")
    
    # Automatic polling: 4s interval while any task pending/processing
    if tasks:
        has_active = any(t.get('status') in ('pending', 'processing') for t in tasks)
        if has_active:
            time.sleep(4)
            st.rerun()
    
    st.markdown("---")
    
    # Main layout
    col_source, col_settings = st.columns([2, 1])
    
    # ===== Source Video & Frame Selection =====
    with col_source:
        st.markdown("### 📹 Select Source")
        
        # Get available videos
        videos = sorted(source_media.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not videos:
            st.warning("📭 No source videos available. Go to **Ingestion** first!")
            return
        
        # Video selector
        video_options = {v.stem: str(v) for v in videos}
        
        # Check if video was pre-selected
        default_idx = 0
        if 'selected_video' in st.session_state and st.session_state.selected_video:
            selected_path = Path(st.session_state.selected_video)
            if selected_path.stem in video_options:
                default_idx = list(video_options.keys()).index(selected_path.stem)
        
        selected_video_name = st.selectbox(
            "Choose video",
            options=list(video_options.keys()),
            index=default_idx,
            key="video_selector"
        )
        
        selected_video_path = Path(video_options[selected_video_name])

        if st.session_state.get('current_video_name') != selected_video_name:
            st.session_state.current_video_name = selected_video_name
            st.session_state.extracted_frames = None
            st.session_state.frames_video = None
            st.session_state.selected_frame = None
            st.session_state.selected_frame_idx = 0
        
        # Show video preview
        col_vid, col_info = st.columns([2, 1])
        with col_vid:
            st.video(str(selected_video_path))
        with col_info:
            info = video_processor.get_video_info(selected_video_path)
            if info:
                st.markdown(f"""
                **📍 Resolution:** {info.get('width', '?')}×{info.get('height', '?')}  
                **🎬 Duration:** {info.get('duration', 0):.1f}s  
                **⚡ FPS:** {info.get('fps', '?'):.0f}  
                """)
        
        st.markdown("---")
        
        # Frame extraction
        st.markdown("### 🖌️ Select Frame")
        
        num_frames = st.slider(
            "Number of frames to extract",
            min_value=4,
            max_value=20,
            value=8,
            step=2,
            key="num_frames"
        )
        
        if st.button("🔄 Extract Frames", key="extract_btn"):
            with st.spinner("Extracting frames..."):
                frames = video_processor.extract_frames(
                    selected_video_path,
                    num_frames=num_frames
                )
                st.session_state.extracted_frames = frames
                st.session_state.frames_video = selected_video_name
        
        # Display extracted frames
        if 'extracted_frames' in st.session_state and st.session_state.get('frames_video') == selected_video_name:
            frames = st.session_state.extracted_frames
            
            if frames:
                st.markdown("**Click a frame to select it:**")
                
                cols_per_row = 4
                selected_frame_idx = st.session_state.get('selected_frame_idx', 0)
                
                for i in range(0, len(frames), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for j, col in enumerate(cols):
                        if i + j < len(frames):
                            frame = frames[i + j]
                            with col:
                                if st.button(
                                    f"Frame {i + j + 1}",
                                    key=f"frame_btn_{i + j}",
                                    use_container_width=True,
                                    type="primary" if (i + j) == selected_frame_idx else "secondary"
                                ):
                                    st.session_state.selected_frame_idx = i + j
                                    st.session_state.selected_frame = str(frame)
                                    st.rerun()
                                
                                st.image(str(frame), use_container_width=True)
                
                # Show selected frame large
                selected_frame = st.session_state.get('selected_frame')
                if selected_frame:
                    st.markdown("### 🎯 Selected Frame")
                    st.image(selected_frame, use_container_width=True)
            else:
                st.warning("No frames extracted. Try again.")
        else:
            st.info("👆 Click 'Extract Frames' to see available frames")
    
    # ===== Generation Settings =====
    with col_settings:
        st.markdown("### ⚙️ Generation Settings")
        
        with st.container():
            st.markdown("**🧩 Preset (Full-body reference)**")
            preset_full_body = st.checkbox(
                "Use recommended full-body preset",
                value=True,
                help="Sets a good starting point for full-body reference images (Wan Animate friendly).",
            )

            st.markdown("---")

            # LoRA Settings
            st.markdown("**🎨 Style (LoRA Ghibli)**")
            lora_name = st.selectbox(
                "LoRA File",
                options=[
                    "StudioGhibli.Redmond-StdGBRRedmAF-StudioGhibli.safetensors",
                    "ghibli_style_sdxl.safetensors",
                ],
                index=0,
                help="Le fichier doit exister dans ComfyUI/models/loras"
            )
            lora_weight = st.slider(
                "LoRA Weight",
                min_value=0.0,
                max_value=1.5,
                value=0.70 if preset_full_body else 0.75,
                step=0.05,
                help=(
                    "0.5–0.8 : stylise bien sans casser le visage (reco avec PuLID)\n"
                    "0.9–1.2 : style très fort (risque de changer les traits)\n"
                    ">1.2 : souvent trop agressif (surtout en I2I)\n"
                    "Reco départ (full body + garder traits) : 0.70\n"
                    "Si rendu trop 'coloring book' → baisse LoRA et monte légèrement Canny."
                )
            )
            
            st.markdown("---")

            # PuLID
            st.markdown("**🧑 Identity (PuLID)**")
            pulid_enabled = st.checkbox(
                "Enable PuLID (identity preservation)",
                value=False,
                disabled=not pulid_available,
                key="pulid_enabled",
                help="Requires PuLID_ComfyUI custom nodes installed in ComfyUI",
            )

            pulid_use_frame_as_id = st.checkbox(
                "Use selected frame as ID image",
                value=True,
                disabled=not pulid_enabled,
                key="pulid_use_frame_as_id",
            )

            pulid_id_image = None
            if pulid_enabled and not pulid_use_frame_as_id:
                pulid_upload = st.file_uploader(
                    "Upload ID face image",
                    type=["png", "jpg", "jpeg", "webp"],
