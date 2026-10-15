"""Resolve Piper voice model paths and build per-agent TTS settings."""

from __future__ import annotations

import logging
from pathlib import Path

from config import TelephonySettings, TtsSettings
from callforge.store.models import AgentRecord

logger = logging.getLogger(__name__)

# Search paths for Piper ONNX voices (Docker /models/piper and local models/piper)
_VOICE_ROOTS = [
    Path("/models/piper"),
    Path("models/piper"),
    Path("/app/models/piper"),
]


def resolve_voice_path(voice_id: str) -> Path:
    """Map a voice id like 'en_US-amy-medium' to an .onnx path with safe fallback."""
    clean_id = voice_id.replace(".onnx", "").strip()
    filename = f"{clean_id}.onnx"

    # 1. Exact match in any known voice root
    for root in _VOICE_ROOTS:
        candidate = root / filename
        if candidate.exists():
            return candidate

    # 2. Resilient fallback: locate any existing onnx voice model in roots
    is_hindi = "hi" in clean_id.lower()
    fallback_name = "hi_IN-priyamvada-medium.onnx" if is_hindi else "en_US-amy-medium.onnx"

    for root in _VOICE_ROOTS:
        if root.exists():
            fb_candidate = root / fallback_name
            if fb_candidate.exists():
                logger.warning(
                    "Voice model '%s' not found. Falling back to '%s' at %s",
                    voice_id, fallback_name, fb_candidate
                )
                return fb_candidate

            # Any available ONNX voice in root
            available = list(root.glob("*.onnx"))
            if available:
                logger.warning(
                    "Voice model '%s' not found. Falling back to '%s'",
                    voice_id, available[0]
                )
                return available[0]

    # Return standard path if roots are not yet mounted
    for root in _VOICE_ROOTS:
        if root.exists():
            return root / filename
    return _VOICE_ROOTS[0] / filename


def tts_settings_for_agent(agent: AgentRecord, base: TtsSettings) -> TtsSettings:
    """Clone base TTS settings with agent-specific English/Hindi voices."""
    en_path = resolve_voice_path(agent.voice_en)
    hi_path = resolve_voice_path(agent.voice_hi)
    return TtsSettings(
        voice_model_path=en_path,
        voice_model_path_hi=hi_path,
        voice_config_path=str(en_path) + ".json",
        voice_config_path_hi=str(hi_path) + ".json",
        language=agent.language if agent.language in ("en", "hi") else base.language,
        piper_binary_path=base.piper_binary_path,
        output_sample_rate_hz=base.output_sample_rate_hz,
        sentence_min_chars=base.sentence_min_chars,
        pitch_shift_factor=base.pitch_shift_factor,
        length_scale=base.length_scale,
        noise_scale=base.noise_scale,
        noise_w_scale=base.noise_w_scale,
        volume=base.volume,
    )


def tts_settings_for_agent_variant_b(agent: AgentRecord, base: TtsSettings) -> TtsSettings:
    """Clone base TTS settings with Variant B English/Hindi voices."""
    en_voice = agent.ab_variant_b_voice_en or agent.voice_en
    hi_voice = agent.ab_variant_b_voice_hi or agent.voice_hi
    en_path = resolve_voice_path(en_voice)
    hi_path = resolve_voice_path(hi_voice)
    return TtsSettings(
        voice_model_path=en_path,
        voice_model_path_hi=hi_path,
        voice_config_path=str(en_path) + ".json",
        voice_config_path_hi=str(hi_path) + ".json",
        language=agent.language if agent.language in ("en", "hi") else base.language,
        piper_binary_path=base.piper_binary_path,
        output_sample_rate_hz=base.output_sample_rate_hz,
        sentence_min_chars=base.sentence_min_chars,
        pitch_shift_factor=base.pitch_shift_factor,
        length_scale=base.length_scale,
        noise_scale=base.noise_scale,
        noise_w_scale=base.noise_w_scale,
        volume=base.volume,
    )


def telephony_settings_for_port(base: TelephonySettings, port: int) -> TelephonySettings:
    return TelephonySettings(
        host=base.host,
        port=port,
        sample_rate_hz=base.sample_rate_hz,
        frame_bytes=base.frame_bytes,
        max_concurrent_calls=base.max_concurrent_calls,
        outbound_queue_max_frames=base.outbound_queue_max_frames,
    )
