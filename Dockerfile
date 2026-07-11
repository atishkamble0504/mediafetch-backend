FROM python:3.10-slim

# Prevent Python from writing pyc files to disc and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (curl to run health checks, ffmpeg for merging high quality video/audio, and nodejs/npm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py .

# Always force upgrade yt-dlp to the latest version on every deploy
RUN pip install --no-cache-dir --upgrade yt-dlp

# Expose the API port
EXPOSE 8080

# Command to run uvicorn (listening on 8080 by default)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
