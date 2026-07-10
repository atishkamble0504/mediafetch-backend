# Universal Video Downloader Backend API

This is a high-performance Python FastAPI service that extracts direct high-quality video stream links, titles, and thumbnails from popular social media platforms. It utilizes `yt-dlp` under the hood.

## Supported Platforms
- YouTube & Shorts
- Instagram (Reels & Posts)
- Facebook & Watch
- Twitter / X
- Reddit
- LinkedIn
- Snapchat
- Generic Direct MP4/HLS URLs

---

## Getting Started

### Method 1: Local Installation (Python)

1. Make sure you have Python 3.9+ installed on your system.
2. Navigate to the backend directory and install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the FastAPI application using Uvicorn:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

The server will be available at `http://localhost:8000`. You can access interactive API documentation at `http://localhost:8000/docs`.

---

### Method 2: Docker Deployment

You can build and run the backend inside a lightweight Docker container.

1. Build the Docker image:
   ```bash
   docker build -t video-downloader-api .
   ```
2. Run the Docker container:
   ```bash
   docker run -d -p 8000:8000 --name video-downloader-api video-downloader-api
   ```

---

## API Endpoints

### 1. Root Status
- **URL:** `/`
- **Method:** `GET`
- **Response:**
  ```json
  {
    "status": "online",
    "message": "Universal Social Media Video Downloader Fetcher API is running."
  }
  ```

### 2. Fetch Video Metadata & Direct Link
- **URL:** `/api/fetch-video`
- **Method:** `POST`
- **Headers:** `Content-Type: application/json`
- **Request Body:**
  ```json
  {
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  }
  ```
- **Response:**
  ```json
  {
    "url": "https://rr3---sn-u5a7zn7e.googlevideo.com/videoplayback?...",
    "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "duration": 212,
    "platform": "YouTube",
    "quality": "720p"
  }
  ```
