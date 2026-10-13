"""
processing/vad.py
==================
Silero VAD wrapper implemented as an explicit state machine.

Architectural decision:
    VAD is modeled as a small explicit state machine (`VadState`) rather
    than scattered booleans, so the pipeline layer can react to clean,
    named transitions (`SPEECH_STARTED`, `SPEECH_ENDED`) instead of
    polling probability floats. The Silero model itself is loaded once
    per-process, and each `VadEngine` instance keeps its own hidden state
    so multiple concurrent calls never share model state (a common
    source of cross-call audio bleeding bugs).

    Chunking note: Silero VAD requires a minimum input length (it raises
    "Input audio chunk is too short" below roughly 32ms). AudioSocket
    delivers 20ms frames, which is below that minimum, so we cannot score
    every incoming frame directly. Instead, incoming frames are appended
    to an internal `_score_buffer`; once enough audio has accumulated to
    meet Silero's minimum chunk size, we score that chunk and cache the
    resulting probability. Turn-taking decisions (speech start/end) still
    run on every 20ms frame using the most recently computed probability,
    so control-loop granularity is unaffected — only the underlying score
    updates at a slightly coarser (~32ms) cadence.

    We score directly on the native 8kHz telephony audio rather than
    resampling to 16kHz: Silero VAD natively supports both 8kHz and
    16kHz, so scoring at 8kHz avoids a resample on every chunk (cheaper,
    and one less thing that can be misconfigured on constrained hardware).
"""

from __future__ import annotations

import enum
import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import torch

from config import VadSettings
from processing.audio_buffer import PreSpeechRingBuffer, UtteranceAccumulator, resample_pcm16

logger = logging.getLogger(__name__)

# Silero's TorchScript model raises ValueError when sample_rate / n_samples > 31.25,
# i.e. it requires at least sample_rate / 31.25 samples per call. This works out to
# 256 samples (32ms) at 8kHz or 512 samples (32ms) at 16kHz.
_SILERO_MIN_CHUNK_DIVISOR = 31.25


class VadState(enum.Enum):
    """Explicit conversational-turn states derived from frame-level VAD scores."""

    SILENCE = "silence"
    SPEECH = "speech"


class VadEventType(enum.Enum):
    """Events emitted by `VadEngine.process_frame` as speech boundaries are crossed."""

    SPEECH_STARTED = "speech_started"
    SPEECH_CONTINUING = "speech_continuing"
    SPEECH_ENDED = "speech_ended"
    NOOP = "noop"


@dataclass(frozen=True, slots=True)
class VadEvent:
    """Result of feeding one frame into the VAD engine."""

    type: VadEventType
    utterance_pcm: Optional[bytes] = None  # populated only on SPEECH_ENDED


import threading

class SileroModelPool:
    """
    Pool of Silero VAD model instances ensuring call isolation.
    Each concurrent call borrows an independent model instance so internal
    RNN hidden states and context buffers never cross-contaminate between calls.
    """

    _pool: list[torch.jit.ScriptModule] = []
    _lock = threading.Lock()

    @classmethod
    def acquire(cls) -> torch.jit.ScriptModule:
        with cls._lock:
            if cls._pool:
                model = cls._pool.pop()
                if hasattr(model, "reset_states"):
                    model.reset_states()
                return model
        from silero_vad import load_silero_vad

        logger.info("Loading Silero VAD model instance (offline)")
        model = load_silero_vad(onnx=False)
        model.eval()
        return model

    @classmethod
    def release(cls, model: Optional[torch.jit.ScriptModule]) -> None:
        if model is None:
            return
        if hasattr(model, "reset_states"):
            model.reset_states()
        with cls._lock:
            if len(cls._pool) < 8:
                cls._pool.append(model)

    @classmethod
    def get_model(cls) -> torch.jit.ScriptModule:
        """Backwards compatibility helper."""
        return cls.acquire()


class VadEngine:
    """
    Per-call Silero VAD state machine.

    Consumes raw 8kHz/16-bit PCM frames (as received over AudioSocket)
    and emits speech start/continue/end events with accumulated utterance
    audio (still at the original 8kHz, ready for STT) on end-of-turn.
    """

    def __init__(self, settings: VadSettings, source_sample_rate_hz: int, frame_bytes: int) -> None:
        self._settings = settings
        self._source_sample_rate_hz = source_sample_rate_hz
        self._model: Optional[torch.jit.ScriptModule] = SileroModelPool.acquire()
        self._hidden_state = self._model.reset_states() if hasattr(self._model, "reset_states") else None

        self._state = VadState.SILENCE
        self._silence_run_ms = 0.0
        self._pre_speech_buffer = PreSpeechRingBuffer(
            sample_rate_hz=source_sample_rate_hz, frame_bytes=frame_bytes, padding_ms=settings.pre_speech_padding_ms
        )
        self._accumulator = UtteranceAccumulator(
            sample_rate_hz=source_sample_rate_hz, max_duration_ms=settings.max_utterance_ms
        )
        self._frame_duration_ms = (frame_bytes / 2) / source_sample_rate_hz * 1000.0
        self._trailing_silence_keep_ms = settings.trailing_silence_keep_ms

        # --- VAD scoring chunk buffering (see module docstring) ---
        target_hz = settings.target_sample_rate_hz
        min_target_samples = math.ceil(target_hz / _SILERO_MIN_CHUNK_DIVISOR)
        # How many *source*-rate bytes we need buffered to produce a chunk
        # of `min_target_samples` once resampled (identity when rates match).
        min_source_samples = math.ceil(min_target_samples * source_sample_rate_hz / target_hz)
        self._score_chunk_source_bytes = min_source_samples * 2  # 16-bit samples
        self._score_buffer = bytearray()
        self._last_probability = 0.0

    @property
    def silence_run_ms(self) -> float:
        return self._silence_run_ms

    @property
    def last_probability(self) -> float:
        return self._last_probability

    def process_frame(self, pcm_frame: bytes) -> VadEvent:
        """Feed one raw 8kHz frame into the state machine and return any resulting event."""
        self._update_probability(pcm_frame)
        is_speech = self._last_probability >= self._settings.speech_threshold

        if self._state is VadState.SILENCE:
            is_speech = self._last_probability >= self._settings.speech_threshold
            # Reject low-energy frames (mic hiss, fan, breath) so background noise cannot start speech
            samples = np.frombuffer(pcm_frame, dtype="<i2").astype(np.float32)
            frame_rms = float(np.sqrt(np.mean(samples ** 2)))
            if frame_rms < 40.0:
                is_speech = False

            self._pre_speech_buffer.push(pcm_frame)
            if is_speech:
                self._state = VadState.SPEECH
                self._silence_run_ms = 0.0
                preroll = self._pre_speech_buffer.drain()
                self._accumulator.append(preroll)
                self._accumulator.append(pcm_frame)
                return VadEvent(type=VadEventType.SPEECH_STARTED)
            return VadEvent(type=VadEventType.NOOP)

        # self._state is SPEECH: use slightly lower continuation threshold (hysteresis)
        # so unvoiced consonants or brief quiet syllables don't prematurely trigger silence.
        continue_threshold = max(0.35, self._settings.speech_threshold - 0.12)
        is_speech = self._last_probability >= continue_threshold
        self._accumulator.append(pcm_frame)
        if is_speech:
            self._silence_run_ms = 0.0
        else:
            self._silence_run_ms += self._frame_duration_ms

        turn_complete = self._silence_run_ms >= self._settings.min_silence_ms or self._accumulator.is_full()
        if turn_complete:
            trailing_silence_ms = self._silence_run_ms
            reason = "silence_timeout" if self._silence_run_ms >= self._settings.min_silence_ms else "max_duration_reached"
            self._state = VadState.SILENCE
            self._silence_run_ms = 0.0
            utterance = self._accumulator.finalize()
            logger.debug(
                "VAD ending turn (%s): %d bytes captured (~%.2fs), last probability=%.2f",
                reason, len(utterance), len(utterance) / (self._source_sample_rate_hz * 2), self._last_probability,
            )
            utterance = self._trim_trailing_silence(utterance, trailing_silence_ms)
            min_bytes = int((self._source_sample_rate_hz * 2) * (self._settings.min_speech_ms / 1000.0))
            if len(utterance) < min_bytes:
                logger.debug("Discarding sub-minimum speech segment (%d bytes)", len(utterance))
                return VadEvent(type=VadEventType.NOOP)
            return VadEvent(type=VadEventType.SPEECH_ENDED, utterance_pcm=utterance)

        return VadEvent(type=VadEventType.SPEECH_CONTINUING)

    def _update_probability(self, pcm_frame: bytes) -> None:
        """
        Accumulate incoming audio into `_score_buffer`; whenever it holds
        enough source-rate bytes to satisfy Silero's minimum chunk size,
        score that chunk and update `_last_probability`. Between chunk
        boundaries the previously computed probability is reused, so
        `process_frame` can still be called once per 20ms AudioSocket
        frame without ever handing Silero a too-short input.
        """
        self._score_buffer.extend(pcm_frame)
        while len(self._score_buffer) >= self._score_chunk_source_bytes:
            chunk = bytes(self._score_buffer[: self._score_chunk_source_bytes])
            del self._score_buffer[: self._score_chunk_source_bytes]
            self._last_probability = self._score_chunk(chunk)

    def _trim_trailing_silence(self, utterance: bytes, trailing_silence_ms: float) -> bytes:
        """
        Trim the accumulated trailing-silence run (see module docstring
        and `VadSettings.trailing_silence_keep_ms`) back down to a small
        margin before this audio goes to STT, keeping only enough tail to
        avoid clipping the very end of real speech.
        """
        trim_ms = trailing_silence_ms - self._trailing_silence_keep_ms
        if trim_ms <= 0:
            return utterance
        bytes_per_ms = (self._source_sample_rate_hz * 2) / 1000.0
        trim_bytes = int(bytes_per_ms * trim_ms)
        trim_bytes -= trim_bytes % 2  # keep 16-bit sample alignment
        if 0 < trim_bytes < len(utterance):
            return utterance[: len(utterance) - trim_bytes]
        return utterance

    def _score_chunk(self, source_pcm_chunk: bytes) -> float:
        """Resample (if needed) a properly-sized chunk and return Silero's speech probability."""
        target_hz = self._settings.target_sample_rate_hz
        resampled_pcm = resample_pcm16(source_pcm_chunk, from_hz=self._source_sample_rate_hz, to_hz=target_hz)
        samples = np.frombuffer(resampled_pcm, dtype="<i2").astype(np.float32) / 32768.0
        tensor = torch.from_numpy(samples)
        with torch.no_grad():
            probability = self._model(tensor, target_hz).item()
        return float(probability)

    def force_speech_start(self, preroll: bytes = b"") -> None:
        """Force state machine into SPEECH state (e.g. on confirmed barge-in)."""
        self._state = VadState.SPEECH
        self._silence_run_ms = 0.0
        if preroll:
            self._accumulator.append(preroll)

    def reset(self) -> None:
        """Reset state machine and model hidden state (e.g. at call teardown)."""
        self._state = VadState.SILENCE
        self._silence_run_ms = 0.0
        self._score_buffer.clear()
        self._last_probability = 0.0
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()

    def close(self) -> None:
        """Release borrowed model back to SileroModelPool."""
        if self._model is not None:
            SileroModelPool.release(self._model)
            self._model = None


def compute_frame_rms(pcm_frame: bytes) -> float:
    """Compute RMS energy for a 16-bit PCM mono frame."""
    if not pcm_frame:
        return 0.0
    samples = np.frombuffer(pcm_frame, dtype="<i2")
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))


class BargeInDetector:
    """
    Discriminates genuine caller interruption from transient noises, coughs,
    microphone pops, line hiss, and acoustic feedback during TTS playback.
    """

    def __init__(
        self,
        vad_engine: VadEngine,
        speech_threshold: float = 0.48,
        min_speech_ms: int = 100,
        min_rms: float = 70.0,
        frame_duration_ms: float = 20.0,
    ) -> None:
        self._vad = vad_engine
        self._speech_threshold = speech_threshold
        self._min_speech_ms = min_speech_ms
        self._min_rms = min_rms
        self._frame_duration_ms = frame_duration_ms
        self._consecutive_speech_ms = 0.0
        self._consecutive_speech_frames = 0
        self._hangover_frames = 0

    def reset(self) -> None:
        self._consecutive_speech_ms = 0.0
        self._consecutive_speech_frames = 0
        self._hangover_frames = 0

    def check_frame(self, pcm_frame: bytes) -> tuple[bool, float, float]:
        """
        Process incoming frame during active TTS playback.
        Returns:
          (is_confirmed_barge_in, probability, rms)
        """
        rms = compute_frame_rms(pcm_frame)
        self._vad._update_probability(pcm_frame)
        prob = self._vad._last_probability

        is_speech_frame = (prob >= self._speech_threshold) and (rms >= self._min_rms)

        if is_speech_frame:
            self._consecutive_speech_ms += self._frame_duration_ms
            self._consecutive_speech_frames += 1
            self._hangover_frames = 2  # allow 2 frames of tolerance for unvoiced consonants
            if self._consecutive_speech_ms >= self._min_speech_ms:
                logger.info(
                    "Barge-in CONFIRMED: sustained speech %.0fms (frames=%d, prob=%.2f, rms=%.1f)",
                    self._consecutive_speech_ms,
                    self._consecutive_speech_frames,
                    prob,
                    rms,
                )
                self.reset()
                return True, prob, rms
        elif self._hangover_frames > 0:
            self._hangover_frames -= 1
        else:
            self.reset()

        return False, prob, rms