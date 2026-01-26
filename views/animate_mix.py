"""
Animate Mix Page
Run the ComfyUI animate_mix workflow with point-based masking.
"""

import os
import time
import random
from pathlib import Path
from typing import List, Dict

import streamlit as st
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.comfyui_client import ComfyUIClient
from utils.video_processor import VideoProcessor


def _center_crop_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _ensure_points_state():
    if "animate_mix_pos_points" not in st.session_state:
        st.session_state.animate_mix_pos_points = []
    if "animate_mix_neg_points" not in st.session_state:
        st.session_state.animate_mix_neg_points = []


def _add_point(x: int, y: int, *, positive: bool):
    _ensure_points_state()
    p = {"x": int(x), "y": int(y)}
    if positive:
        st.session_state.animate_mix_pos_points.append(p)
    else:
        st.session_state.animate_mix_neg_points.append(p)


def render():
    st.markdown(
        """
        <h1 class="main-title">🎬 Animate Mix</h1>
        <p class="subtitle">Animate with Wan2.2 + point mask (ComfyUI workflow: animate_mix)</p>
        """,
        unsafe_allow_html=True,
    )

    gallery_root = Path(__file__).parent.parent / "gallery"
    source_media = gallery_root / "source_media"
    generated_images = gallery_root / "generated_images"
    generated_videos = gallery_root / "generated_videos"
    temp_dir = Path(__file__).parent.parent / "temp"

    for p in (source_media, generated_images, generated_videos, temp_dir):
        p.mkdir(parents=True, exist_ok=True)

    comfyui_host = os.getenv("COMFYUI_HOST", "127.0.0.1")
    comfyui_port = int(os.getenv("COMFYUI_PORT", "8188"))
    comfyui_input_dir = Path(os.getenv("COMFYUI_INPUT_DIR", str(Path(__file__).parent.parent / "data" / "comfyui" / "input")))
    workflows_dir = Path(os.getenv("COMFYUI_WORKFLOWS_DIR", str(Path(__file__).parent.parent / "data" / "comfyui" / "user" / "default" / "workflows")))
    workflow_ui_path = workflows_dir / "animate_mix.json"

    comfyui = ComfyUIClient(host=comfyui_host, port=comfyui_port)
    video_processor = VideoProcessor(temp_dir, source_media)

    if not workflow_ui_path.exists():
        st.error(f"Missing workflow file: `{workflow_ui_path}`")
        return

    col_inputs, col_mask = st.columns([2, 1])

    with col_inputs:
        st.markdown("### 📥 Inputs")

        gen_images = sorted(generated_images.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True)
        source_videos = sorted(source_media.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)

        if not gen_images:
            st.warning("No generated images. Go to Image Studio first!")
            selected_image_path = None
        else:
            image_options = {img.stem: img for img in gen_images}
            selected_image_name = st.selectbox("Reference image", list(image_options.keys()), index=0)
            selected_image_path = image_options[selected_image_name]
            st.image(str(selected_image_path), use_container_width=True)

        if not source_videos:
            st.warning("No source videos. Go to Ingestion first!")
            selected_video_path = None
        else:
            video_options = {vid.stem: vid for vid in source_videos}
            selected_video_name = st.selectbox("Source video", list(video_options.keys()), index=0)
            selected_video_path = video_options[selected_video_name]
            st.video(str(selected_video_path))

    with col_mask:
        st.markdown("### 🎯 Mask points")

        if selected_video_path is None:
            st.caption("Select a source video to edit mask points")
        else:
            frames = video_processor.extract_frames(selected_video_path, num_frames=10)
            if not frames:
                st.warning("Could not extract frames from video")
            else:
                frame_options = {f"frame_{i+1:02d}": fp for i, fp in enumerate(frames)}
                frame_name = st.selectbox("Frame for mask", list(frame_options.keys()), index=0)
                frame_path = frame_options[frame_name]

                img = Image.open(frame_path).convert("RGB")
                img = _center_crop_square(img).resize((768, 768), Image.LANCZOS)

                _ensure_points_state()

                mode = st.radio("Point type", ["Positive", "Negative"], horizontal=True)

                # Click-capture component
                try:
                    from streamlit_image_coordinates import streamlit_image_coordinates

                    value = streamlit_image_coordinates(img, key="animate_mix_mask_click")
                    if value and isinstance(value, dict) and "x" in value and "y" in value:
                        if st.button("Add point", key="animate_mix_add_point"):
                            _add_point(value["x"], value["y"], positive=(mode == "Positive"))
                            st.rerun()
                except Exception:
                    st.warning("streamlit-image-coordinates not available. Install frontend deps.")
                    st.image(img, use_container_width=True)

                colp1, colp2 = st.columns(2)
                with colp1:
                    st.markdown("**Positive points**")
                    st.json(st.session_state.animate_mix_pos_points)
                with colp2:
                    st.markdown("**Negative points**")
                    st.json(st.session_state.animate_mix_neg_points)

                if st.button("Clear points", key="animate_mix_clear_points"):
                    st.session_state.animate_mix_pos_points = []
                    st.session_state.animate_mix_neg_points = []
                    st.rerun()

    st.markdown("---")
    st.markdown("### ⚙️ Settings")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        steps = st.slider("Steps", min_value=8, max_value=30, value=20)
        cfg = st.slider("Guidance / CFG", min_value=0.7, max_value=1.6, value=1.0, step=0.05)
    with col_b:
        segment_length = st.selectbox("Segment length", options=[49, 61, 77, 93], index=2)
        overlap = st.slider("Overlap / conditioning frames", min_value=1, max_value=5, value=1)
    with col_c:
        mask_dilate = st.slider("Mask dilate", min_value=4, max_value=24, value=12)
        use_relight = st.checkbox("Enable relight LoRA", value=False)
        relight_strength = None
        if use_relight:
            relight_strength = st.slider("Relight strength", min_value=0.0, max_value=1.0, value=0.5, step=0.05)

    st.markdown("---")

    can_run = selected_image_path is not None and selected_video_path is not None and len(st.session_state.get("animate_mix_pos_points", [])) > 0
    st.caption("You need at least 1 positive point.")

    run_btn = st.button("🚀 Generate (4 variants)", disabled=not can_run, type="primary")

    if run_btn and can_run:
        if not comfyui.is_available():
            st.error("ComfyUI is not reachable. Check COMFYUI_HOST/COMFYUI_PORT.")
            return

        progress = st.progress(0)
        status = st.empty()

        def _progress(p, msg):
            progress.progress(min(max(p, 0.0), 1.0))
            status.markdown(f"**{msg}**")

        ref_img = Image.open(selected_image_path).convert("RGB")

        base_seed = random.randint(0, 2**32 - 1)
        seeds = [base_seed + i for i in range(4)]

        ok, msg, vids = comfyui.generate_animate_mix(
            reference_image=ref_img,
            reference_video_path=selected_video_path,
            comfyui_input_dir=comfyui_input_dir,
            workflow_ui_path=workflow_ui_path,
            steps=int(steps),
            cfg=float(cfg),
            segment_length=int(segment_length),
            overlap_frames=int(overlap),
            mask_dilate=int(mask_dilate),
            points_positive=list(st.session_state.animate_mix_pos_points),
            points_negative=list(st.session_state.animate_mix_neg_points),
            seeds=seeds,
            relight_strength=relight_strength,
            progress_callback=_progress,
        )

        if not ok or not vids:
            progress.empty()
            status.empty()
            st.error(f"❌ Failed: {msg}")
            return

        progress.progress(1.0)
        status.markdown("**✅ Complete!**")

        st.session_state.animate_mix_last_results = vids

    vids = st.session_state.get("animate_mix_last_results")
    if vids:
        st.markdown("---")
        st.markdown("### 🎞️ Results")

        cols = st.columns(2)
        for idx, (prefix, video_bytes) in enumerate(vids):
            with cols[idx % 2]:
                st.video(video_bytes)
                save_name = f"{prefix}.mp4"
                if st.button("Save to Gallery", key=f"animate_mix_save_{idx}"):
                    out_path = generated_videos / save_name
                    out_path.write_bytes(video_bytes)
                    st.success(f"Saved: `{out_path.name}`")
