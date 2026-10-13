"""
processing/prosody.py
=====================
Real-time acoustic prosody and emotion intelligence for phone conversations.

Analyzes raw 8kHz 16-bit PCM frames to extract:
  1. RMS Energy & Energy Variance (detects shouting, intensity, or whispered speech)
  2. Zero-Crossing Rate (ZCR) (estimates pitch elevation and consonant sharpness)
  3. Speech Cadence / Rate (distinguishes fast/rushed callers from calm/deliberate callers)

Derives caller emotional state:
  - 'agitated': High energy variance + elevated pitch + rapid onset -> triggers empathetic de-escalation
  - 'calm': Low energy variance + slow steady cadence -> matches slow, soothing pace
  - 'fast': Rapid speech bursts with high duty cycle -> matches quick, crisp, concise answers
  - 'neutral': Standard conversational cadence

Outputs dynamic prompt directives and adaptive TTS parameter scaling (Chameleon Effect).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProsodyMetrics:
    """Acoustic features computed from an utterance."""
    rms_mean: float
    rms_variance: float
    zcr_mean: float
    speech_duration_s: float
    estimated_rate_wpm: float


@dataclass(frozen=True, slots=True)
class EmotionProfile:
    """Classified emotion and adaptive steering parameters for LLM and TTS."""
    emotion: str  # "agitated" | "calm" | "fast" | "neutral"
    confidence: float
    metrics: ProsodyMetrics
    # Adaptive TTS parameters (Chameleon voice matching)
    tts_length_scale: float  # < 1.0 is faster, > 1.0 is slower
    tts_noise_scale: float   # emotional warmth / variability
    tts_volume_scale: float
    # Steering directive injected into LLM system prompt
    prompt_directive: str


class ProsodyAnalyzer:
    """
    Analyzes accumulated 16-bit 8000Hz mono PCM audio to detect caller emotion and prosody.
    """

    def __init__(self, sample_rate_hz: int = 8000, frame_bytes: int = 320) -> None:
        self._sample_rate_hz = sample_rate_hz
        self._frame_bytes = frame_bytes
        self._samples_per_frame = frame_bytes // 2

    def analyze_utterance(self, pcm_bytes: bytes, text_word_count: int = 0) -> EmotionProfile:
        """
        Analyze an utterance and return its emotional profile and adaptive directives.
        """
        if len(pcm_bytes) < self._frame_bytes * 3:
            # Utterance too short for meaningful prosody analysis; return neutral
            metrics = ProsodyMetrics(
                rms_mean=500.0,
                rms_variance=0.0,
                zcr_mean=0.1,
                speech_duration_s=len(pcm_bytes) / (self._sample_rate_hz * 2),
                estimated_rate_wpm=120.0,
            )
            return EmotionProfile(
                emotion="neutral",
                confidence=0.5,
                metrics=metrics,
                tts_length_scale=1.05,
                tts_noise_scale=0.667,
                tts_volume_scale=1.0,
                prompt_directive="",
            )

        samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
        total_duration_s = len(samples) / self._sample_rate_hz

        # Frame-by-frame analysis
        num_frames = len(samples) // self._samples_per_frame
        rms_values: list[float] = []
        zcr_values: list[float] = []

        for i in range(num_frames):
            frame = samples[i * self._samples_per_frame : (i + 1) * self._samples_per_frame]
            # RMS
            rms = float(np.sqrt(np.mean(frame ** 2)))
            rms_values.append(rms)
            # Zero-Crossing Rate
            zcr = float(np.mean(np.abs(np.diff(np.sign(frame + 1e-6)))) / 2.0)
            zcr_values.append(zcr)

        rms_mean = float(np.mean(rms_values)) if rms_values else 0.0
        rms_var = float(np.var(rms_values)) if rms_values else 0.0
        rms_std = math.sqrt(rms_var)
        zcr_mean = float(np.mean(zcr_values)) if zcr_values else 0.0

        # Estimate speaking rate
        if text_word_count > 0 and total_duration_s > 0.4:
            estimated_wpm = (text_word_count / total_duration_s) * 60.0
        else:
            # Heuristic estimate based on energy bursts
            energy_peaks = sum(1 for r in rms_values if r > rms_mean * 1.2)
            estimated_wpm = (energy_peaks / max(1.0, total_duration_s)) * 12.0

        metrics = ProsodyMetrics(
            rms_mean=round(rms_mean, 1),
            rms_variance=round(rms_var, 1),
            zcr_mean=round(zcr_mean, 3),
            speech_duration_s=round(total_duration_s, 2),
            estimated_rate_wpm=round(estimated_wpm, 1),
        )

        # Classify emotion
        # High RMS energy + high variance + high ZCR = Agitation / Frustration / Urgency
        is_agitated = (rms_mean > 1200.0 and rms_std > 800.0) or (rms_mean > 900.0 and zcr_mean > 0.16)
        # Low energy + low variance + slow speaking rate = Calm / Hesitant
        is_calm = (rms_mean < 750.0 and rms_std < 500.0 and estimated_wpm < 115.0)
        # High speaking rate = Fast / Energetic
        is_fast = (estimated_wpm > 155.0 and not is_agitated)

        if is_agitated:
            emotion = "agitated"
            confidence = 0.85
            tts_length_scale = 1.15  # Speak slightly slower and calmer to soothe the caller
            tts_noise_scale = 0.55   # Warmer, less jittery voice
            tts_volume_scale = 1.05
            prompt_directive = (
                "EMOTION DIRECTIVE: The caller sounds distressed or agitated. "
                "Respond with warm empathy, a calm and reassuring tone, and prioritize de-escalation. "
                "Acknowledge their feelings immediately and offer clear, direct help."
            )
        elif is_fast:
            emotion = "fast"
            confidence = 0.80
            tts_length_scale = 0.96  # Match their fast pace
            tts_noise_scale = 0.667
            tts_volume_scale = 1.0
            prompt_directive = (
                "EMOTION DIRECTIVE: The caller is speaking quickly and directly. "
                "Provide crisp, efficient, and direct answers without unnecessary filler."
            )
        elif is_calm:
            emotion = "calm"
            confidence = 0.75
            tts_length_scale = 1.18  # Match their unhurried, thoughtful pace
            tts_noise_scale = 0.70
            tts_volume_scale = 0.95
            prompt_directive = (
                "EMOTION DIRECTIVE: The caller is speaking softly and thoughtfully. "
                "Maintain a gentle, supportive, and unhurried tone."
            )
        else:
            emotion = "neutral"
            confidence = 0.70
            tts_length_scale = 1.05
            tts_noise_scale = 0.667
            tts_volume_scale = 1.0
            prompt_directive = ""

        logger.info(
            "Prosody: emotion=%s (conf=%.2f, rms=%.0f, var=%.0f, wpm=%.0f) -> tts_len=%.2f",
            emotion, confidence, rms_mean, rms_var, estimated_wpm, tts_length_scale,
        )

        return EmotionProfile(
            emotion=emotion,
            confidence=confidence,
            metrics=metrics,
            tts_length_scale=tts_length_scale,
            tts_noise_scale=tts_noise_scale,
            tts_volume_scale=tts_volume_scale,
            prompt_directive=prompt_directive,
        )
