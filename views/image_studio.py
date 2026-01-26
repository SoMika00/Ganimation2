"""
Image Studio Page
Generate Ghibli-style frames using ComfyUI (SDXL + ControlNet + LoRA)
"""

import streamlit as st
from pathlib import Path
from PIL import Image
import time
import io
import random
import os
import json

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
    comfyui_host = os.getenv("COMFYUI_HOST", "127.0.0.1")
    comfyui_port = int(os.getenv("COMFYUI_PORT", "8188"))
    comfyui = ComfyUIClient(host=comfyui_host, port=comfyui_port)

    workflows_dir = Path(os.getenv("COMFYUI_WORKFLOWS_DIR", str(Path(__file__).parent.parent / "data" / "comfyui" / "user" / "default" / "workflows")))
    
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
            st.markdown("**🧩 Workflow**")
            selected_workflow_name = "I2M GYB.json"
            selected_workflow_path = workflows_dir / selected_workflow_name
            if selected_workflow_path.exists():
                st.caption(f"Using workflow: {selected_workflow_name}")
            else:
                st.warning(f"Workflow not found: {selected_workflow_path}")

            st.session_state.comfy_selected_workflow = selected_workflow_name

            i2i_defaults = None
            if comfyui_available and selected_workflow_path.exists() and selected_workflow_name == "I2M GYB.json":
                try:
                    cache_key = f"wf_defaults::{selected_workflow_name}::{int(selected_workflow_path.stat().st_mtime)}"
                    if st.session_state.get("_wf_defaults_cache_key") != cache_key:
                        wf_ui = json.loads(selected_workflow_path.read_text(encoding="utf-8"))
                        wf_api = comfyui.workflow_convert(wf_ui)
                        if wf_api:
                            st.session_state._wf_defaults_cache_key = cache_key
                            st.session_state._wf_api_template = wf_api
                            st.session_state._wf_i2i_defaults = comfyui.extract_i2i_gibly_defaults(wf_api)
                        else:
                            st.session_state._wf_i2i_defaults = None
                    i2i_defaults = st.session_state.get("_wf_i2i_defaults")
                except Exception:
                    i2i_defaults = None

            if selected_workflow_name == "I2M GYB.json":
                if not selected_workflow_path.exists():
                    st.warning(f"Workflow not found: {selected_workflow_path}")
                elif not comfyui_available:
                    st.caption("Start ComfyUI to load workflow defaults")
                elif i2i_defaults is None:
                    st.caption("Could not load defaults from /workflow/convert (is the converter custom node installed?)")

            preset_full_body = True

            if selected_workflow_name == "I2M GYB.json":
                st.markdown("**🎨 Style (LoRA)**")
                default_strength_model = float((i2i_defaults or {}).get("strength_model", 0.9))
                default_strength_clip = float((i2i_defaults or {}).get("strength_clip", 1.0))
                strength_model = st.slider(
                    "LoRA strength_model",
                    min_value=0.0,
                    max_value=2.0,
                    value=default_strength_model,
                    step=0.05,
                    help="Force LoRA sur le modèle (default = valeur du workflow)",
                )
                strength_clip = st.slider(
                    "LoRA strength_clip",
                    min_value=0.0,
                    max_value=2.0,
                    value=default_strength_clip,
                    step=0.05,
                    help="Force LoRA sur le CLIP (default = valeur du workflow)",
                )
            else:
                # Legacy SDXL workflow controls
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

            pulid_enabled = False
            pulid_use_frame_as_id = True
            pulid_id_image = None
            pulid_method = None
            pulid_weight = None
            pulid_start = None
            pulid_end = None
            
            # Sampling
            st.markdown("**🔧 Sampling**")

            default_steps = int((i2i_defaults or {}).get("steps", 28))
            default_guidance = float((i2i_defaults or {}).get("guidance", 2.7))
            default_cfg = float((i2i_defaults or {}).get("cfg", 1.0))
            steps = st.slider(
                "Steps",
                min_value=5,
                max_value=80,
                value=default_steps,
                step=1,
                help="Nombre d'itérations (default = valeur du workflow)",
            )
            cfg = st.slider(
                "CFG",
                min_value=0.0,
                max_value=20.0,
                value=default_cfg,
                step=0.1,
                help="CFG (default = valeur du workflow)",
            )
            guidance = st.slider(
                "GuidanceFlux (guidance)",
                min_value=0.0,
                max_value=20.0,
                value=default_guidance,
                step=0.1,
                help="Guidance Flux (default = valeur du workflow)",
            )
            
            st.markdown("---")

            st.markdown("**📝 Prompting**")
            prompt_override_enabled = st.checkbox(
                "Override workflow prompt",
                value=False,
                help="Par défaut, on garde le prompt dans le workflow. Active seulement si tu veux le remplacer côté Streamlit.",
            )

            default_prompt = None
            try:
                wf_api_cached = st.session_state.get("_wf_api_template")
                if isinstance(wf_api_cached, dict):
                    default_prompt = comfyui.extract_i2i_gibly_prompt_text(wf_api_cached)
            except Exception:
                default_prompt = None

            if prompt_override_enabled:
                prompt = st.text_area(
                    "Prompt",
                    value=default_prompt or "",
                    height=120,
                )
            else:
                prompt = None
                st.caption("Using prompt from workflow")
            
            st.markdown("---")
            
            # Seed
            st.markdown("**🎲 Seed**")
            seed_random = st.checkbox("Random seed", value=True)
            if seed_random:
                seed = -1
            else:
                seed = st.number_input("Seed", min_value=0, max_value=2147483647, value=42)

            st.markdown("---")

            st.markdown("**🧪 Variations**")
            num_variations = st.slider(
                "Number of variations",
                min_value=1,
                max_value=8,
                value=4,
                step=1,
                help="Generate multiple candidates with different seeds; choose the best for Wan Animate.",
            )
        
        # Generate button
        st.markdown("---")
        
        can_generate = (
            'selected_frame' in st.session_state 
            and st.session_state.selected_frame 
            and comfyui_available
        )
        
        generate_label = "🚀 Generate" if st.session_state.get("comfy_selected_workflow") == "I2M GYB.json" else "🚀 Generate Ghibli Frame"
        generate_btn = st.button(
            generate_label,
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

        # Pick an SDXL-friendly size (multiple of 64) while keeping the frame orientation.
        # This prevents the previous 1024x1024 squashing.
        w0, h0 = source_frame.size
        if h0 >= w0 * 1.2:          # portrait
            target_w, target_h = 896, 1600
        elif w0 >= h0 * 1.2:        # landscape
            target_w, target_h = 1600, 896
        else:                       # roughly square
            target_w, target_h = 1024, 1024

        if (w0, h0) != (target_w, target_h):
            resample = getattr(Image, "Resampling", Image).LANCZOS
            source_frame = source_frame.resize((target_w, target_h), resample)
        
        # Prepare seeds
        if seed == -1:
            base_seed = random.randint(0, 2**32 - 1)
            seeds = [base_seed + i for i in range(num_variations)]
        else:
            seeds = [int(seed) + i for i in range(num_variations)]
        
        try:
            if st.session_state.get("comfy_selected_workflow") == "I2M GYB.json":
                workflow_path = workflows_dir / "I2M GYB.json"
                if not workflow_path.exists():
                    raise FileNotFoundError(f"Workflow not found: {workflow_path}")

                # For now we feed the selected frame as both inputs (image1/image2)
                # until you confirm what image2 should be (e.g. mask/second ref).
                success, message, result_images = comfyui.generate_i2i_gibly(
                    image1=source_frame,
                    image2=source_frame,
                    workflow_ui_path=workflow_path,
                    text=prompt,
                    strength_model=float(strength_model),
                    strength_clip=float(strength_clip),
                    guidance=float(guidance),
                    cfg=float(cfg),
                    steps=int(steps),
                    seeds=seeds,
                    filename_prefix_base=f"ganimation_i2i_gibly_{selected_video_name}",
                    progress_callback=update_progress,
                )
            else:
                settings = {
                    'lora_name': lora_name,
                    'lora_weight': lora_weight,
                    'cfg_scale': cfg_scale,
                    'steps': steps,
                    'seed': seed,
                    'controlnet_depth_enabled': controlnet_depth_enabled,
                    'controlnet_canny_enabled': controlnet_canny_enabled,
                    'controlnet_depth_strength': controlnet_depth_strength,
                    'controlnet_depth_start': controlnet_depth_start,
                    'controlnet_depth_end': controlnet_depth_end,
                    'controlnet_canny_strength': controlnet_canny_strength,
                    'controlnet_canny_start': controlnet_canny_start,
                    'controlnet_canny_end': controlnet_canny_end,
                    'canny_low_threshold': canny_low_threshold,
                    'canny_high_threshold': canny_high_threshold,
                    'denoise': denoise,
                    'prompt': prompt,
                    'negative_prompt': negative_prompt,
                    'pulid_enabled': pulid_enabled,
                    'pulid_file': 'pulid_v1.1.safetensors',
                    'pulid_method': pulid_method,
                    'pulid_weight': pulid_weight,
                    'pulid_start': pulid_start,
                    'pulid_end': pulid_end,
                    'pulid_provider': 'CUDA',
                    'pulid_id_image': None if pulid_use_frame_as_id else pulid_id_image,
                    'num_variations': num_variations,
                    'seeds': seeds,
                    'width': target_w,
                    'height': target_h,
                    'depth_resolution': max(target_w, target_h),
                }

                success, message, result_images = comfyui.generate_ghibli_image(
                    source_frame,
                    settings=settings,
                    progress_callback=update_progress
                )
            
            if success and result_images:
                progress_bar.progress(1.0)
                status_text.empty()
                
                # Store in session for validation
                pending_images = []
                for img in result_images:
                    img_buffer = io.BytesIO()
                    img.save(img_buffer, format='PNG')
                    pending_images.append(img_buffer.getvalue())

                st.session_state.pending_images = pending_images
                st.session_state.pending_seeds = seeds
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
    if 'pending_images' in st.session_state and st.session_state.pending_images:
        st.markdown("### 🎯 Validate Generation")

        pending_imgs = [Image.open(io.BytesIO(b)) for b in st.session_state.pending_images]
        pending_seeds = st.session_state.get('pending_seeds')
        
        # Show source and result side by side
        col_src, col_result = st.columns(2)
        
        with col_src:
            st.markdown("**Source Frame**")
            if 'pending_source_frame' in st.session_state:
                st.image(st.session_state.pending_source_frame, use_container_width=True)
        
        with col_result:
            st.markdown("**Generated Images**")
            cols = st.columns(2)
            selected_idxs = []
            for idx, img in enumerate(pending_imgs):
                with cols[idx % 2]:
                    seed_label = ""
                    if pending_seeds and idx < len(pending_seeds):
                        seed_label = f" (seed {pending_seeds[idx]})"
                    st.image(img, use_container_width=True)
                    if st.checkbox(f"Select{seed_label}", value=(idx == 0), key=f"select_gen_{idx}"):
                        selected_idxs.append(idx)
        
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
                st.session_state.pending_images = None
                st.session_state.pending_seeds = None
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
                base_name = st.session_state.pending_video_name
                existing = list(generated_images.glob(f"{base_name}_*.png"))
                iteration = len(existing) + 1
                saved_paths = []

                if not selected_idxs:
                    selected_idxs = [0]

                for idx in selected_idxs:
                    output_name = f"{base_name}_{iteration:03d}.png"
                    output_path = generated_images / output_name
                    pending_imgs[idx].save(output_path, "PNG", quality=95)
                    saved_paths.append(str(output_path))
                    iteration += 1
                
                # Clear pending
                st.session_state.pending_images = None
                st.session_state.pending_seeds = None
                st.session_state.pending_video_name = None
                st.session_state.pending_source_frame = None
                st.session_state.last_saved_image = saved_paths[-1] if saved_paths else None
                
                st.toast(f"💾 Sauvegardé: {len(saved_paths)} image(s)", icon="✅")
                st.rerun()
        
        # Additional actions for pending image
        st.markdown("---")
        col_dl, col_regen = st.columns(2)
        
        with col_dl:
            st.download_button(
                "⬇️ Télécharger (sans sauvegarder)",
                st.session_state.pending_images[0],
                file_name=f"{st.session_state.pending_video_name}_preview.png",
                mime="image/png",
                use_container_width=True
            )
        
        with col_regen:
            if st.button("🔄 Régénérer", use_container_width=True):
                st.session_state.pending_images = None
                st.session_state.pending_seeds = None
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
