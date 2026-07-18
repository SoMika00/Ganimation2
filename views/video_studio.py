'''
Video Studio Page
Animate images using Wan2.2 with style transfer
'''

import streamlit as st
from pathlib import Path
from PIL import Image
import time
import os
import requests

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.video_processor import VideoProcessor
from utils.video_animator import VideoAnimator, PostProcessor

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
    """Render the Video Studio page"""
    
    st.markdown("""
    <h1 class="main-title">🎬 Video Studio</h1>
    <p class="subtitle">Run animation conversion pipelines (Wan Animate 2.2)</p>
    """, unsafe_allow_html=True)
    
    # Initialize paths
    gallery_root = Path(__file__).parent.parent / "gallery"
    source_media = gallery_root / "source_media"
    generated_images = gallery_root / "generated_images"
    generated_videos = gallery_root / "generated_videos"
    temp_dir = Path(__file__).parent.parent / "temp"
    models_dir = Path(__file__).parent.parent / "models"
    
    video_processor = VideoProcessor(temp_dir, generated_videos)
    video_animator = VideoAnimator(models_dir, temp_dir)
    post_processor = PostProcessor(temp_dir, generated_videos)
    
    pipeline_name = st.selectbox(
        "Pipeline",
        options=["Wan Animate 2.2 (Animate Control)"],
        index=0,
    )
    
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
            st.caption("Input subject image (generated via IA)")
            
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
            st.caption("Base video (motion reference)")
            
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
    
    # ===== Pipeline Settings =====
    with col_settings:
        st.markdown("### ⚙️ Pipeline Settings")
        
        with st.container():
            st.markdown("**💡 Optional: Relighting LoRA**")

            wan_dir = models_dir / "wan2.2"
            relight_primary = wan_dir / "WanAnimate_relight_lora_fp16.safetensors"
            relight_fallback = wan_dir / "WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors"

            available_relight = []
            if relight_primary.exists():
                available_relight.append(str(relight_primary))
            if relight_fallback.exists():
                available_relight.append(str(relight_fallback))

            use_relighting = st.checkbox(
                "Enable Relighting LoRA",
                value=False,
                help="Bonus: improves lighting consistency. If the main LoRA bugs, use the resized fallback.",
            )

            if use_relighting:
                if not available_relight:
                    st.warning("Relighting LoRA not found in models/wan2.2")
                    relight_path = None
                else:
                    relight_path = st.selectbox(
                        "Relight LoRA file",
                        options=available_relight,
                        index=0,
                    )
            else:
                relight_path = None
    
    # ===== Run =====
    st.markdown("---")
    
    can_generate = selected_image is not None and selected_video is not None
    
    generate_btn = st.button(
        "🚀 Run Pipeline",
        use_container_width=True,
        disabled=not can_generate,
        type="primary",
        key="generate_video_btn"
    )

    if not can_generate:
        st.caption("⚠️ Select both an image and video first")
    
    # Generation Process
    if generate_btn and can_generate:
        st.markdown("### 🎬 Generation Progress")
        
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            status_text.markdown(f"**🔄 Initializing: {pipeline_name}...**")
            progress_bar.progress(0.05)

            models_ok = video_animator.check_models()
            if not models_ok.get('wan_animate'):
                progress_bar.empty()
                status_text.empty()
                st.error("Missing model: `models/wan2.2/wan_animate_control.safetensors`")
            else:
                status_text.markdown("**📥 Loading inputs...**")
                progress_bar.progress(0.10)

                input_img = Image.open(selected_image).convert('RGB')
                reference_video_path = Path(selected_video)

                status_text.markdown("**🎬 Running Wan Animate 2.2...**")
                progress_bar.progress(0.20)

                def _progress(p, msg):
                    progress_bar.progress(min(0.20 + p * 0.60, 0.80))
                    status_text.markdown(f"**{msg}**")

                success, msg, frames = video_animator.animate(
                    source_image=input_img,
                    reference_video_path=reference_video_path,
                    settings={
                        'use_relighting': bool(relight_path),
                        'relight_lora_path': relight_path,
                    },
                    progress_callback=_progress,
                )

                if not success or not frames:
                    progress_bar.empty()
                    status_text.empty()
                    st.error(f"❌ Wan Animate failed: {msg}")
                else:
                    status_text.markdown("**📤 Encoding video...**")
                    progress_bar.progress(0.85)

                    run_id = time.strftime("%Y%m%d_%H%M%S")
                    base_name = f"{Path(selected_video).stem}__{Path(selected_image).stem}"
                    output_name = f"{base_name}__wan22__{run_id}.mp4"
                    output_path = generated_videos / output_name

                    tmp_video = temp_dir / f"tmp__{output_name}"
                    ok, enc_msg = post_processor.frames_to_video(
                        frames=frames,
                        output_path=tmp_video,
                        fps=30,
                        crf=18,
                        preset="medium",
                    )
                    if not ok:
                        progress_bar.empty()
                        status_text.empty()
                        st.error(f"❌ Encode failed: {enc_msg}")
                    else:
                        status_text.markdown("**🔊 Merging audio...**")
                        progress_bar.progress(0.95)

                        ok, merge_msg = post_processor.merge_audio(
                            video_path=tmp_video,
                            audio_source=reference_video_path,
                            output_path=output_path,
                        )
                        if ok:
                            try:
                                tmp_video.unlink()
                            except Exception:
                                pass
                            progress_bar.progress(1.0)
                            status_text.markdown("**✅ Complete!**")
                            st.success(f"🎉 Video generated: `{output_name}`")
                            st.video(str(output_path))
                        else:
                            try:
                                tmp_video.replace(output_path)
                            except Exception:
                                pass
                            progress_bar.progress(1.0)
                            status_text.markdown("**✅ Complete (no audio)!**")
                            st.warning(f"Audio merge failed: {merge_msg}")
                            st.success(f"🎉 Video generated: `{output_name}`")
                            st.video(str(output_path))
                
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
    
    st.markdown("---")
    st.caption("New videos appear automatically after generation.")
