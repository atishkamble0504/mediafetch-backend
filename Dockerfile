FROM python:3.11-slim

WORKDIR /app

# ffmpeg is needed by yt-dlp for merging/transcoding some formats
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run / Render inject PORT; default to 8080 for local docker run
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
