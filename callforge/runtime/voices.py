"""Resolve Piper voice model paths and build per-agent TTS settings."""

from __future__ import annotations

from pathlib import Path

from config import TelephonySettings, TtsSettings
from callforge.store.models import AgentRecord

# Prefer local ./models/piper, fall back to /models/piper (Docker).
_VOICE_ROOTS = [
    Path("models/piper"),
    Path("/models/piper"),
]


def resolve_voice_path(voice_id: str) -> Path:
    """Map a voice id like 'en_US-amy-medium' to an .onnx path."""
    filename = f"{voice_id}.onnx"
    for root in _VOICE_ROOTS:
        candidate = root / filename
        if candidate.exists():
            return candidate
    # Return the first conventional path even if missing — TtsService will error clearly.
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
