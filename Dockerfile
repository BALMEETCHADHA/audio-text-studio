# Runs the whole app — backend API + the static frontend it serves — as
# one container. Works on any host that runs Docker (Render, Railway,
# Fly.io, a plain VPS). Unlike Colab, nothing here depends on a notebook
# session staying open: the link stays up until you deliberately stop the
# container, and a host restart brings it straight back.

FROM python:3.12-slim

# ffmpeg is a SYSTEM dependency (not a pip package) needed for the
# "reduce background noise" feature and for local (no-API-key)
# transcription. Installing it here means every deployment has it
# automatically — no separate "install ffmpeg yourself" step.
# tesseract-ocr lets Text -> Audio read text out of uploaded images and scanned PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy just the dependency list first so Docker can cache this layer and
# skip reinstalling everything when only application code changes.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

WORKDIR /app/backend

# Render (and most hosts) inject a PORT env var and expect the app to
# listen on it. The shell form of CMD lets ${PORT} expand at container
# start; ${PORT:-8000} falls back to 8000 for hosts that don't set it
# (e.g. running this image locally with `docker run -p 8000:8000 ...`).
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
