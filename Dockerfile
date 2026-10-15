# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build CallForge UI (React + Tailwind + Vite)
# ---------------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python builder with CPU PyTorch
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Pre-install CPU-only PyTorch and modern wheel build tools.
# This prevents pip from downloading ~3.5GB of unused CUDA/NVIDIA libraries,
# drastically speeding up Docker builds and shrinking the image footprint.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchaudio

COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 3: runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libsndfile1 \
        ffmpeg \
        curl \
        gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash voiceagent

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Pre-create all required directory hierarchies and ensure proper initial ownership
# FreePBX Method 1: CallForge exposes AudioSocket TCP + HTTP session/handoff APIs.
# FreePBX dialplan snippets are written under platform_data/freepbx/.
RUN mkdir -p /app/platform_data/outgoing \
             /app/platform_data/outgoing_staging \
             /app/platform_data/voice_samples \
             /app/platform_data/recordings \
             /app/platform_data/uploads \
             /app/platform_data/freepbx \
             /app/chroma_data \
             /app/asterisk-server/calls \
             /app/asterisk-server/handoff \
             /models/piper \
             /home/voiceagent/.cache \
    && chown -R voiceagent:voiceagent /app /home/voiceagent /models

COPY --chown=voiceagent:voiceagent . /app
COPY --from=web --chown=voiceagent:voiceagent /web/dist /app/web/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080 9092-9101

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "main.py"]
