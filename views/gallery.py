"""
Gallery Page
Browse and manage all media: source videos, generated images, generated videos
"""

import streamlit as st
from pathlib import Path
import os
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.video_processor import VideoProcessor


def render():
    """Render the gallery page"""
    
    st.markdown("""
    <h1 class="main-title">🖼️ Gallery</h1>
    <p class="subtitle">Browse and manage your media library</p>
    """, unsafe_allow_html=True)
    
    # Initialize paths
    gallery_root = Path(__file__).parent.parent / "gallery"
    source_media = gallery_root / "source_media"
    generated_images = gallery_root / "generated_images"
    generated_videos = gallery_root / "generated_videos"
    temp_dir = Path(__file__).parent.parent / "temp"
    
    processor = VideoProcessor(temp_dir, source_media)
    
    # Tabs for different media types
    tab_source, tab_images, tab_videos = st.tabs([
        "📥 Source Media",
        "🎨 Generated Images", 
        "🎬 Generated Videos"
    ])
    
    # ===== Source Media Tab =====
    with tab_source:
        st.markdown("### Source Videos")
        st.caption("Original and normalized videos imported via ingestion")
        
        videos = sorted(
            source_media.glob("*.mp4"), 
            key=lambda x: x.stat().st_mtime, 
            reverse=True
        )
        
        if videos:
            # View controls
            col_view, col_sort, col_search = st.columns([1, 1, 2])
            with col_view:
                view_mode = st.selectbox(
                    "View",
                    ["Grid", "List"],
                    key="source_view",
                    label_visibility="collapsed"
                )
            with col_sort:
                sort_by = st.selectbox(
                    "Sort",
                    ["Newest", "Oldest", "Name A-Z", "Name Z-A"],
                    key="source_sort",
                    label_visibility="collapsed"
                )
            with col_search:
                search = st.text_input(
                    "Search",
                    placeholder="🔍 Search videos...",
                    key="source_search",
                    label_visibility="collapsed"
                )
            
            # Apply search filter
            if search:
                videos = [v for v in videos if search.lower() in v.stem.lower()]
            
            # Apply sorting
            if sort_by == "Oldest":
                videos = sorted(videos, key=lambda x: x.stat().st_mtime)
            elif sort_by == "Name A-Z":
                videos = sorted(videos, key=lambda x: x.stem.lower())
            elif sort_by == "Name Z-A":
                videos = sorted(videos, key=lambda x: x.stem.lower(), reverse=True)
            
            if view_mode == "Grid":
                # Grid view
                cols_per_row = 4
                for i in range(0, len(videos), cols_per_row):
                    cols = st.columns(cols_per_row)
                    for j, col in enumerate(cols):
                        if i + j < len(videos):
                            video = videos[i + j]
                            with col:
                                render_video_card(video, processor, temp_dir)
            else:
                # List view
                for video in videos:
                    render_video_row(video, processor)
        else:
            st.info("📭 No source videos yet. Go to **Ingestion** to import videos!")
    
    # ===== Generated Images Tab =====
    with tab_images:
        st.markdown("### Generated Images")
        st.caption("Ghibli-style frames generated from your videos")
        
        images = sorted(
            generated_images.glob("*.png"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        if images:
            # View controls
            col_view, col_search = st.columns([1, 3])
            with col_view:
                cols_img = st.selectbox(
                    "Columns",
                    [3, 4, 5, 6],
                    index=1,
                    key="img_cols"
                )
            with col_search:
                search_img = st.text_input(
                    "Search",
                    placeholder="🔍 Search images...",
                    key="img_search",
                    label_visibility="collapsed"
                )
            
            if search_img:
                images = [img for img in images if search_img.lower() in img.stem.lower()]
            
            # Display grid
            for i in range(0, len(images), cols_img):
                cols = st.columns(cols_img)
                for j, col in enumerate(cols):
                    if i + j < len(images):
                        img = images[i + j]
                        with col:
                            st.image(str(img), use_container_width=True)
                            st.caption(img.stem[:20] + ('...' if len(img.stem) > 20 else ''))
                            
                            # Actions
                            col_a, col_b = st.columns(2)
                            with col_a:
                                if st.button("🎬", key=f"use_img_{img.stem}", help="Use in Video Studio"):
                                    st.session_state.selected_image_for_video = str(img)
                                    st.session_state.current_page = 'video_studio'
                                    st.rerun()
                            with col_b:
                                if st.button("🗑️", key=f"del_img_{img.stem}", help="Delete"):
                                    try:
                                        img.unlink()
                                        st.rerun()
                                    except:
                                        st.error("Failed to delete")
        else:
            st.info("📭 No generated images yet. Go to **Image Studio** to create Ghibli frames!")
    
    # ===== Generated Videos Tab =====
    with tab_videos:
        st.markdown("### Generated Videos")
        st.caption("AI-animated videos with style transfer")
        
        gen_videos = sorted(
            generated_videos.glob("*.mp4"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        if gen_videos:
            for i in range(0, len(gen_videos), 3):
                cols = st.columns(3)
                for j, col in enumerate(cols):
                    if i + j < len(gen_videos):
                        video = gen_videos[i + j]
                        with col:
                            st.video(str(video))
                            st.markdown(f"**{video.stem[:25]}**")
                            
                            info = processor.get_video_info(video)
                            if info:
                                st.caption(
                                    f"⏱️ {info.get('duration', 0):.1f}s | "
                                    f"💾 {info.get('size_mb', 0):.1f}MB"
                                )
                            
                            col_a, col_b = st.columns(2)
                            with col_a:
                                # Download button
                                with open(video, 'rb') as f:
                                    st.download_button(
                                        "⬇️",
                                        f,
                                        file_name=video.name,
                                        mime="video/mp4",
                                        key=f"dl_{video.stem}",
                                        help="Download"
                                    )
                            with col_b:
                                if st.button("🗑️", key=f"del_vid_{video.stem}", help="Delete"):
                                    try:
                                        video.unlink()
                                        st.rerun()
                                    except:
                                        st.error("Failed to delete")
        else:
            st.info("📭 No generated videos yet. Go to **Video Studio** to create animations!")
    
    # ===== Storage Info =====
    st.markdown("---")
    
    with st.expander("💾 Storage Info"):
        col1, col2, col3 = st.columns(3)
        
        def get_dir_size(path: Path) -> float:
            total = 0
            for f in path.glob("*"):
                if f.is_file():
                    total += f.stat().st_size
            return total / (1024 * 1024)  # MB
        
        with col1:
            size = get_dir_size(source_media)
            count = len(list(source_media.glob("*.mp4")))
            st.metric("Source Media", f"{count} files", f"{size:.1f} MB")
        
        with col2:
            size = get_dir_size(generated_images)
            count = len(list(generated_images.glob("*.png")))
            st.metric("Generated Images", f"{count} files", f"{size:.1f} MB")
        
        with col3:
            size = get_dir_size(generated_videos)
            count = len(list(generated_videos.glob("*.mp4")))
            st.metric("Generated Videos", f"{count} files", f"{size:.1f} MB")
        
        # Cleanup temp
        temp_size = get_dir_size(temp_dir)
        if temp_size > 100:  # More than 100MB
            st.warning(f"⚠️ Temp folder has {temp_size:.0f}MB of data")
            if st.button("🧹 Clean Temp Folder"):
                for f in temp_dir.glob("*"):
                    try:
                        if f.is_file():
                            f.unlink()
                    except:
                        pass
                st.success("Temp folder cleaned!")
                st.rerun()


def render_video_card(video: Path, processor: VideoProcessor, temp_dir: Path):
    """Render a video card in grid view"""
    # Get or create thumbnail
    thumb_path = temp_dir / f"thumb_{video.stem}.png"
    
    if not thumb_path.exists():
        first_frame = processor.extract_first_frame(video)
        if first_frame and first_frame.exists():
            try:
                first_frame.rename(thumb_path)
            except:
                pass
    
    # Card container
    with st.container():
        if thumb_path.exists():
            st.image(str(thumb_path), use_container_width=True)
        else:
            st.video(str(video))
        
        st.markdown(f"**{video.stem[:18]}**{'...' if len(video.stem) > 18 else ''}")
        
        info = processor.get_video_info(video)
        if info:
            st.caption(f"⏱️ {info.get('duration', 0):.1f}s")
        
        # Actions row
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🎨", key=f"to_img_{video.stem}", help="Generate Image"):
                st.session_state.selected_video = str(video)
                st.session_state.current_page = 'image_studio'
                st.rerun()
        with col2:
            if st.button("✏️", key=f"rename_{video.stem}", help="Rename"):
                st.session_state[f"renaming_{video.stem}"] = True
                st.rerun()
        with col3:
            if st.button("🗑️", key=f"del_{video.stem}", help="Delete"):
                try:
                    video.unlink()
                    if thumb_path.exists():
                        thumb_path.unlink()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
        
        # Rename dialog
        if st.session_state.get(f"renaming_{video.stem}", False):
            new_name = st.text_input(
                "New name",
                value=video.stem,
                key=f"new_name_{video.stem}"
            )
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("💾", key=f"save_rename_{video.stem}"):
                    if new_name and new_name != video.stem:
                        new_path = video.parent / f"{new_name}.mp4"
                        try:
                            video.rename(new_path)
                            st.session_state[f"renaming_{video.stem}"] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
            with col_cancel:
                if st.button("❌", key=f"cancel_rename_{video.stem}"):
                    st.session_state[f"renaming_{video.stem}"] = False
                    st.rerun()


def render_video_row(video: Path, processor: VideoProcessor):
    """Render a video in list view"""
    col_vid, col_info, col_actions = st.columns([2, 2, 1])
    
    with col_vid:
        st.video(str(video))
    
    with col_info:
        st.markdown(f"### {video.stem}")
        
        info = processor.get_video_info(video)
        if info:
            st.markdown(f"""
            - **Resolution:** {info.get('width', '?')}×{info.get('height', '?')}
            - **Duration:** {info.get('duration', 0):.1f} seconds
            - **FPS:** {info.get('fps', '?'):.0f}
            - **Codec:** {info.get('video_codec', '?')}
            - **Size:** {info.get('size_mb', 0):.1f} MB
            """)
        
        # File info
        mtime = datetime.fromtimestamp(video.stat().st_mtime)
        st.caption(f"Imported: {mtime.strftime('%Y-%m-%d %H:%M')}")
    
    with col_actions:
        if st.button("🎨 Generate Image", key=f"list_img_{video.stem}", use_container_width=True):
            st.session_state.selected_video = str(video)
            st.session_state.current_page = 'image_studio'
            st.rerun()
        
        if st.button("🎬 Animate", key=f"list_vid_{video.stem}", use_container_width=True):
            st.session_state.selected_video = str(video)
            st.session_state.current_page = 'video_studio'
            st.rerun()
        
        if st.button("🗑️ Delete", key=f"list_del_{video.stem}", use_container_width=True):
            try:
                video.unlink()
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
    
    st.markdown("---")

