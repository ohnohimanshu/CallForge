#!/bin/bash
set -e

# ==============================================================================
# CallForge Docker Entrypoint Script
# Prepares directories, fixes shared volume permissions, and launches the runtime
# ==============================================================================

# Ensure all runtime directory hierarchies exist
mkdir -p /app/platform_data/outgoing \
         /app/platform_data/outgoing_staging \
         /app/platform_data/voice_samples \
         /app/platform_data/recordings \
         /app/platform_data/uploads \
         /app/platform_data/freepbx \
         /app/chroma_data \
         /app/asterisk-server/calls \
         /app/asterisk-server/handoff \
         /models/piper \
         /home/voiceagent/.cache

# If run as root (default in Docker without user namespace remap):
# Ensure shared host-mounted volumes are writable by voiceagent (UID 1000).
# FreePBX Method 1 needs no shared Asterisk filesystem — only TCP AudioSocket + HTTP.
if [ "$(id -u)" = '0' ]; then
    chmod -R 777 /app/platform_data \
                 /app/chroma_data \
                 /app/asterisk-server \
                 /home/voiceagent/.cache 2>/dev/null || true

    chown -R voiceagent:voiceagent /app/platform_data \
                                   /app/chroma_data \
                                   /home/voiceagent 2>/dev/null || true

    # Step down to non-privileged voiceagent user
    if command -v gosu >/dev/null 2>&1; then
        exec gosu voiceagent "$@"
    elif command -v su-exec >/dev/null 2>&1; then
        exec su-exec voiceagent "$@"
    else
        exec su -s /bin/bash voiceagent -c "$*"
    fi
fi

# If already running as non-root user, execute directly
exec "$@"
