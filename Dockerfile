# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build CallForge UI
# ---------------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python deps
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 3: runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 voiceagent

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN mkdir -p /app/platform_data/outgoing /app/platform_data/outgoing_staging /app/chroma_data /app/asterisk-server \
    && chown -R voiceagent:voiceagent /app /home/voiceagent

COPY --chown=voiceagent:voiceagent . /app
COPY --from=web --chown=voiceagent:voiceagent /web/dist /app/web/dist

USER voiceagent

VOLUME ["/models", "/app/platform_data", "/app/chroma_data"]

EXPOSE 8080 9092-9101

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

ENTRYPOINT ["python", "main.py"]
