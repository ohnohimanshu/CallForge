"""
services/tts_service.py
========================
Text-to-speech via a process-resident Piper engine.

Architectural decision:
    Voice models are loaded once (or as a small pool sized to
    TELEPHONY_MAX_CONCURRENT_CALLS) and kept resident. Synthesis is
    offloaded to a ThreadPoolExecutor so the asyncio loop stays free for
    AudioSocket I/O across concurrent calls.

    onnxruntime sessions are not safe for concurrent inference on the
    *same* PiperVoice instance, so each pool slot owns its own loaded
    voice + a matching worker thread. That lets N English (or Hindi)
    sentences synthesize in parallel when N callers speak at once.
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator, Optional

from piper import PiperVoice, SynthesisConfig

from config import TelephonySettings, TtsSettings
from processing.audio_buffer import resample_pcm16

logger = logging.getLogger(__name__)

# Small local LLMs (e.g. qwen2.5:3b, llama3.2:3b) don't reliably follow "no
# markdown / no actions" system-prompt instructions, especially for a
# roleplay-style persona -- they'll periodically emit stage directions like
# "*blushes*" or markdown emphasis like "**really**". Piper has no concept
# of either and will synthesize the literal characters (e.g. pronouncing
# "asterisk"), so this is stripped unconditionally at the TTS boundary
# rather than relying on prompt compliance alone.
_ACTION_RE = re.compile(r"\*[^*\n]+\*")  # *sighs*, *giggles softly* -- whole action removed
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")  # **word** -- keep the text, drop the markers
_UNDERSCORE_EMPHASIS_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)")  # _word_ -- keep text, drop markers
_STRAY_MARKDOWN_RE = re.compile(r"[*_`#~]")  # any leftover stray markdown symbols
_WHITESPACE_RE = re.compile(r"[ \t]{2,}")
# Numbers / abbreviations that sound clearer when spoken on a phone line.
_PHONE_NUMBER_RE = re.compile(r"\b(\d{3})[-.]?(\d{3})[-.]?(\d{4})\b")
_ELLIPSIS_RE = re.compile(r"\.{2,}")


def sanitize_for_speech(text: str) -> str:
    """
    Strip markdown formatting, stage directions, and problematic symbols
    from LLM output before it's handed to Piper TTS.
    """
    text = _BOLD_RE.sub(r"\1", text)
    text = _UNDERSCORE_EMPHASIS_RE.sub(r"\1", text)
    text = _ACTION_RE.sub("", text)
    text = _STRAY_MARKDOWN_RE.sub("", text)
    text = _ELLIPSIS_RE.sub(". ", text)
    text = _PHONE_NUMBER_RE.sub(r"\1 \2 \3", text)
    # Expand common abbreviations that cause weird phoneme / pitch glitches:
    text = re.sub(r"\be\.g\.,?\s*", "for example, ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bi\.e\.,?\s*", "that is, ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bapprox\.\s*", "approximately ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDr\.\s*", "Doctor ", text)
    text = re.sub(r"\bMr\.\s*", "Mister ", text)
    text = re.sub(r"\bMrs\.\s*", "Misses ", text)
    text = re.sub(r"\bMs\.\s*", "Miss ", text)
    text = re.sub(r"\bRs\.\s*", "Rupees ", text, flags=re.IGNORECASE)
    # Clean symbols that trigger unnatural pitch spikes or clicks in Piper
    text = re.sub(r"[{}\[\]^~@|\\/<>=+*#;]", " ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


class _VoicePool:
    """Checkout pool of PiperVoice instances (one ONNX session per concurrent slot)."""

    def __init__(self, label: str, model_path: str, config_path: Optional[str], size: int = 1) -> None:
        size = max(1, size)
        self._label = label
        self._model_path = model_path
        self._config_path = config_path
        logger.info("Loading Piper voice (%s, pool=%d): %s", label, size, model_path)
        self._slots: list[tuple[PiperVoice, ThreadPoolExecutor]] = []
        for i in range(size):
            voice = PiperVoice.load(model_path, config_path or None)
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tts-{label}-{i}")
            self._slots.append((voice, executor))
        self._native_hz = self._slots[0][0].config.sample_rate
        self._free: asyncio.Queue[tuple[PiperVoice, ThreadPoolExecutor]] = asyncio.Queue()
        for slot in self._slots:
            self._free.put_nowait(slot)

    @property
    def native_hz(self) -> int:
        return self._native_hz

    async def synthesize(self, text: str, syn_config: SynthesisConfig) -> bytes:
        try:
            voice, executor = self._free.get_nowait()
        except asyncio.QueueEmpty:
            # All pre-warmed slots busy: dynamically spin up an additional slot so multiple concurrent callers never block
            logger.info("Piper voice pool (%s) exhausted; creating on-demand slot", self._label)
            voice = PiperVoice.load(self._model_path, self._config_path or None)
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tts-{self._label}-dyn")
            self._slots.append((voice, executor))

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                executor, _synthesize_blocking, voice, text, syn_config
            )
        finally:
            self._free.put_nowait((voice, executor))

    def shutdown(self) -> None:
        for _, executor in self._slots:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        self._slots.clear()
        while not self._free.empty():
            try:
                self._free.get_nowait()
            except Exception:
                break


def _synthesize_blocking(voice: PiperVoice, text: str, syn_config: SynthesisConfig) -> bytes:
    return b"".join(
        chunk.audio_int16_bytes for chunk in voice.synthesize(text, syn_config=syn_config)
    )


from services.voice_clone_service import voice_clone_service


class TtsService:
    """
    Facade over process-resident Piper voice pools (English, Hindi)
    and on-the-fly voice cloning engine.

    One `TtsService` is constructed per persona/agent line (each persona
    can use a different voice pair or custom cloned voice).
    """

    def __init__(
        self,
        tts_settings: TtsSettings,
        telephony_settings: TelephonySettings,
        cloned_voice_path: Optional[str] = None,
        warm_pool_size: int = 1,
    ) -> None:
        self._settings = tts_settings
        self._telephony_settings = telephony_settings
        self._frame_bytes = telephony_settings.frame_bytes
        self._cloned_voice_path = cloned_voice_path
        self._warm_pool_size = max(1, warm_pool_size)

        self._pool_en: Optional[_VoicePool] = _VoicePool(
            "en",
            str(tts_settings.voice_model_path),
            tts_settings.voice_config_path or None,
            self._warm_pool_size,
        )
        self._pool_hi: Optional[_VoicePool] = None
        # Only warm Hindi pool if agent explicitly targets Hindi
        if tts_settings.language == "hi":
            self._pool_hi = _VoicePool(
                "hi",
                str(tts_settings.voice_model_path_hi),
                tts_settings.voice_config_path_hi or None,
                self._warm_pool_size,
            )

        self._syn_config = SynthesisConfig(
            length_scale=tts_settings.length_scale,
            noise_scale=tts_settings.noise_scale,
            noise_w_scale=tts_settings.noise_w_scale,
            normalize_audio=True,
            volume=tts_settings.volume,
        )
        logger.info(
            "Piper TTS resident and warm: en=%dHz hi=%s pool=%d "
            "length_scale=%.2f noise_scale=%.2f volume=%.2f (cloned_voice=%s)",
            self._pool_en.native_hz,
            "warm" if self._pool_hi else "lazy",
            self._warm_pool_size,
            tts_settings.length_scale,
            tts_settings.noise_scale,
            tts_settings.volume,
            bool(cloned_voice_path),
        )

    def _get_pool_hi(self) -> _VoicePool:
        if self._pool_hi is None:
            self._pool_hi = _VoicePool(
                "hi",
                str(self._settings.voice_model_path_hi),
                self._settings.voice_config_path_hi or None,
                self._warm_pool_size,
            )
        return self._pool_hi

    async def synthesize_raw(
        self,
        text: str,
        target_language: str = "en",
        pitch_shift: float = 1.0,
        length_scale: Optional[float] = None,
        noise_scale: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> bytes:
        """Synthesize text and return 8kHz PCM16 bytes directly."""
        text = sanitize_for_speech(text)
        if not text.strip():
            return b""
        is_hindi = target_language == "hi"
        pool = self._get_pool_hi() if is_hindi else self._pool_en

        base_len = length_scale if length_scale is not None else self._syn_config.length_scale
        base_noise = noise_scale if noise_scale is not None else self._syn_config.noise_scale
        base_vol = volume if volume is not None else self._syn_config.volume

        syn_config = SynthesisConfig(
            length_scale=base_len,
            noise_scale=base_noise,
            noise_w_scale=self._syn_config.noise_w_scale,
            normalize_audio=True,
            volume=base_vol,
        )
        native_pcm = await pool.synthesize(text, syn_config)
        return resample_pcm16(
            native_pcm,
            from_hz=pool.native_hz,
            to_hz=self._settings.output_sample_rate_hz,
        )

    async def synthesize_streaming(
        self,
        text: str,
        interrupt_event: asyncio.Event,
        target_language: str = "en",
        length_scale: Optional[float] = None,
        noise_scale: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> AsyncIterator[bytes]:
        """
        Synthesize `text` and yield telephony-compliant 20ms PCM chunks.
        Supports on-the-fly cloned voices and dynamic prosody overrides (length_scale, noise_scale, volume)
        for real-time emotional matching.
        """
        text = sanitize_for_speech(text)
        logger.debug("[TTS] Synthesizing: %s", text)
        if not text.strip():
            return

        if interrupt_event.is_set():
            logger.info("TTS synthesis cut-off early before synthesis started.")
            return

        # 1. Check if persona has a custom cloned voice enabled
        if self._cloned_voice_path:
            try:
                if Path(self._cloned_voice_path).exists():
                    cloned_pcm = await voice_clone_service.synthesize_cloned(
                        text=text,
                        sample_path=self._cloned_voice_path,
                        target_language=target_language,
                        base_tts_func=self.synthesize_raw,
                    )
                    if cloned_pcm and not interrupt_event.is_set():
                        usable_len = (len(cloned_pcm) // self._frame_bytes) * self._frame_bytes
                        for offset in range(0, usable_len, self._frame_bytes):
                            if interrupt_event.is_set():
                                logger.info("Outbound cloned audio stream interrupted by active user barge-in.")
                                return
                            yield cloned_pcm[offset : offset + self._frame_bytes]

                        remainder = cloned_pcm[usable_len:]
                        if remainder and not interrupt_event.is_set():
                            yield remainder.ljust(self._frame_bytes, b"\x00")
                        return
            except Exception as exc:
                logger.warning("[TTS] Cloned voice synthesis failed, falling back to Piper: %s", exc)

        # 2. Standard Piper Neural TTS
        is_hindi = target_language == "hi"
        pool = self._get_pool_hi() if is_hindi else self._pool_en
        native_hz = pool.native_hz

        base_len = length_scale if length_scale is not None else self._syn_config.length_scale
        syn_config = SynthesisConfig(
            length_scale=base_len,
            noise_scale=noise_scale if noise_scale is not None else self._syn_config.noise_scale,
            noise_w_scale=self._syn_config.noise_w_scale,
            normalize_audio=True,
            volume=volume if volume is not None else self._syn_config.volume,
        )

        try:
            native_pcm = await pool.synthesize(text, syn_config)
        except Exception as e:
            logger.error("TTS processing failed inside TtsService: %s", e, exc_info=True)
            return

        if interrupt_event.is_set():
            logger.info("Inference complete but barge-in detected; dropping audio.")
            return

        if not native_pcm:
            logger.warning("TTS returned empty audio for text: %.60s", text)
            return

        resampled = resample_pcm16(
            native_pcm,
            from_hz=native_hz,
            to_hz=self._settings.output_sample_rate_hz,
        )

        usable_len = (len(resampled) // self._frame_bytes) * self._frame_bytes
        for offset in range(0, usable_len, self._frame_bytes):
            if interrupt_event.is_set():
                logger.info("Outbound audio stream interrupted by active user barge-in.")
                return
            yield resampled[offset : offset + self._frame_bytes]

        remainder = resampled[usable_len:]
        if remainder and not interrupt_event.is_set():
            yield remainder.ljust(self._frame_bytes, b"\x00")

    def shutdown(self) -> None:
        """Release the thread pools. Call once at application shutdown or line reload."""
        if self._pool_en is not None:
            self._pool_en.shutdown()
            self._pool_en = None
        if self._pool_hi is not None:
            self._pool_hi.shutdown()
            self._pool_hi = None
