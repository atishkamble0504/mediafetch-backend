import re
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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
    po_token: Optional[str] = None
    visitor_data: Optional[str] = None

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

def fetch_via_cobalt_fallback(target_url: str) -> Optional[Dict[str, Any]]:
    import urllib.request
    import urllib.error
    import json
    
    # List of public, highly resilient, active cobalt instances
    # Using these ensures that if the server fails, we safely route through free, non-cookie public APIs.
    cobalt_instances = [
        "https://api.cobalt.liubquanti.click",
        "https://rue-cobalt.xenon.zone",
        "https://dog.kittycat.boo",
        "https://api.cobalt.tools",
        "https://api.cobalt.best",
    ]
    
    payload = {
        "url": target_url,
        "videoQuality": "1080"
    }
    
    data_bytes = json.dumps(payload).encode("utf-8")
    
    for instance in cobalt_instances:
        for endpoint in [instance, f"{instance}/api/json"]:
            logger.info(f"Attempting fallback to Cobalt instance: {endpoint}")
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=data_bytes,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=12) as response:
                    resp_data = json.loads(response.read().decode("utf-8"))
                    status = resp_data.get("status")
                    video_url = resp_data.get("url")
                    title = resp_data.get("filename") or resp_data.get("text") or "Video Download"
                    
                    if video_url and status in ["redirect", "stream", "success", "tunnel"]:
                        logger.info(f"Successfully fetched video link from Cobalt fallback: {video_url}")
                        return {
                            "url": video_url,
                            "title": title,
                            "thumbnail": None,
                            "duration": None,
                            "quality": "Best (Cobalt Fallback)"
                        }
            except Exception as e:
                logger.warning(f"Cobalt instance {endpoint} failed: {e}")
                
    return None

# No cookies file setup function. All user session cookies have been completely removed 
# to keep the developer's and users' Google/YouTube accounts 100% secure.

@app.post("/api/fetch-video", response_model=VideoFetchResponse)
def fetch_video(request: Request, payload: VideoFetchRequest = Body(...)):
    import os
    import uuid
    import time
    import threading
    from fastapi.responses import FileResponse

    # Ensure downloads directory exists
    DOWNLOAD_DIR = "/tmp/downloads"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Helper for server-side downloading and merging
    def download_and_merge_video(target_url: str, video_platform: str, api_base_url: str) -> Optional[VideoFetchResponse]:
        unique_id = str(uuid.uuid4())
        filename = f"{unique_id}.mp4"
        output_path = os.path.join(DOWNLOAD_DIR, filename)
        
        ydl_opts = {
            # Bounded quality to 1080p to keep merges fast and reliable on limited CPU
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(DOWNLOAD_DIR, f"{unique_id}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
        }
        
        if video_platform == "YouTube":
            ydl_opts["extractor_args"] = {
                "youtube": {
                    "player_client": ["ios", "tvhtml5", "mweb"]
                }
            }
            # Access dynamic PO_TOKEN and VISITOR_DATA supplied by payload, falling back to environment
            po_token = payload.po_token or os.environ.get("PO_TOKEN")
            visitor_data = payload.visitor_data or os.environ.get("VISITOR_DATA")
            if po_token and visitor_data:
                ydl_opts["extractor_args"]["youtube"]["po_token"] = [po_token]
                ydl_opts["extractor_args"]["youtube"]["visitor_data"] = [visitor_data]
                logger.info("Using supplied visitor_data and po_token for YouTube video download and merge.")
            
        try:
            logger.info(f"Downloading and merging video server-side to {output_path}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
                
                if "entries" in info:
                    entries = info["entries"]
                    if not entries:
                        return None
                    info = entries[0]
                    
                title = info.get("title", "Merged Video")
                thumbnail = info.get("thumbnail") or (info.get("thumbnails")[0].get("url") if info.get("thumbnails") else None)
                duration = info.get("duration")
                quality = info.get("format_note") or f"{info.get('height')}p" if info.get("height") else "1080p (Merged)"
                
                if os.path.exists(output_path):
                    video_url = f"{api_base_url}/api/local-file/{filename}"
                    logger.info(f"Successfully downloaded and merged to {video_url}")
                    return VideoFetchResponse(
                        url=video_url,
                        title=title,
                        thumbnail=thumbnail,
                        duration=duration,
                        platform=video_platform,
                        quality=quality
                    )
                else:
                    for f in os.listdir(DOWNLOAD_DIR):
                        if f.startswith(unique_id):
                            actual_filename = f
                            video_url = f"{api_base_url}/api/local-file/{actual_filename}"
                            logger.info(f"Found non-mp4 merged file {actual_filename}, serving via local-file")
                            return VideoFetchResponse(
                                url=video_url,
                                title=title,
                                thumbnail=thumbnail,
                                duration=duration,
                                platform=video_platform,
                                quality=quality
                            )
        except Exception as e:
            logger.error(f"Failed server-side download and merge: {e}")
            
        return None

    raw_url = payload.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
        
    url = clean_and_extract_url(raw_url)
    logger.info(f"Cleaned URL: {url}")
    
    platform = detect_platform(url)
    logger.info(f"Detected platform: {platform}")

    # Dynamic PO_TOKEN and VISITOR_DATA supplied by payload or environment
    po_token = payload.po_token or os.environ.get("PO_TOKEN")
    visitor_data = payload.visitor_data or os.environ.get("VISITOR_DATA")

    # Configure multiple yt-dlp options to try sequentially for YouTube
    ydl_configs = [
        # Attempt 1: Modern tvhtml5 client (extremely resilient to bot checks)
        {
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["tvhtml5"]
                }
            }
        },
        # Attempt 2: Combo of ios, tvhtml5, and mweb
        {
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["ios", "tvhtml5", "mweb"]
                }
            }
        },
        # Attempt 3: android and web_embedded
        {
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web_embedded"]
                }
            }
        }
    ]

    # For non-YouTube platforms, we only need one simple configuration
    if platform != "YouTube":
        ydl_configs = [{
            "format": "best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }]
    else:
        # Inject dynamic or environment PO_TOKEN/VISITOR_DATA into youtube extractor_args
        if po_token and visitor_data:
            logger.info("Injecting supplied PO_TOKEN and VISITOR_DATA into yt-dlp extractor args.")
            for cfg in ydl_configs:
                if "extractor_args" in cfg and "youtube" in cfg["extractor_args"]:
                    cfg["extractor_args"]["youtube"]["po_token"] = [po_token]
                    cfg["extractor_args"]["youtube"]["visitor_data"] = [visitor_data]

    last_error_msg = ""
    base_url = str(request.base_url).rstrip("/")
    
    # Try all yt-dlp configurations
    for idx, config in enumerate(ydl_configs):
        logger.info(f"Trying yt-dlp configuration attempt {idx+1}/{len(ydl_configs)}")
        try:
            with yt_dlp.YoutubeDL(config) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # If it's a playlist or multiple entries, pick the first
                if "entries" in info:
                    entries = info["entries"]
                    if not entries:
                        raise ValueError("No video entries found at the provided URL")
                    info = entries[0]

                # Direct video URL extraction
                video_url = info.get("url")
                
                # If direct URL is missing, search formats for the best playable video stream
                if not video_url:
                    formats = info.get("formats", [])
                    # Filter formats with both audio and video
                    progressive_formats = [
                        f for f in formats 
                        if f.get("vcodec") != "none" and f.get("acodec") != "none" and f.get("url")
                    ]
                    if progressive_formats:
                        progressive_formats.sort(key=lambda x: x.get("height", 0) or 0, reverse=True)
                        video_url = progressive_formats[0]["url"]
                    elif formats:
                        # If no progressive format found, but formats are available, this could be separate audio/video!
                        # Skip direct extraction and fallback to download_and_merge_video
                        logger.info("No progressive formats found in direct extraction, skipping to server-side merge.")
                        break

                if not video_url:
                    raise ValueError("Could not extract a direct video stream URL from this source")

                # Wrap YouTube streams in proxy to bypass client IP lock
                if "googlevideo.com" in video_url or platform == "YouTube":
                    import urllib.parse
                    video_url = f"{base_url}/api/download?url={urllib.parse.quote(video_url)}"
                    logger.info(f"Wrapped YouTube video URL in streaming proxy: {video_url}")

                # Extract metadata safely
                title = info.get("title", "Social Media Video")
                thumbnail = info.get("thumbnail") or (info.get("thumbnails")[0].get("url") if info.get("thumbnails") else None)
                duration = info.get("duration")
                quality = info.get("format_note") or f"{info.get('height')}p" if info.get("height") else "Best"

                logger.info(f"Successfully extracted: '{title}' on {platform} via yt-dlp config {idx+1}")
                return VideoFetchResponse(
                    url=video_url,
                    title=title,
                    thumbnail=thumbnail,
                    duration=duration,
                    platform=platform,
                    quality=quality
                )
        except Exception as e:
            last_error_msg = str(e)
            logger.warning(f"yt-dlp attempt {idx+1} failed: {last_error_msg}")

    # Fallback to server-side downloading and merging
    logger.info(f"Direct extraction failed or was incomplete. Attempting server-side download and merge for {platform}...")
    merged_response = download_and_merge_video(url, platform, base_url)
    if merged_response:
        return merged_response

    # Fallback to Cobalt Public API instances
    logger.info("yt-dlp and merging failed. Trying Cobalt Public API instances...")
    cobalt_res = fetch_via_cobalt_fallback(url)
    if cobalt_res:
        return VideoFetchResponse(
            url=cobalt_res["url"],
            title=cobalt_res["title"],
            thumbnail=cobalt_res["thumbnail"],
            duration=cobalt_res["duration"],
            platform=platform,
            quality=cobalt_res["quality"]
        )

    # Fallback to pytubefix for YouTube if yt-dlp failed completely
    if platform == "YouTube":
        logger.info("yt-dlp and merging failed. Falling back to pytubefix...")
        pytube_clients = ["TV", "WEB", "IOS", "MWEB"]
        for client_name in pytube_clients:
            logger.info(f"Trying pytubefix with client='{client_name}'")
            try:
                from pytubefix import YouTube as PytubeVideo
                try:
                    yt = PytubeVideo(url, client=client_name)
                except TypeError:
                    # Fallback if the local pytubefix version doesn't accept client parameter
                    yt = PytubeVideo(url)
                
                # Get progressive mp4 formats
                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
                if not stream:
                    stream = yt.streams.filter(file_extension='mp4').order_by('resolution').desc().first()
                
                if stream and stream.url:
                    video_url = stream.url
                    import urllib.parse
                    video_url = f"{base_url}/api/download?url={urllib.parse.quote(video_url)}"
                    
                    title = yt.title or "YouTube Video"
                    thumbnail = yt.thumbnail_url
                    duration = yt.length
                    
                    logger.info(f"Successfully extracted: '{title}' on YouTube via pytubefix (client: {client_name})")
                    return VideoFetchResponse(
                        url=video_url,
                        title=title,
                        thumbnail=thumbnail,
                        duration=duration,
                        platform=platform,
                        quality=stream.resolution or "Best"
                    )
            except Exception as py_err:
                last_error_msg = str(py_err)
                logger.warning(f"pytubefix with client {client_name} failed: {last_error_msg}")

    # If all attempts failed
    logger.error(f"All extraction attempts failed. Last error: {last_error_msg}")
    raise HTTPException(
        status_code=400,
        detail=f"Extraction failed: The video link is private, invalid, or requires authentication. (Details: {last_error_msg})"
    )

# Download and merged local file server route
@app.get("/api/local-file/{filename}")
def get_local_file(filename: str):
    import os
    DOWNLOAD_DIR = "/tmp/downloads"
    if ".." in filename or filename.startswith("/") or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
        
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found or expired")
        
    return FileResponse(file_path, media_type="video/mp4", filename=filename)

# Background file cleanup routine
def cleanup_old_files():
    import os
    import time
    DOWNLOAD_DIR = "/tmp/downloads"
    while True:
        try:
            now = time.time()
            if os.path.exists(DOWNLOAD_DIR):
                for f in os.listdir(DOWNLOAD_DIR):
                    file_path = os.path.join(DOWNLOAD_DIR, f)
                    if os.path.isfile(file_path):
                        # Delete files older than 30 minutes (1800 seconds)
                        if now - os.path.getmtime(file_path) > 1800:
                            os.remove(file_path)
                            logger.info(f"Cleaned up expired local file: {f}")
        except Exception as e:
            logger.error(f"Error in cleanup thread: {e}")
        time.sleep(300) # Run every 5 minutes

# Start the background file-cleaner daemon thread
import threading
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
