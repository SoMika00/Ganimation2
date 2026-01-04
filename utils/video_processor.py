"""
Video Processing Utilities
Handles video download, normalization, and frame extraction
"""

import subprocess
import os
import re
import json
from pathlib import Path
from typing import Optional, Tuple, List
import shutil


class VideoProcessor:
    """Handle video processing operations using ffmpeg and yt-dlp"""
    
    # Target specs for normalization
    TARGET_FPS = 30
    TARGET_WIDTH = 720
    TARGET_HEIGHT = 1280  # 9:16 aspect ratio for shorts
    FALLBACK_HEIGHT = 854  # For 480p width
    FALLBACK_WIDTH = 480
    
    def __init__(self, temp_dir: Path, output_dir: Path):
        self.temp_dir = Path(temp_dir)
        self.output_dir = Path(output_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def check_dependencies() -> dict:
        """Check if required tools are available"""
        deps = {'ffmpeg': False, 'yt-dlp': False, 'ffprobe': False}
        
        # Different version flags for different tools
        version_flags = {
            'ffmpeg': '-version',
            'ffprobe': '-version', 
            'yt-dlp': '--version'
        }
        
        for tool in deps.keys():
            try:
                result = subprocess.run(
                    [tool, version_flags[tool]],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                deps[tool] = result.returncode == 0
            except (subprocess.SubprocessError, FileNotFoundError):
                deps[tool] = False
        
        return deps
    
    def download_video(
        self,
        url: str,
        output_name: Optional[str] = None,
        progress_callback=None
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        Download video from URL using yt-dlp
        
        Returns:
            (success, message, output_path)
        """
        try:
            # Generate output name if not provided
            if not output_name:
                # Get video info first
                info_cmd = [
                    'yt-dlp',
                    '--dump-json',
                    '--no-download',
                    url
                ]
                
                result = subprocess.run(
                    info_cmd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode != 0:
                    return False, f"Failed to get video info: {result.stderr}", None
                
                info = json.loads(result.stdout)
                # Clean title for filename
                title = info.get('title', 'video')
                title = re.sub(r'[^\w\s-]', '', title)
                title = re.sub(r'[-\s]+', '_', title).strip('_')[:50]
                output_name = title
            
            raw_path = self.temp_dir / f"{output_name}_raw.mp4"
            
            # Download command - Force H264 codec (avoid AV1 which needs special decoder)
            download_cmd = [
                'yt-dlp',
                '-f', 'bestvideo[vcodec^=avc]+bestaudio/best[vcodec^=avc]/bestvideo+bestaudio/best',
                '--merge-output-format', 'mp4',
                '-o', str(raw_path),
                '--no-playlist',
                '--progress',
                url
            ]
            
            if progress_callback:
                progress_callback(0.1, "Starting download...")
            
            process = subprocess.Popen(
                download_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # Parse progress from output
            for line in iter(process.stdout.readline, ''):
                if '[download]' in line and '%' in line:
                    try:
                        # Extract percentage
                        match = re.search(r'(\d+\.?\d*)%', line)
                        if match and progress_callback:
                            pct = float(match.group(1)) / 100
                            progress_callback(0.1 + pct * 0.4, f"Downloading: {match.group(1)}%")
                    except:
                        pass
            
            process.wait()
            
            if process.returncode != 0 or not raw_path.exists():
                return False, "Download failed", None
            
            if progress_callback:
                progress_callback(0.5, "Download complete, normalizing...")
            
            return True, "Download successful", raw_path
            
        except subprocess.TimeoutExpired:
            return False, "Download timed out", None
        except Exception as e:
            return False, f"Download error: {str(e)}", None
    
    def get_video_info(self, video_path: Path) -> Optional[dict]:
        """Get video metadata using ffprobe"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(video_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return None
            
            data = json.loads(result.stdout)
            
            # Extract relevant info
            video_stream = next(
                (s for s in data.get('streams', []) if s['codec_type'] == 'video'),
                None
            )
            audio_stream = next(
                (s for s in data.get('streams', []) if s['codec_type'] == 'audio'),
                None
            )
            
            info = {
                'duration': float(data.get('format', {}).get('duration', 0)),
                'size_mb': int(data.get('format', {}).get('size', 0)) / (1024 * 1024),
                'format': data.get('format', {}).get('format_name', 'unknown')
            }
            
            if video_stream:
                info.update({
                    'width': int(video_stream.get('width', 0)),
                    'height': int(video_stream.get('height', 0)),
                    'fps': eval(video_stream.get('r_frame_rate', '0/1')) if '/' in str(video_stream.get('r_frame_rate', '0')) else float(video_stream.get('r_frame_rate', 0)),
                    'video_codec': video_stream.get('codec_name', 'unknown'),
                    'pix_fmt': video_stream.get('pix_fmt', 'unknown')
                })
            
            if audio_stream:
                info.update({
                    'audio_codec': audio_stream.get('codec_name', 'unknown'),
                    'sample_rate': int(audio_stream.get('sample_rate', 0)),
                    'channels': int(audio_stream.get('channels', 0))
                })
            
            return info
            
        except Exception as e:
            print(f"Error getting video info: {e}")
            return None
    
    def normalize_video(
        self,
        input_path: Path,
        output_name: str,
        progress_callback=None
    ) -> Tuple[bool, str, Optional[Path]]:
        """
        Normalize video to standard format:
        - 30fps CFR
        - 720x1280 (or 480x854 if source is lower)
        - H.264 codec
        - yuv420p pixel format
        - AAC audio
        
        Returns:
            (success, message, output_path)
        """
        try:
            # Get source info
            info = self.get_video_info(input_path)
            if not info:
                return False, "Could not read video info", None
            
            if progress_callback:
                progress_callback(0.55, "Analyzing video...")
            
            # Determine target resolution
            src_width = info.get('width', 0)
            src_height = info.get('height', 0)
            
            # Decide target based on source resolution
            if src_width >= 720:
                target_w = self.TARGET_WIDTH
                target_h = self.TARGET_HEIGHT
            else:
                target_w = self.FALLBACK_WIDTH
                target_h = self.FALLBACK_HEIGHT
            
            output_path = self.output_dir / f"{output_name}.mp4"
            
            # Build ffmpeg filter
            # Scale while maintaining aspect ratio, then pad to exact dimensions
            vf_filters = [
                f'fps={self.TARGET_FPS}',
                f'scale={target_w}:{target_h}:force_original_aspect_ratio=decrease',
                f'pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black',
                'format=yuv420p'
            ]
            
            cmd = [
                'ffmpeg',
                '-y',  # Overwrite output
                '-i', str(input_path),
                '-vf', ','.join(vf_filters),
                '-c:v', 'libx264',
                '-crf', '18',
                '-preset', 'medium',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-movflags', '+faststart',
                str(output_path)
            ]
            
            if progress_callback:
                progress_callback(0.6, "Normalizing video...")
            
            # Run ffmpeg with progress parsing
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            duration = info.get('duration', 0)
            
            for line in iter(process.stdout.readline, ''):
                if 'time=' in line and duration > 0:
                    try:
                        # Parse time from ffmpeg output
                        match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
                        if match and progress_callback:
                            h, m, s = match.groups()
                            current = int(h) * 3600 + int(m) * 60 + float(s)
                            pct = min(current / duration, 1.0)
                            progress_callback(0.6 + pct * 0.35, f"Encoding: {int(pct*100)}%")
                    except:
                        pass
            
            process.wait()
            
            if process.returncode != 0:
                return False, "Normalization failed", None
            
            if not output_path.exists():
                return False, "Output file not created", None
            
            if progress_callback:
                progress_callback(0.95, "Finalizing...")
            
            # Clean up temp file
            if input_path.parent == self.temp_dir:
                try:
                    input_path.unlink()
                except:
                    pass
            
            if progress_callback:
                progress_callback(1.0, "Complete!")
            
            return True, "Video normalized successfully", output_path
            
        except Exception as e:
            return False, f"Normalization error: {str(e)}", None
    
    def extract_frames(
        self,
        video_path: Path,
        num_frames: int = 10,
        output_dir: Optional[Path] = None
    ) -> List[Path]:
        """
        Extract frames from video at regular intervals
        
        Args:
            video_path: Path to video file
            num_frames: Number of frames to extract
            output_dir: Output directory (uses temp if not specified)
        
        Returns:
            List of paths to extracted frames
        """
        if output_dir is None:
            output_dir = self.temp_dir / f"frames_{video_path.stem}"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Clear existing frames
        for f in output_dir.glob("*.png"):
            f.unlink()
        
        try:
            info = self.get_video_info(video_path)
            if not info:
                return []
            
            duration = info.get('duration', 0)
            if duration <= 0:
                return []
            
            # Calculate frame extraction points
            fps = info.get('fps', 30)
            total_frames = int(duration * fps)
            
            if total_frames < num_frames:
                num_frames = max(1, total_frames)
            
            # Use scene detection or regular interval
            interval = duration / (num_frames + 1)
            
            frames = []
            for i in range(num_frames):
                timestamp = interval * (i + 1)
                output_path = output_dir / f"frame_{i:03d}.png"
                
                cmd = [
                    'ffmpeg',
                    '-y',
                    '-ss', str(timestamp),
                    '-i', str(video_path),
                    '-vframes', '1',
                    '-q:v', '2',
                    str(output_path)
                ]
                
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                
                if result.returncode == 0 and output_path.exists():
                    frames.append(output_path)
            
            return frames
            
        except Exception as e:
            print(f"Frame extraction error: {e}")
            return []
    
    def extract_first_frame(self, video_path: Path) -> Optional[Path]:
        """Extract the first frame of a video"""
        output_path = self.temp_dir / f"{video_path.stem}_first_frame.png"
        
        try:
            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(video_path),
                '-vframes', '1',
                '-q:v', '2',
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            
            if result.returncode == 0 and output_path.exists():
                return output_path
            
            return None
            
        except Exception as e:
            print(f"First frame extraction error: {e}")
            return None
    
    def extract_audio(self, video_path: Path, output_path: Optional[Path] = None) -> Optional[Path]:
        """Extract audio track from video"""
        if output_path is None:
            output_path = self.temp_dir / f"{video_path.stem}_audio.aac"
        
        try:
            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(video_path),
                '-vn',
                '-c:a', 'aac',
                '-b:a', '192k',
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            
            if result.returncode == 0 and output_path.exists():
                return output_path
            
            return None
            
        except Exception as e:
            print(f"Audio extraction error: {e}")
            return None
    
    def combine_video_audio(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path
    ) -> Tuple[bool, str]:
        """Combine video with audio track"""
        try:
            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(video_path),
                '-i', str(audio_path),
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-shortest',
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            
            if result.returncode == 0 and output_path.exists():
                return True, "Combined successfully"
            
            return False, f"FFmpeg error: {result.stderr.decode()}"
            
        except Exception as e:
            return False, f"Combine error: {str(e)}"


def sanitize_filename(name: str) -> str:
    """Clean a string for use as filename"""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'[\s]+', '_', name)
    name = name.strip('._')
    return name[:100] if name else 'unnamed'

