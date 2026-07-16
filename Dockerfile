# Acoustic Analyzer — DSP tool service (FastAPI over the DSP tools).
# Multi-arch (arm64 for the Jetson, amd64 for a dev box).
FROM python:3.11-slim

# Runtime system libs: PortAudio for sounddevice, libsndfile for wav I/O.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libportaudio2 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY src/ ./src/
ENV PYTHONPATH=/app/src

EXPOSE 8000
# ACOUSTIC_DEMO=1 (set in compose) -> works with no microphone.
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000"]
