
"""
🎬 Ganimation Studio
AI-Powered Video Editing Platform
Transform your shorts into Ghibli-style animations
"""

import streamlit as st
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Page config must be first Streamlit command
st.set_page_config(
    page_title="Ganimation Studio",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for professional look
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    
    /* Main theme */
    :root {
        --bg-primary: #0a0a0f;
        --bg-secondary: #12121a;
        --bg-card: #1a1a24;
        --accent-primary: #6366f1;
        --accent-secondary: #8b5cf6;
        --accent-ghibli: #4ade80;
        --text-primary: #f8fafc;
        --text-secondary: #94a3b8;
        --border-color: #2d2d3a;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Main container */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #12121a 0%, #0a0a0f 100%);
        border-right: 1px solid var(--border-color);
    }
    
    [data-testid="stSidebar"] .stMarkdown {
        color: var(--text-primary);
    }
    
    /* Custom title */
    .main-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #4ade80 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
    }
    
    .subtitle {
        font-family: 'Space Grotesk', sans-serif;
        color: var(--text-secondary);
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    
    /* Cards */
    .studio-card {
        background: linear-gradient(145deg, #1a1a24 0%, #12121a 100%);
        border: 1px solid var(--border-color);
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        transition: all 0.3s ease;
    }
    
    .studio-card:hover {
        border-color: var(--accent-primary);
        box-shadow: 0 0 30px rgba(99, 102, 241, 0.15);
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
        color: white;
        border: none;
        border-radius: 12px;
        padding: 0.75rem 2rem;
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 30px rgba(99, 102, 241, 0.3);
    }
    
    /* File uploader */
    [data-testid="stFileUploader"] {
        border: 2px dashed var(--border-color);
        border-radius: 16px;
        padding: 2rem;
        background: var(--bg-card);
    }
    
    /* Text inputs */
    .stTextInput > div > div > input {
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        color: var(--text-primary);
        font-family: 'JetBrains Mono', monospace;
    }
    
    /* Selectbox */
    .stSelectbox > div > div {
        background: var(--bg-card);
        border: 1px solid var(--border-color);
        border-radius: 12px;
    }
    
    /* Progress bar */
    .stProgress > div > div > div {
        background: linear-gradient(90deg, #6366f1 0%, #4ade80 100%);
    }
    
    /* Navigation buttons in sidebar */
    .nav-button {
        display: block;
        width: 100%;
        padding: 1rem 1.5rem;
        margin: 0.5rem 0;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 12px;
        color: var(--text-secondary);
        text-align: left;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1rem;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .nav-button:hover {
        background: var(--bg-card);
        border-color: var(--border-color);
        color: var(--text-primary);
    }
    
    .nav-button.active {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.2) 0%, rgba(139, 92, 246, 0.2) 100%);
        border-color: var(--accent-primary);
        color: var(--text-primary);
    }
    
    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 500;
    }
    
    .status-ready {
        background: rgba(74, 222, 128, 0.2);
        color: #4ade80;
    }
    
    .status-processing {
        background: rgba(251, 191, 36, 0.2);
        color: #fbbf24;
    }
    
    .status-error {
        background: rgba(239, 68, 68, 0.2);
        color: #ef4444;
    }
    
    /* Gallery grid */
    .gallery-item {
        position: relative;
        border-radius: 12px;
        overflow: hidden;
        aspect-ratio: 9/16;
        background: var(--bg-card);
        border: 1px solid var(--border-color);
    }
    
    .gallery-item img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    
    /* Sliders */
    .stSlider > div > div > div {
        background: var(--accent-primary);
    }
    
    /* Expander */
    .streamlit-expanderHeader {
        background: var(--bg-card);
        border-radius: 12px;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: transparent;
    }
    
    .stTabs [data-baseweb="tab"] {
        background: var(--bg-card);
        border-radius: 12px;
        border: 1px solid var(--border-color);
        color: var(--text-secondary);
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
        color: white;
        border-color: transparent;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'current_page' not in st.session_state:
    st.session_state.current_page = 'ingestion'

if 'selected_video' not in st.session_state:
    st.session_state.selected_video = None

if 'selected_frame' not in st.session_state:
    st.session_state.selected_frame = None

# Gallery paths
GALLERY_ROOT = Path(__file__).parent / "gallery"
SOURCE_MEDIA = GALLERY_ROOT / "source_media"
GENERATED_IMAGES = GALLERY_ROOT / "generated_images"
GENERATED_VIDEOS = GALLERY_ROOT / "generated_videos"
TEMP_DIR = Path(__file__).parent / "temp"

# Ensure directories exist
for dir_path in [SOURCE_MEDIA, GENERATED_IMAGES, GENERATED_VIDEOS, TEMP_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


from api.services.gpu_manager import GPUManager


def _render_gpu_monitor():
    """Live GPU memory monitor (toggleable, polls every 5s via fragment)."""
    gpu = GPUManager()
    info = gpu.get_info()
    if info['num_gpus'] == 0:
        st.caption("💻 CPU mode")
        return
    total_alloc = sum(g['allocated_gb'] for g in info['gpus'])
    total_vram = sum(g['total_gb'] for g in info['gpus'])
    st.caption(f"🖥️ {info['num_gpus']} GPU(s) • {total_alloc:.1f}/{total_vram:.1f} GB")
    for g in info['gpus']:
        frac = g['allocated_gb'] / g['total_gb'] if g['total_gb'] > 0 else 0
        st.progress(frac, text=f"{g['name']}: {g['allocated_gb']:.1f}/{g['total_gb']:.1f} GB ({frac*100:.0f}%) util")


# Sidebar Navigation
with st.sidebar:
    st.markdown("""
    <div style="text-align: center; padding: 1rem 0 2rem 0;">
        <h1 style="font-family: 'Space Grotesk', sans-serif; 
                   font-size: 1.8rem; 
                   background: linear-gradient(135deg, #6366f1 0%, #4ade80 100%);
                   -webkit-background-clip: text;
                   -webkit-text-fill-color: transparent;
                   background-clip: text;
                   margin: 0;">
            🎬 Ganimation
        </h1>
        <p style="color: #64748b; font-size: 0.9rem; margin-top: 0.5rem;">
            AI Video Studio
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Navigation
    pages = {
        'ingestion': ('📥', 'Ingestion', 'Import & normalize videos'),
        'gallery': ('🖼️', 'Gallery', 'Browse your media'),
        'image_studio': ('🎨', 'Image Studio', 'Generate Ghibli frames'),
        'video_studio': ('🎬', 'Video Studio', 'Animate with Wan2.2'),
    }
    
    for page_id, (icon, name, desc) in pages.items():
        is_active = st.session_state.current_page == page_id
        
        if st.button(
            f"{icon}  {name}",
            key=f"nav_{page_id}",
            use_container_width=True,
            type="primary" if is_active else "secondary"
        ):
            st.session_state.current_page = page_id
            st.rerun()
        
        if is_active:
            st.caption(f"   {desc}")
    
    st.markdown("---")
    
    # Quick stats
    st.markdown("### 📊 Library Stats")
    
    source_count = len(list(SOURCE_MEDIA.glob("*.mp4")))
    img_count = len(list(GENERATED_IMAGES.glob("*.png")))
    vid_count = len(list(GENERATED_VIDEOS.glob("*.mp4")))
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Source", source_count)
    col2.metric("Images", img_count)
    col3.metric("Videos", vid_count)

    st.markdown("---")

    # Live GPU Memory Monitor (toggleable, reuses GPUManager)
    show_gpu = st.checkbox("🖥️ Live GPU Monitor", value=True, key="gpu_monitor_toggle")
    if show_gpu:
        @st.fragment(run_every=5)
        def _gpu_frag():
            _render_gpu_monitor()
        _gpu_frag()

# Main content area - Dynamic page loading
if st.session_state.current_page == 'ingestion':
    from views import ingestion
    ingestion.render()

elif st.session_state.current_page == 'gallery':
    from views import gallery
    gallery.render()

elif st.session_state.current_page == 'image_studio':
    from views import image_studio
    image_studio.render()

elif st.session_state.current_page == 'video_studio':
    from views import video_studio
    video_studio.render()

