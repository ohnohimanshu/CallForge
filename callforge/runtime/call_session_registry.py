"""In-memory registry for FreePBX ↔ CallForge call metadata.

FreePBX and CallForge often run on separate hosts, so shared Asterisk
filesystem paths for caller-id / handoff files do not work. Instead:

1. FreePBX dialplan POSTs caller_id keyed by CALL_UUID before AudioSocket.
2. CallForge AudioSocket looks up that caller_id when the TCP session starts.
3. On human handoff, CallForge stores the target extension; FreePBX dialplan
   GETs it after AudioSocket() returns and routes the live channel.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CallSessionMeta:
    call_uuid: str
    caller_id: str = "unknown"
    handoff_target: str = ""
    agent_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class CallSessionRegistry:
    """Thread-safe TTL map of AudioSocket call UUIDs → call metadata."""

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._sessions: dict[str, CallSessionMeta] = {}

    def _purge_unlocked(self) -> None:
        now = time.time()
        expired = [k for k, v in self._sessions.items() if now - v.updated_at > self._ttl]
        for key in expired:
            self._sessions.pop(key, None)

    def register(self, call_uuid: str, caller_id: str = "unknown", agent_id: str = "") -> CallSessionMeta:
        key = call_uuid.strip().lower()
        with self._lock:
            self._purge_unlocked()
            existing = self._sessions.get(key)
            if existing:
                if caller_id and caller_id != "unknown":
                    existing.caller_id = caller_id.strip()
                if agent_id:
                    existing.agent_id = agent_id
                existing.updated_at = time.time()
                return existing
            meta = CallSessionMeta(
                call_uuid=key,
                caller_id=(caller_id or "unknown").strip() or "unknown",
                agent_id=agent_id or "",
            )
            self._sessions[key] = meta
            return meta

    def get(self, call_uuid: str) -> Optional[CallSessionMeta]:
        key = call_uuid.strip().lower()
        with self._lock:
            self._purge_unlocked()
            return self._sessions.get(key)

    def get_caller_id(self, call_uuid: str) -> str:
        meta = self.get(call_uuid)
        if meta and meta.caller_id:
            return meta.caller_id
        return "unknown"

    def set_handoff(self, call_uuid: str, target: str) -> CallSessionMeta:
        key = call_uuid.strip().lower()
        with self._lock:
            self._purge_unlocked()
            meta = self._sessions.get(key)
            if meta is None:
                meta = CallSessionMeta(call_uuid=key)
                self._sessions[key] = meta
            meta.handoff_target = (target or "").strip()
            meta.updated_at = time.time()
            return meta

    def pop_handoff(self, call_uuid: str) -> str:
        """Return and clear handoff target (FreePBX dialplan one-shot read)."""
        key = call_uuid.strip().lower()
        with self._lock:
            self._purge_unlocked()
            meta = self._sessions.get(key)
            if not meta:
                return ""
            target = meta.handoff_target
            meta.handoff_target = ""
            meta.updated_at = time.time()
            return target

    def clear(self, call_uuid: str) -> None:
        key = call_uuid.strip().lower()
        with self._lock:
            self._sessions.pop(key, None)


# Process-wide singleton used by API, AudioSocket server, and pipeline handoff.
SESSION_REGISTRY = CallSessionRegistry()
