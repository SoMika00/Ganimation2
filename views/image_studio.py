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
                    disabled=not pulid_enabled,
                    key="pulid_id_upload",
                )
                if pulid_upload is not None:
                    pulid_id_image = Image.open(pulid_upload).convert('RGB')
                    st.image(pulid_id_image, caption="PuLID identity image", use_container_width=True)

            pulid_method = st.selectbox(
                "PuLID method",
                options=["fidelity", "style", "neutral"],
                index=1,
                disabled=not pulid_enabled,
                help=(
                    "style : aide à préserver l'identité même quand tu pousses le style\n"
                    "fidelity : verrouille plus fort l'identité\n"
                    "neutral : compromis"
                ),
            )

            pulid_weight = st.slider(
                "PuLID weight",
                min_value=0.0,
                max_value=2.0,
                value=1.0,
                step=0.05,
                disabled=not pulid_enabled,
                help=(
                    "0.6–1.0 : garde bien l’identité sans trop bloquer le style\n"
                    "1.0–1.4 : verrouille fort (utile si le visage dérive)\n"
                    ">1.4 : peut figer / créer des artefacts\n"
                    "Reco départ : 1.0"
                ),
            )

            pulid_start = st.slider(
                "PuLID start %",
                min_value=0.0,
                max_value=1.0,
                value=0.05,
                step=0.05,
                disabled=not pulid_enabled,
                help=(
                    "Quand PuLID s'applique pendant la diffusion.\n"
                    "Réglage standard efficace : Start 0.05 → End 0.85\n"
                    "Pourquoi : au début tu laisses le modèle poser le style, puis PuLID stabilise l'identité."
                ),
            )

            pulid_end = st.slider(
                "PuLID end %",
                min_value=0.0,
                max_value=1.0,
                value=0.85,
                step=0.05,
                disabled=not pulid_enabled,
                help="Réglage standard efficace : Start 0.05 → End 0.85",
            )
            
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
                step=0.5,
                help=(
                    "4.5–6 : top quand tu as LoRA + PuLID + ControlNet\n"
                    "Trop haut = 'cassant' (anatomie/traits)\n"
                    "Reco départ : 5.0"
                )
            )

            denoise = st.slider(
                "Denoise (img2img strength)",
                min_value=0.30,
                max_value=0.95,
                value=0.48,
                step=0.05,
                help=(
                    "Le bouton principal 'photo → dessin'.\n"
                    "0.30–0.40 : proche de la photo (stylisation modérée)\n"
                    "0.42–0.55 : idéal pour transformer tout le corps en gardant la personne\n"
                    "0.60+ : tu perds vite les traits\n"
                    "Reco départ : 0.48"
                )
            )
            
            st.markdown("---")
            
            # ControlNet
            st.markdown("**🎛️ ControlNet**")

            controlnet_depth_enabled = st.checkbox("Enable Depth", value=True)
            controlnet_depth_strength = st.slider(
                "Depth weight",
                min_value=0.0,
                max_value=1.0,
                value=0.65,
                step=0.05,
                disabled=not controlnet_depth_enabled,
                help=(
                    "0.45–0.70 : bon verrou de pose et volumes\n"
                    "Reco départ : 0.65"
                ),
            )
            controlnet_depth_start = st.slider(
                "Depth start %",
                min_value=0.0,
                max_value=1.0,
                value=0.0,
                step=0.05,
                disabled=not controlnet_depth_enabled,
                help="Reco départ : Start 0.00 → End 0.85",
            )
            controlnet_depth_end = st.slider(
                "Depth end %",
                min_value=0.0,
                max_value=1.0,
                value=0.85,
                step=0.05,
                disabled=not controlnet_depth_enabled,
                help="Laisse la fin s'affiner sans surcontrainte. Reco : 0.85",
            )

            st.markdown("---")

            controlnet_canny_enabled = st.checkbox("Enable Canny", value=True)
            controlnet_canny_strength = st.slider(
                "Canny weight",
                min_value=0.0,
                max_value=1.0,
                value=0.40,
                step=0.05,
                disabled=not controlnet_canny_enabled,
                help="0.25–0.55 : donne du dessin sans rigidifier. Reco : 0.40",
            )
            controlnet_canny_start = st.slider(
                "Canny start %",
                min_value=0.0,
                max_value=1.0,
                value=0.05,
                step=0.05,
                disabled=not controlnet_canny_enabled,
                help="Reco départ : Start 0.05 → End 0.75",
            )
            controlnet_canny_end = st.slider(
                "Canny end %",
                min_value=0.0,
                max_value=1.0,
                value=0.75,
                step=0.05,
                disabled=not controlnet_canny_enabled,
                help="Reco départ : 0.75 (évite contours trop durs à la fin)",
            )

            canny_low_threshold = st.slider(
                "Canny Low",
                min_value=1,
                max_value=255,
                value=80,
                step=1,
                disabled=not controlnet_canny_enabled,
                help=(
                    "Seuil de détection des bords.\n"
                    "Reco universelle photo : Low 80 / High 200\n"
                    "Trop de bords parasites : 120 / 240\n"
                    "Pas assez de contours : 50 / 150"
                ),
            )
            canny_high_threshold = st.slider(
                "Canny High",
                min_value=1,
                max_value=255,
                value=200,
                step=1,
                disabled=not controlnet_canny_enabled,
                help=(
                    "Seuil de détection des bords.\n"
                    "Reco universelle photo : Low 80 / High 200\n"
                    "Trop de bords parasites : 120 / 240\n"
                    "Pas assez de contours : 50 / 150"
                ),
            )

            st.markdown("---")

            st.markdown("**📝 Prompting**")
            prompt = st.text_area(
                "Prompt",
                value=(
                    "StdGBRedmAF, Studio Ghibli, full body character, clean silhouette, hand-painted animated film look, "
                    "soft lineart, warm pastel palette, gentle shading, watercolor-like textures, consistent anatomy, "
                    "detailed clothing folds, clean face, natural proportions, cinematic lighting, cohesive style"
                    if preset_full_body
                    else "StdGBRedmAF, Studio Ghibli, anime illustration, masterpiece, high quality, detailed, beautiful lighting, soft colors, whimsical, hand-drawn aesthetic"
                ),
                height=120,
            )
            negative_prompt = st.text_area(
                "Negative Prompt",
                value=(
                    "photorealistic, plastic skin, harsh shadows, noisy texture, messy lineart, deformed body, bad hands, "
                    "extra fingers, extra limbs, text, watermark, logo"
                    if preset_full_body
                    else "low quality, bad anatomy, worst quality, low resolution, blurry, distorted, ugly, duplicate, watermark, signature, jpeg artifacts, photorealistic, 3d render"
                ),
                height=90,
            )
            
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
        
        # Prepare settings
        if seed == -1:
            base_seed = random.randint(0, 2**32 - 1)
            seeds = [base_seed + i for i in range(num_variations)]
        else:
            seeds = [int(seed) + i for i in range(num_variations)]

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
        
        try:
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
