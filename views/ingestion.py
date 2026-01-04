"""
Ingestion Page
Import videos via URL (yt-dlp) or upload, then normalize for processing
"""

import streamlit as st
from pathlib import Path
import time
import re

# Import utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.video_processor import VideoProcessor, sanitize_filename


def render():
    """Render the ingestion page"""
    
    # Page header
    st.markdown("""
    <h1 class="main-title">📥 Ingestion</h1>
    <p class="subtitle">Import and normalize videos for AI processing</p>
    """, unsafe_allow_html=True)
    
    # Initialize paths
    gallery_root = Path(__file__).parent.parent / "gallery"
    source_media = gallery_root / "source_media"
    temp_dir = Path(__file__).parent.parent / "temp"
    
    # Initialize processor
    processor = VideoProcessor(temp_dir, source_media)
    
    # Check dependencies
    deps = processor.check_dependencies()
    
    # Dependency status
    with st.expander("🔧 System Requirements", expanded=False):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            status = "✅" if deps['ffmpeg'] else "❌"
            st.markdown(f"**FFmpeg** {status}")
            if not deps['ffmpeg']:
                st.caption("Required for video processing")
        
        with col2:
            status = "✅" if deps['yt-dlp'] else "❌"
            st.markdown(f"**yt-dlp** {status}")
            if not deps['yt-dlp']:
                st.caption("Required for URL downloads")
        
        with col3:
            status = "✅" if deps['ffprobe'] else "❌"
            st.markdown(f"**FFprobe** {status}")
            if not deps['ffprobe']:
                st.caption("Required for video analysis")
        
        if not all(deps.values()):
            st.warning("⚠️ Install missing dependencies for full functionality")
            st.code("""
# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg
pip install yt-dlp

# macOS
brew install ffmpeg yt-dlp
            """)
    
    st.markdown("---")
    
    # Main content - Two columns
    col_url, col_upload = st.columns(2)
    
    # ===== URL Download Section =====
    with col_url:
        st.markdown("""
        <div class="studio-card">
            <h3>🔗 Import from URL</h3>
            <p style="color: #94a3b8; font-size: 0.9rem;">
                Paste a YouTube Shorts, TikTok, or video URL
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        url_input = st.text_input(
            "Video URL",
            placeholder="https://youtube.com/shorts/...",
            key="url_input",
            label_visibility="collapsed"
        )
        
        custom_name_url = st.text_input(
            "Custom name (optional)",
            placeholder="Leave empty to use video title",
            key="custom_name_url"
        )
        
        download_btn = st.button(
            "⬇️ Download & Normalize",
            use_container_width=True,
            disabled=not deps['yt-dlp'] or not url_input,
            key="download_btn"
        )
        
        if download_btn and url_input:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(progress: float, message: str):
                progress_bar.progress(progress)
                status_text.markdown(f"**{message}**")
            
            # Download
            update_progress(0.05, "Initiating download...")
            
            name = sanitize_filename(custom_name_url) if custom_name_url else None
            success, message, raw_path = processor.download_video(
                url_input,
                output_name=name,
                progress_callback=update_progress
            )
            
            if success and raw_path:
                # Get final name
                if not name:
                    name = raw_path.stem.replace('_raw', '')
                
                # Normalize
                success, message, output_path = processor.normalize_video(
                    raw_path,
                    output_name=name,
                    progress_callback=update_progress
                )
                
                if success:
                    progress_bar.progress(1.0)
                    status_text.empty()
                    st.success(f"✅ Video imported: **{name}**")
                    
                    # Show preview
                    if output_path and output_path.exists():
                        st.video(str(output_path))
                        
                        # Show info
                        info = processor.get_video_info(output_path)
                        if info:
                            st.caption(
                                f"📐 {info.get('width', '?')}x{info.get('height', '?')} | "
                                f"🎬 {info.get('fps', '?'):.0f}fps | "
                                f"⏱️ {info.get('duration', 0):.1f}s | "
                                f"💾 {info.get('size_mb', 0):.1f}MB"
                            )
                else:
                    st.error(f"❌ Normalization failed: {message}")
            else:
                st.error(f"❌ Download failed: {message}")
    
    # ===== File Upload Section =====
    with col_upload:
        st.markdown("""
        <div class="studio-card">
            <h3>📁 Upload Video</h3>
            <p style="color: #94a3b8; font-size: 0.9rem;">
                Upload a local video file to normalize
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader(
            "Choose video file",
            type=['mp4', 'mov', 'avi', 'mkv', 'webm'],
            key="video_upload",
            label_visibility="collapsed"
        )
        
        custom_name_upload = st.text_input(
            "Custom name (optional)",
            placeholder="Leave empty to use original filename",
            key="custom_name_upload"
        )
        
        process_btn = st.button(
            "⚡ Process & Normalize",
            use_container_width=True,
            disabled=not deps['ffmpeg'] or uploaded_file is None,
            key="process_btn"
        )
        
        if process_btn and uploaded_file:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(progress: float, message: str):
                progress_bar.progress(progress)
                status_text.markdown(f"**{message}**")
            
            update_progress(0.1, "Saving uploaded file...")
            
            # Save uploaded file to temp
            original_name = Path(uploaded_file.name).stem
            name = sanitize_filename(custom_name_upload) if custom_name_upload else sanitize_filename(original_name)
            
            temp_path = temp_dir / f"{name}_raw{Path(uploaded_file.name).suffix}"
            
            with open(temp_path, 'wb') as f:
                f.write(uploaded_file.getbuffer())
            
            update_progress(0.3, "File saved, analyzing...")
            
            # Show original info
            info = processor.get_video_info(temp_path)
            if info:
                st.info(
                    f"📊 Original: {info.get('width', '?')}x{info.get('height', '?')} @ "
                    f"{info.get('fps', '?'):.1f}fps, {info.get('video_codec', '?')}"
                )
            
            # Normalize
            success, message, output_path = processor.normalize_video(
                temp_path,
                output_name=name,
                progress_callback=update_progress
            )
            
            if success:
                progress_bar.progress(1.0)
                status_text.empty()
                st.success(f"✅ Video processed: **{name}**")
                
                # Show preview
                if output_path and output_path.exists():
                    st.video(str(output_path))
                    
                    # Show info
                    info = processor.get_video_info(output_path)
                    if info:
                        st.caption(
                            f"📐 {info.get('width', '?')}x{info.get('height', '?')} | "
                            f"🎬 {info.get('fps', '?'):.0f}fps | "
                            f"⏱️ {info.get('duration', 0):.1f}s | "
                            f"💾 {info.get('size_mb', 0):.1f}MB"
                        )
            else:
                st.error(f"❌ Processing failed: {message}")
            
            # Cleanup temp
            try:
                temp_path.unlink()
            except:
                pass
    
    # ===== Normalization Settings Info =====
    st.markdown("---")
    
    with st.expander("📋 Normalization Settings", expanded=False):
        st.markdown("""
        ### Video Processing Pipeline
        
        All imported videos are automatically normalized to ensure consistent quality:
        
        | Setting | Value | Notes |
        |---------|-------|-------|
        | **Resolution** | 720×1280 | 9:16 aspect ratio (or 480×854 for lower quality sources) |
        | **Frame Rate** | 30fps CFR | Constant frame rate for AI processing |
        | **Codec** | H.264 (libx264) | Universal compatibility |
        | **Pixel Format** | yuv420p | Standard color space |
        | **Quality** | CRF 18 | High quality, reasonable file size |
        | **Audio** | AAC 192kbps | Clear audio for final output |
        
        ### FFmpeg Command (for reference):
        ```bash
        ffmpeg -i input.mp4 \\
          -vf "fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \\
          -c:v libx264 -crf 18 -preset medium \\
          -c:a aac -b:a 192k \\
          -movflags +faststart \\
          output.mp4
        ```
        """)
    
    # ===== Recent Imports =====
    st.markdown("---")
    st.markdown("### 📂 Recent Imports")
    
    # Get recent videos
    videos = sorted(source_media.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)[:6]
    
    if videos:
        cols = st.columns(3)
        for idx, video in enumerate(videos):
            with cols[idx % 3]:
                # Get thumbnail
                thumb_path = temp_dir / f"thumb_{video.stem}.png"
                if not thumb_path.exists():
                    processor.extract_first_frame(video)
                    # Move to correct location
                    src_thumb = temp_dir / f"{video.stem}_first_frame.png"
                    if src_thumb.exists():
                        src_thumb.rename(thumb_path)
                
                # Display
                st.markdown(f"""
                <div class="studio-card" style="padding: 0.75rem;">
                    <p style="margin: 0; font-weight: 500; font-size: 0.9rem;">
                        {video.stem[:25]}{'...' if len(video.stem) > 25 else ''}
                    </p>
                </div>
                """, unsafe_allow_html=True)
                
                if thumb_path.exists():
                    st.image(str(thumb_path), use_container_width=True)
                else:
                    st.video(str(video))
                
                # Info
                info = processor.get_video_info(video)
                if info:
                    st.caption(f"⏱️ {info.get('duration', 0):.1f}s")
    else:
        st.info("📭 No videos imported yet. Use the options above to add videos!")

