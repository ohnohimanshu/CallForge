"""
processing/audio_buffer.py
===========================
Sample-rate conversion, ring buffering, and PCM<->float32 normalization.

Architectural decision:
    Resampling is implemented with `scipy.signal.resample_poly`, which is
    both fast enough for real-time 20ms frames and dependency-light (no
    need for `torchaudio`/`librosa` in the hot audio path). All conversion
    helpers are pure functions with no shared state, so they're trivially
    unit-testable and safe to call concurrently from many sessions.

    `PreSpeechRingBuffer` retains a fixed-duration tail of recent audio so
    that when VAD confirms speech has started, we can prepend the audio
    that occurred just *before* the detector crossed its threshold —
    without this, the first phoneme of every utterance gets clipped.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np
from scipy.signal import resample_poly

PCM_DTYPE = np.int16


def pcm16_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert little-endian 16-bit signed PCM bytes to a float32 array in [-1.0, 1.0]."""
    samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
    return samples / 32768.0


def float32_to_pcm16_bytes(samples: np.ndarray) -> bytes:
    """Convert a float32 array in [-1.0, 1.0] to little-endian 16-bit signed PCM bytes."""
    clipped = np.clip(samples, -1.0, 1.0)
    ints = (clipped * 32767.0).astype("<i2")
    return ints.tobytes()


def resample_pcm16(pcm_bytes: bytes, from_hz: int, to_hz: int) -> bytes:
    """
    Resample raw 16-bit PCM audio between two sample rates using a
    polyphase filter (high quality, no external process required).

    Returns an empty bytes object for empty input rather than raising,
    since silence/empty frames are common at stream boundaries.
    """
    if from_hz == to_hz or len(pcm_bytes) == 0:
        return pcm_bytes
    samples = np.frombuffer(pcm_bytes, dtype="<i2")
    # resample_poly wants a rational up/down ratio; reduce it for efficiency.
    from math import gcd

    divisor = gcd(from_hz, to_hz)
    up, down = to_hz // divisor, from_hz // divisor
    resampled = resample_poly(samples.astype(np.float32), up, down)
    resampled = np.clip(resampled, -32768, 32767)
    return resampled.astype("<i2").tobytes()


class PreSpeechRingBuffer:
    """
    Fixed-duration ring buffer of raw PCM frames, used to retain audio
    immediately preceding a VAD-confirmed speech onset.
    """

    def __init__(self, sample_rate_hz: int, frame_bytes: int, padding_ms: int) -> None:
        bytes_per_ms = (sample_rate_hz * 2) // 1000  # 2 bytes/sample, mono
        target_bytes = bytes_per_ms * padding_ms
        max_frames = max(1, target_bytes // max(frame_bytes, 1))
        self._buffer: Deque[bytes] = deque(maxlen=max_frames)

    def push(self, frame: bytes) -> None:
        """Add a frame, evicting the oldest if at capacity."""
        self._buffer.append(frame)

    def drain(self) -> bytes:
        """Return and clear all buffered pre-speech audio, concatenated in order."""
        audio = b"".join(self._buffer)
        self._buffer.clear()
        return audio

    def __len__(self) -> int:
        return len(self._buffer)


class UtteranceAccumulator:
    """
    Accumulates raw PCM bytes for a single in-progress speech utterance,
    with a hard cap to force end-of-turn on run-on speech (e.g. a caller
    who never pauses).
    """

    def __init__(self, sample_rate_hz: int, max_duration_ms: int) -> None:
        bytes_per_ms = (sample_rate_hz * 2) // 1000
        self._max_bytes = bytes_per_ms * max_duration_ms
        self._chunks: list[bytes] = []
        self._total_bytes = 0

    def append(self, pcm_bytes: bytes) -> None:
        self._chunks.append(pcm_bytes)
        self._total_bytes += len(pcm_bytes)

    def is_full(self) -> bool:
        """True once the accumulated audio has hit the hard duration cap."""
        return self._total_bytes >= self._max_bytes

    def finalize(self) -> bytes:
        """Return the concatenated utterance audio and reset internal state."""
        audio = b"".join(self._chunks)
        self._chunks.clear()
        self._total_bytes = 0
        return audio

    def duration_ms(self, sample_rate_hz: int) -> float:
        """Current accumulated duration in milliseconds."""
        bytes_per_ms = (sample_rate_hz * 2) // 1000
        return self._total_bytes / bytes_per_ms if bytes_per_ms else 0.0

    def __len__(self) -> int:
        return self._total_bytes
