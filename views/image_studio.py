"""
Image Studio Page
Generate Ghibli-style frames using ComfyUI (SDXL + ControlNet + LoRA)
"""

import streamlit as st
from pathlib import Path
from PIL import Image
import time
import io

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.video_processor import VideoProcessor
from utils.comfyui_client import ComfyUIClient


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
    comfyui = ComfyUIClient(host="127.0.0.1", port=8188)
    
    # Check ComfyUI status
    comfyui_available = comfyui.is_available()
    
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
            st.markdown("**Pipeline:** SDXL + ControlNet + LoRA Ghibli")
        
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
        
        # Show video preview
        col_vid, col_info = st.columns([2, 1])
        with col_vid:
            st.video(str(selected_video_path))
        with col_info:
            info = video_processor.get_video_info(selected_video_path)
            if info:
                st.markdown(f"""
                **📐 Resolution:** {info.get('width', '?')}×{info.get('height', '?')}  
                **🎬 Duration:** {info.get('duration', 0):.1f}s  
                **⚡ FPS:** {info.get('fps', '?'):.0f}  
                """)
        
        st.markdown("---")
        
        # Frame extraction
        st.markdown("### 🖼️ Select Frame")
        
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
                if 'selected_frame' in st.session_state:
                    st.markdown("### 🎯 Selected Frame")
                    st.image(st.session_state.selected_frame, use_container_width=True)
            else:
                st.warning("No frames extracted. Try again.")
        else:
            st.info("👆 Click 'Extract Frames' to see available frames")
    
    # ===== Generation Settings =====
    with col_settings:
        st.markdown("### ⚙️ Generation Settings")
        
        with st.container():
            # LoRA Settings
            st.markdown("**🎨 Style (LoRA Ghibli)**")
            lora_weight = st.slider(
                "LoRA Weight",
                min_value=0.0,
                max_value=1.5,
                value=0.75,
                step=0.05,
                help="Style strength. Sweet spot: 0.7-0.85"
            )
            
            st.markdown("---")
            
            # Sampling
            st.markdown("**🔧 Sampling**")
            
            steps = st.slider(
                "Steps",
                min_value=15,
                max_value=50,
                value=30,
                step=5
            )
            
            cfg_scale = st.slider(
                "CFG Scale",
                min_value=3.0,
                max_value=12.0,
                value=5.0,
                step=0.5
            )
            
            st.markdown("---")
            
            # ControlNet
            st.markdown("**🎛️ ControlNet (Depth)**")
            
            controlnet_strength = st.slider(
                "Strength",
                min_value=0.0,
                max_value=1.0,
                value=0.6,
                step=0.1
            )
            
            st.markdown("---")
            
            # Seed
            st.markdown("**🎲 Seed**")
            seed_random = st.checkbox("Random seed", value=True)
            if seed_random:
                seed = -1
            else:
                seed = st.number_input("Seed", min_value=0, max_value=2147483647, value=42)
        
        # Generate button
        st.markdown("---")
        
        can_generate = (
            'selected_frame' in st.session_state 
            and st.session_state.selected_frame 
            and comfyui_available
        )
        
        generate_btn = st.button(
            "🚀 Generate Ghibli Frame",
            use_container_width=True,
            disabled=not can_generate,
            type="primary",
            key="generate_btn"
        )
        
        if not comfyui_available:
            st.caption("⚠️ Start ComfyUI first")
        elif 'selected_frame' not in st.session_state:
            st.caption("⬆️ Select a frame first")
    
    # ===== Generation Process =====
    st.markdown("---")
    
    if generate_btn and can_generate:
        st.markdown("### 🎬 Generation")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(progress: float, message: str):
            progress_bar.progress(progress)
            status_text.markdown(f"**{message}**")
        
        # Load source frame
        source_frame = Image.open(st.session_state.selected_frame).convert('RGB')
        
        # Prepare settings
        settings = {
            'lora_weight': lora_weight,
            'cfg_scale': cfg_scale,
            'steps': steps,
            'seed': seed,
            'controlnet_strength': controlnet_strength,
        }
        
        try:
            success, message, result_image = comfyui.generate_ghibli_image(
                source_frame,
                settings=settings,
                progress_callback=update_progress
            )
            
            if success and result_image:
                progress_bar.progress(1.0)
                status_text.empty()
                
                # Store in session for validation
                img_buffer = io.BytesIO()
                result_image.save(img_buffer, format='PNG')
                st.session_state.pending_image = img_buffer.getvalue()
                st.session_state.pending_video_name = selected_video_name
                st.session_state.pending_source_frame = st.session_state.selected_frame
                st.rerun()
            else:
                progress_bar.empty()
                status_text.empty()
                st.error(f"❌ Generation failed: {message}")
                
        except Exception as e:
            progress_bar.empty()
            status_text.empty()
            st.error(f"❌ Error: {str(e)}")
            
            import traceback
            with st.expander("Error Details"):
                st.code(traceback.format_exc())
    
    # ===== Pending Image Validation =====
    if 'pending_image' in st.session_state and st.session_state.pending_image:
        st.markdown("### 🎯 Validate Generation")
        
        pending_img = Image.open(io.BytesIO(st.session_state.pending_image))
        
        # Show source and result side by side
        col_src, col_result = st.columns(2)
        
        with col_src:
            st.markdown("**Source Frame**")
            if 'pending_source_frame' in st.session_state:
                st.image(st.session_state.pending_source_frame, use_container_width=True)
        
        with col_result:
            st.markdown("**Generated Image**")
            st.image(pending_img, use_container_width=True)
        
        st.markdown("---")
        
        # Validation buttons
        st.markdown("""
        <div style="text-align: center; padding: 1rem 0;">
            <p style="font-size: 1.2rem; color: #94a3b8;">Garder cette image ?</p>
        </div>
        """, unsafe_allow_html=True)
        
        col_reject, col_spacer, col_accept = st.columns([1, 0.5, 1])
        
        with col_reject:
            if st.button(
                "❌ Rejeter",
                use_container_width=True,
                type="secondary",
                key="reject_btn"
            ):
                # Clear pending image
                st.session_state.pending_image = None
                st.session_state.pending_video_name = None
                st.session_state.pending_source_frame = None
                st.toast("🗑️ Image rejetée", icon="❌")
                st.rerun()
        
        with col_accept:
            if st.button(
                "✅ Valider & Sauvegarder",
                use_container_width=True,
                type="primary",
                key="accept_btn"
            ):
                # Save to gallery
                base_name = st.session_state.pending_video_name
                existing = list(generated_images.glob(f"{base_name}_*.png"))
                iteration = len(existing) + 1
                output_name = f"{base_name}_{iteration:03d}.png"
                output_path = generated_images / output_name
                
                pending_img.save(output_path, "PNG", quality=95)
                
                # Clear pending
                st.session_state.pending_image = None
                st.session_state.pending_video_name = None
                st.session_state.pending_source_frame = None
                st.session_state.last_saved_image = str(output_path)
                
                st.toast(f"💾 Sauvegardé: {output_name}", icon="✅")
                st.rerun()
        
        # Additional actions for pending image
        st.markdown("---")
        col_dl, col_regen = st.columns(2)
        
        with col_dl:
            st.download_button(
                "⬇️ Télécharger (sans sauvegarder)",
                st.session_state.pending_image,
                file_name=f"{st.session_state.pending_video_name}_preview.png",
                mime="image/png",
                use_container_width=True
            )
        
        with col_regen:
            if st.button("🔄 Régénérer", use_container_width=True):
                st.session_state.pending_image = None
                st.rerun()
    
    # Show last saved confirmation
    if 'last_saved_image' in st.session_state and st.session_state.last_saved_image:
        saved_path = Path(st.session_state.last_saved_image)
        if saved_path.exists():
            st.success(f"✅ Dernière image sauvegardée: `{saved_path.name}`")
            
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                with open(saved_path, 'rb') as f:
                    st.download_button(
                        "⬇️ Download",
                        f,
                        file_name=saved_path.name,
                        mime="image/png",
                        use_container_width=True
                    )
            with col_b:
                if st.button("🎬 Use in Video Studio", use_container_width=True, key="use_video_btn"):
                    st.session_state.selected_image_for_video = str(saved_path)
                    st.session_state.current_page = 'video_studio'
                    st.session_state.last_saved_image = None
                    st.rerun()
            with col_c:
                if st.button("🔄 New Generation", use_container_width=True, key="new_gen_btn"):
                    st.session_state.last_saved_image = None
                    st.rerun()
    
    # ===== Recent Generated Images =====
    st.markdown("---")
    st.markdown("### 📸 Recent Generations")
    
    recent_images = sorted(
        generated_images.glob("*.png"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )[:8]
    
    if recent_images:
        cols = st.columns(4)
        for idx, img in enumerate(recent_images):
            with cols[idx % 4]:
                st.image(str(img), use_container_width=True)
                st.caption(img.stem[:15] + "...")
    else:
        st.info("No generated images yet. Create your first Ghibli frame above!")
