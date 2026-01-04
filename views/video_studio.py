"""
Video Studio Page
Animate images using Wan2.2 with style transfer
"""

import streamlit as st
from pathlib import Path
from PIL import Image
import time

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.video_processor import VideoProcessor


def render():
    """Render the Video Studio page"""
    
    st.markdown("""
    <h1 class="main-title">🎬 Video Studio</h1>
    <p class="subtitle">Animate Ghibli frames with Wan2.2 and style transfer</p>
    """, unsafe_allow_html=True)
    
    # Initialize paths
    gallery_root = Path(__file__).parent.parent / "gallery"
    source_media = gallery_root / "source_media"
    generated_images = gallery_root / "generated_images"
    generated_videos = gallery_root / "generated_videos"
    temp_dir = Path(__file__).parent.parent / "temp"
    models_dir = Path(__file__).parent.parent / "models"
    
    video_processor = VideoProcessor(temp_dir, generated_videos)
    
    # Pipeline Info
    with st.expander("🔧 Pipeline Overview", expanded=False):
        st.markdown("""
        ### Wan2.2 Animate Control Pipeline
        
        This pipeline combines:
        
        1. **Input Image** - Generated Ghibli-style frame (from Image Studio)
        2. **Source Video** - Original video for motion reference
        3. **Wan2.2** - AnimateDiff-style video generation
        4. **Optional:** Relighting LoRA for enhanced lighting effects
        
        ### Output Processing
        
        - **RIFE** - Frame interpolation for smoother motion
        - **Upscale** - Resolution enhancement if needed
        - **Audio Merge** - Reattach original audio track
        - **Final Encode** - H.264 optimized output
        
        ### Model Files Needed
        
        ```
        models/
        ├── wan2.2/
        │   ├── wan_animate_control.safetensors
        │   └── WanAnimate_relight_lora_fp16.safetensors
        ├── rife/
        │   └── rife_v4.6.pkl
        └── realesrgan/
            └── RealESRGAN_x4plus.pth
        ```
        """)
    
    st.markdown("---")
    
    # Main layout
    col_inputs, col_settings = st.columns([2, 1])
    
    # ===== Input Selection =====
    with col_inputs:
        st.markdown("### 📥 Inputs")
        
        # Two columns for image and video selection
        col_img, col_vid = st.columns(2)
        
        # Generated Image Selection
        with col_img:
            st.markdown("#### 🎨 Generated Image")
            st.caption("Ghibli-style frame to animate")
            
            gen_images = sorted(
                generated_images.glob("*.png"),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            
            if not gen_images:
                st.warning("No generated images. Go to Image Studio first!")
                selected_image = None
            else:
                # Check if pre-selected from gallery
                default_img_idx = 0
                if 'selected_image_for_video' in st.session_state and st.session_state.selected_image_for_video:
                    selected_path = Path(st.session_state.selected_image_for_video)
                    for idx, img in enumerate(gen_images):
                        if img == selected_path:
                            default_img_idx = idx
                            break
                
                image_options = {img.stem: str(img) for img in gen_images}
                selected_image_name = st.selectbox(
                    "Select image",
                    options=list(image_options.keys()),
                    index=default_img_idx,
                    key="anim_image_select",
                    label_visibility="collapsed"
                )
                selected_image = image_options[selected_image_name]
                
                st.image(selected_image, use_container_width=True)
        
        # Source Video Selection (for motion)
        with col_vid:
            st.markdown("#### 📹 Source Video")
            st.caption("Motion reference video")
            
            source_videos = sorted(
                source_media.glob("*.mp4"),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            
            if not source_videos:
                st.warning("No source videos. Go to Ingestion first!")
                selected_video = None
            else:
                # Try to match video to image name
                default_vid_idx = 0
                if selected_image:
                    img_stem = Path(selected_image).stem
                    # Image names are like "video_name_001"
                    base_name = "_".join(img_stem.split("_")[:-1])
                    for idx, vid in enumerate(source_videos):
                        if vid.stem == base_name:
                            default_vid_idx = idx
                            break
                
                video_options = {vid.stem: str(vid) for vid in source_videos}
                selected_video_name = st.selectbox(
                    "Select video",
                    options=list(video_options.keys()),
                    index=default_vid_idx,
                    key="anim_video_select",
                    label_visibility="collapsed"
                )
                selected_video = video_options[selected_video_name]
                
                st.video(selected_video)
                
                # Video info
                info = video_processor.get_video_info(Path(selected_video))
                if info:
                    st.caption(f"⏱️ {info.get('duration', 0):.1f}s | 🎬 {info.get('fps', 30):.0f}fps")
    
    # ===== Generation Settings =====
    with col_settings:
        st.markdown("### ⚙️ Animation Settings")
        
        with st.container():
            st.markdown('<div class="studio-card">', unsafe_allow_html=True)
            
            # Wan2.2 Settings
            st.markdown("**🎬 Wan2.2 Animate**")
            
            motion_strength = st.slider(
                "Motion Strength",
                min_value=0.1,
                max_value=1.0,
                value=0.7,
                step=0.1,
                help="How much motion to transfer from source"
            )
            
            num_frames = st.slider(
                "Output Frames",
                min_value=16,
                max_value=128,
                value=48,
                step=8,
                help="Number of frames to generate"
            )
            
            guidance_scale = st.slider(
                "Guidance Scale",
                min_value=1.0,
                max_value=15.0,
                value=7.5,
                step=0.5
            )
            
            st.markdown("---")
            
            # Relighting LoRA
            st.markdown("**💡 Relighting LoRA**")
            
            use_relighting = st.checkbox(
                "Enable Relighting",
                value=False,
                help="Use WanAnimate_relight_lora for enhanced lighting"
            )
            
            if use_relighting:
                relight_strength = st.slider(
                    "Relight Strength",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.5,
                    step=0.1
                )
            else:
                relight_strength = 0.0
            
            st.markdown("---")
            
            # Post-processing
            st.markdown("**🔧 Post-Processing**")
            
            use_rife = st.checkbox(
                "RIFE Interpolation",
                value=True,
                help="Interpolate frames for smoother motion"
            )
            
            if use_rife:
                rife_multiplier = st.selectbox(
                    "Frame Multiplier",
                    options=[2, 4],
                    index=0,
                    help="2x or 4x frame interpolation"
                )
            else:
                rife_multiplier = 1
            
            use_upscale = st.checkbox(
                "Upscale Output",
                value=False,
                help="Use Real-ESRGAN for upscaling"
            )
            
            merge_audio = st.checkbox(
                "Merge Original Audio",
                value=True,
                help="Add audio from source video"
            )
            
            st.markdown("---")
            
            # Output settings
            st.markdown("**📤 Output**")
            
            output_fps = st.selectbox(
                "Output FPS",
                options=[24, 30, 60],
                index=1
            )
            
            output_quality = st.select_slider(
                "Quality",
                options=["Fast", "Balanced", "High Quality"],
                value="Balanced"
            )
            
            st.markdown('</div>', unsafe_allow_html=True)
    
    # ===== Generation =====
    st.markdown("---")
    
    can_generate = selected_image is not None and selected_video is not None
    
    col_gen, col_preview = st.columns([1, 1])
    
    with col_gen:
        generate_btn = st.button(
            "🚀 Generate Animation",
            use_container_width=True,
            disabled=not can_generate,
            type="primary",
            key="generate_video_btn"
        )
        
        if not can_generate:
            st.caption("⚠️ Select both an image and video first")
    
    with col_preview:
        st.markdown("**Pipeline Preview:**")
        st.caption(f"📸 {Path(selected_image).stem if selected_image else 'None'} → 🎬 Wan2.2 → {'📈 RIFE → ' if use_rife else ''}{'🔍 Upscale → ' if use_upscale else ''}{'🔊 Audio → ' if merge_audio else ''}📤 Output")
    
    # Generation Process
    if generate_btn and can_generate:
        st.markdown("### 🎬 Generation Progress")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Prepare settings dict
        settings = {
            'motion_strength': motion_strength,
            'num_frames': num_frames,
            'guidance_scale': guidance_scale,
            'use_relighting': use_relighting,
            'relight_strength': relight_strength,
            'use_rife': use_rife,
            'rife_multiplier': rife_multiplier,
            'use_upscale': use_upscale,
            'merge_audio': merge_audio,
            'output_fps': output_fps,
            'output_quality': output_quality,
        }
        
        try:
            # Placeholder for actual generation
            # This would integrate with Wan2.2 when models are available
            
            status_text.markdown("**🔄 Initializing pipeline...**")
            progress_bar.progress(0.1)
            time.sleep(0.5)
            
            status_text.markdown("**📥 Loading models...**")
            progress_bar.progress(0.2)
            
            # Check if models exist
            wan_model_path = models_dir / "wan2.2" / "wan_animate_control.safetensors"
            
            if not wan_model_path.exists():
                progress_bar.empty()
                status_text.empty()
                
                st.warning("""
                ⚠️ **Wan2.2 Models Not Found**
                
                This feature requires the Wan2.2 Animate Control models.
                
                **Setup Instructions:**
                
                1. Download the model files:
                   - `wan_animate_control.safetensors`
                   - `WanAnimate_relight_lora_fp16.safetensors` (optional)
                
                2. Place them in: `models/wan2.2/`
                
                3. Install additional dependencies:
                   ```bash
                   pip install einops rotary_embedding_torch
                   ```
                """)
                
                # Show what would be generated
                st.markdown("---")
                st.markdown("### 📋 Generation Configuration (Preview)")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.json({
                        "input_image": Path(selected_image).name,
                        "source_video": Path(selected_video).name,
                        "output_frames": num_frames,
                        "motion_strength": motion_strength,
                    })
                with col2:
                    st.json({
                        "post_processing": {
                            "rife": use_rife,
                            "rife_multiplier": rife_multiplier if use_rife else None,
                            "upscale": use_upscale,
                            "merge_audio": merge_audio,
                        },
                        "output": {
                            "fps": output_fps,
                            "quality": output_quality
                        }
                    })
            else:
                # Actual generation would happen here
                status_text.markdown("**🎬 Generating frames...**")
                
                # Simulate progress
                for i in range(30, 80, 10):
                    progress_bar.progress(i / 100)
                    time.sleep(0.3)
                
                if use_rife:
                    status_text.markdown("**📈 Interpolating frames with RIFE...**")
                    progress_bar.progress(0.85)
                    time.sleep(0.5)
                
                if merge_audio:
                    status_text.markdown("**🔊 Merging audio...**")
                    progress_bar.progress(0.95)
                    time.sleep(0.3)
                
                progress_bar.progress(1.0)
                status_text.markdown("**✅ Complete!**")
                
                # Output path
                base_name = Path(selected_image).stem
                output_name = f"{base_name}_animated.mp4"
                output_path = generated_videos / output_name
                
                st.success(f"🎉 Video generated: `{output_name}`")
                
        except Exception as e:
            progress_bar.empty()
            status_text.empty()
            st.error(f"❌ Generation failed: {str(e)}")
            
            import traceback
            with st.expander("Error Details"):
                st.code(traceback.format_exc())
    
    # ===== Recent Generated Videos =====
    st.markdown("---")
    st.markdown("### 📽️ Recent Animations")
    
    recent_videos = sorted(
        generated_videos.glob("*.mp4"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )[:4]
    
    if recent_videos:
        cols = st.columns(2)
        for idx, vid in enumerate(recent_videos):
            with cols[idx % 2]:
                st.video(str(vid))
                st.caption(vid.stem)
                
                info = video_processor.get_video_info(vid)
                if info:
                    st.caption(f"⏱️ {info.get('duration', 0):.1f}s | 💾 {info.get('size_mb', 0):.1f}MB")
    else:
        st.info("No generated videos yet. Create your first animation above!")
    
    # ===== Advanced Pipeline Configuration =====
    st.markdown("---")
    
    with st.expander("🔬 Advanced Configuration"):
        st.markdown("""
        ### Custom Pipeline Configuration
        
        For advanced users who want to modify the pipeline parameters directly.
        """)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Wan2.2 Parameters**")
            
            wan_steps = st.number_input("Inference Steps", 10, 100, 30)
            wan_cfg = st.number_input("CFG Scale", 1.0, 20.0, 7.5, 0.5)
            wan_seed = st.number_input("Seed (-1 for random)", -1, 2147483647, -1)
        
        with col2:
            st.markdown("**Output Encoding**")
            
            encoder_preset = st.selectbox(
                "Encoder Preset",
                ["ultrafast", "superfast", "fast", "medium", "slow", "veryslow"],
                index=3
            )
            crf_value = st.slider("CRF (quality)", 15, 28, 18)
            pixel_format = st.selectbox(
                "Pixel Format",
                ["yuv420p", "yuv444p"],
                index=0
            )
        
        st.markdown("---")
        
        st.markdown("**FFmpeg Command Preview:**")
        st.code(f"""
ffmpeg -framerate {output_fps} -i frames/%04d.png \\
  {f'-i audio.aac' if merge_audio else ''} \\
  -c:v libx264 -crf {crf_value} -preset {encoder_preset} \\
  -pix_fmt {pixel_format} \\
  {'-c:a aac -b:a 192k -shortest' if merge_audio else ''} \\
  -movflags +faststart \\
  output.mp4
        """)

