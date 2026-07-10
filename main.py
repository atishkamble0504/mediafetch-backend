import re
import os
import uuid
import glob
import time
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Directory used when we have to actually download + merge separate audio/video
# streams into a single playable file (needed for platforms like Instagram Reels
# that serve audio and video as two separate tracks for licensed music).
DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def cleanup_old_files(max_age_seconds: int = 1800) -> None:
    """Remove merged files older than max_age_seconds so /tmp doesn't fill up."""
    now = time.time()
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        try:
            if now - os.path.getmtime(f) > max_age_seconds:
                os.remove(f)
        except OSError:
            pass

app = FastAPI(
    title="Universal Video Downloader API",
    description="A FastAPI backend to fetch direct high-quality video links from various social media platforms using yt-dlp.",
    version="1.0.0"
)

# Enable CORS so the Android app and other clients can communicate with it
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VideoFetchRequest(BaseModel):
    url: str

class VideoFetchResponse(BaseModel):
    url: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    platform: str
    quality: Optional[str] = None

def clean_and_extract_url(text: str) -> str:
    """
    Extracts the first valid HTTP/HTTPS URL from a given text.
    This handles shares that include extra text like 'Check out this video! https://instagram.com/p/...'
    """
    url_pattern = r'https?://[^\s]+'
    match = re.search(url_pattern, text)
    if match:
        extracted_url = match.group(0)
        # Clean any trailing punctuation attached to the URL
        cleaned_url = re.sub(r'[.,;!?\)]+$', '', extracted_url)
        return cleaned_url
    return text

def detect_platform(url: str) -> str:
    """
    Helper to identify the social media platform from the URL.
    """
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"
    elif "instagram.com" in url_lower:
        return "Instagram"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        return "Facebook"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "Twitter/X"
    elif "reddit.com" in url_lower or "v.redd.it" in url_lower:
        return "Reddit"
    elif "linkedin.com" in url_lower:
        return "LinkedIn"
    elif "snapchat.com" in url_lower:
        return "Snapchat"
    elif "tiktok.com" in url_lower:
        return "TikTok"
    else:
        return "Generic Video"

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Universal Social Media Video Downloader Fetcher API is running.",
        "docs": "/docs"
    }

@app.get("/api/download")
def proxy_download(url: str):
    import urllib.request
    import urllib.parse
    from fastapi.responses import StreamingResponse
    
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter is required")
    
    decoded_url = urllib.parse.unquote(url)
    logger.info(f"Proxying download for URL: {decoded_url}")
    
    req = urllib.request.Request(
        decoded_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive"
        }
    )
    
    try:
        # Open connection once to inspect headers
        response_obj = urllib.request.urlopen(req, timeout=15)
        headers = {}
        content_length = response_obj.info().get("Content-Length")
        if content_length:
            headers["Content-Length"] = content_length
            
        def stream_video():
            try:
                with response_obj as r:
                    while True:
                        chunk = r.read(128 * 1024)  # 128 KB
                        if not chunk:
                            break
                        yield chunk
            except Exception as e:
                logger.error(f"Error streaming video chunks: {e}")
                
        return StreamingResponse(stream_video(), media_type="video/mp4", headers=headers)
    except Exception as e:
        logger.error(f"Error opening proxy connection: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to open connection to video source: {str(e)}")

@app.get("/api/local-file/{filename}")
def serve_local_file(filename: str):
    """Serves a video we merged (audio+video) server-side."""
    safe_name = os.path.basename(filename)  # prevent path traversal
    path = os.path.join(DOWNLOAD_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="Merged file not found or has expired. Please fetch the video again."
        )
    return FileResponse(path, media_type="video/mp4", filename=safe_name)


def download_and_merge(url: str, request: Request) -> str:
    """
    Used when the platform doesn't provide a single file with both audio and
    video (common on Instagram Reels with licensed music). Downloads the best
    video-only and audio-only streams and merges them with ffmpeg, then
    returns a URL pointing at our own server to fetch the merged file.
    """
    cleanup_old_files()
    file_id = uuid.uuid4().hex
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    merge_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "mweb"]}
        },
    }

    logger.info(f"No combined audio+video stream available — downloading and merging with ffmpeg for: {url}")
    with yt_dlp.YoutubeDL(merge_opts) as ydl:
        ydl.download([url])

    matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"{file_id}.*"))
    if not matches:
        raise HTTPException(status_code=500, detail="Failed to merge audio and video streams")

    final_path = matches[0]
    filename = os.path.basename(final_path)
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/api/local-file/{filename}"


@app.post("/api/fetch-video", response_model=VideoFetchResponse)
def fetch_video(request: Request, payload: VideoFetchRequest = Body(...)):
    raw_url = payload.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
        
    url = clean_and_extract_url(raw_url)
    logger.info(f"Cleaned URL: {url}")
    
    platform = detect_platform(url)
    logger.info(f"Detected platform: {platform}")

    # Configure yt-dlp options
    ydl_opts = {
        # Format selection: Prefer direct progressive mp4 files containing both audio and video
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb"]
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # If it's a playlist or multiple entries, pick the first
            if "entries" in info:
                entries = info["entries"]
                if not entries:
                    raise HTTPException(status_code=404, detail="No video entries found at the provided URL")
                info = entries[0]

            # Find a format that already has BOTH audio and video muxed together.
            # We deliberately ignore info.get("url") here, since that can point
            # to a video-only "best" pick when no muxed option exists.
            formats = info.get("formats", [])
            progressive_formats = [
                f for f in formats
                if f.get("vcodec") not in (None, "none")
                and f.get("acodec") not in (None, "none")
                and f.get("url")
            ]

            video_url: Optional[str] = None
            if progressive_formats:
                # Sort by resolution/height descending to get the best quality that still has audio
                progressive_formats.sort(key=lambda x: x.get("height", 0) or 0, reverse=True)
                video_url = progressive_formats[0]["url"]
            else:
                # Platform only offers separate audio/video tracks (common for
                # Instagram Reels with licensed music). Download + merge with ffmpeg.
                video_url = download_and_merge(url, request)

            if not video_url:
                raise HTTPException(status_code=404, detail="Could not extract a direct video stream URL from this source")

            # Wrap YouTube CDN streams in our proxy to bypass client IP lock.
            # Skip this for our own merged /api/local-file URLs — those already work directly.
            if "/api/local-file/" not in video_url and ("googlevideo.com" in video_url or platform == "YouTube"):
                import urllib.parse
                base_url = str(request.base_url).rstrip("/")
                video_url = f"{base_url}/api/download?url={urllib.parse.quote(video_url)}"
                logger.info(f"Wrapped YouTube video URL in streaming proxy: {video_url}")

            # Extract metadata safely
            title = info.get("title", "Social Media Video")
            thumbnail = info.get("thumbnail") or (info.get("thumbnails")[0].get("url") if info.get("thumbnails") else None)
            duration = info.get("duration")
            
            # Identify actual quality descriptor if present
            quality = info.get("format_note") or f"{info.get('height')}p" if info.get("height") else "Best"

            logger.info(f"Successfully extracted: '{title}' on {platform}")
            return VideoFetchResponse(
                url=video_url,
                title=title,
                thumbnail=thumbnail,
                duration=duration,
                platform=platform,
                quality=quality
            )

    except yt_dlp.utils.DownloadError as de:
        logger.error(f"yt-dlp Download Error: {str(de)}")
        raise HTTPException(
            status_code=400, 
            detail=f"Extractor failed: The link is private, invalid, or requires authentication."
        )
    except Exception as e:
        logger.error(f"Unexpected extraction error: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred during extraction: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
