"""
services/stt_service.py
========================
Speech-to-text via faster-whisper (CTranslate2 backend).

Architectural decision:
    `faster-whisper` inference is CPU/GPU-bound and blocking; running it
    directly on the asyncio event loop would stall every other concurrent
    call's audio I/O. We offload each transcription to a bounded
    `ThreadPoolExecutor` via `loop.run_in_executor`, keeping the event
    loop free while still bounding total concurrent CPU load across all
    calls (the pool size, not the call count, determines parallelism).
    The `WhisperModel` itself is loaded once per process and is safe to
    call concurrently from multiple worker threads (CTranslate2 handles
    internal locking).
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from faster_whisper import WhisperModel

from config import SttSettings
from processing.audio_buffer import pcm16_bytes_to_float32

logger = logging.getLogger(__name__)

# Matches any short substring (1-30 chars) immediately repeated 4+ times in
# a row, with or without separators -- catches both space-separated word
# loops ("interview interview interview ...") and run-on repeats with no
# separator at all ("बातबातबातबात..."). See _collapse_pathological_repeats.
_PATHOLOGICAL_REPEAT_RE = re.compile(r"(.{1,30}?)\1{3,}", re.DOTALL)


def _collapse_pathological_repeats(text: str) -> str:
    """
    Guard against Whisper's known failure mode of degenerating into a
    repeated-token/substring loop on ambiguous or silence-padded audio
    (observed in testing as both a word repeated ~80x and a syllable
    repeated with no spaces at all). Collapses any such run down to two
    repetitions -- kept rather than removed entirely so a genuinely
    garbled utterance still reads as garbled (and downstream code can
    react to it) instead of silently vanishing, but without flooding the
    LLM prompt (and its latency) with hundreds of duplicate tokens.
    """
    prev = None
    collapsed = text
    while prev != collapsed:
        prev = collapsed
        collapsed = _PATHOLOGICAL_REPEAT_RE.sub(lambda m: m.group(1) * 2, collapsed)
    return collapsed


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Result of transcribing one utterance."""

    text: str
    language: str
    duration_s: float
    average_logprob: float
    language_probability: float = 1.0


@dataclass(frozen=True, slots=True)
class PartialTranscriptionResult:
    """Incremental/partial transcript emitted while caller is still speaking."""

    text: str
    language: str
    duration_s: float
    is_final: bool = False


class SttService:
    """
    Thin async facade over a process-wide `faster-whisper` model instance.

    One `SttService` is shared (constructor-injected) across all concurrent
    `VoiceSession`s; the underlying model and thread pool are the only
    shared mutable resources, and both are safe for concurrent use.
    """

    def __init__(self, settings: SttSettings) -> None:
        self._settings = settings
        logger.info("Loading faster-whisper model '%s' (device=%s, compute=%s)",
                    settings.model_size, settings.device, settings.compute_type)
        self._model = WhisperModel(
            settings.model_size, device=settings.device, compute_type=settings.compute_type
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max(4, settings.thread_pool_workers), thread_name_prefix="stt-worker"
        )

    async def transcribe_pcm16(
        self,
        pcm_bytes: bytes,
        sample_rate_hz: int,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> Optional[TranscriptionResult]:
        """
        Transcribe one complete utterance of raw 16-bit PCM audio.

        Returns None if the utterance produced no meaningful transcript
        (e.g. pure noise segments that slipped past VAD's minimum duration
        filter).
        """
        if not pcm_bytes:
            return None
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._executor, self._transcribe_blocking, pcm_bytes, sample_rate_hz, language, initial_prompt
            )
        except Exception:
            logger.exception("STT transcription failed")
            return None

    def _transcribe_blocking(
        self,
        pcm_bytes: bytes,
        sample_rate_hz: int,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> Optional[TranscriptionResult]:
        """Runs on a worker thread. faster-whisper expects float32 audio at 16kHz."""
        from processing.audio_buffer import resample_pcm16

        if sample_rate_hz != 16000:
            pcm_bytes = resample_pcm16(pcm_bytes, from_hz=sample_rate_hz, to_hz=16000)
        audio = pcm16_bytes_to_float32(pcm_bytes)

        target_lang = language or self._settings.language
        target_prompt = initial_prompt or self._settings.initial_prompt

        segments, info = self._model.transcribe(
            audio,
            language=target_lang,
            beam_size=self._settings.beam_size,
            vad_filter=False,  # our own Silero VAD already segmented the audio
            condition_on_previous_text=False,  # avoid latency-inflating context carryover per turn
            # A single deterministic decode pass. faster-whisper's default
            # `temperature` is actually a *fallback chain*
            # ([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]): if the decode at one
            # temperature fails an internal confidence check (compression
            # ratio / avg logprob), it silently re-decodes the SAME audio
            # at the next temperature -- up to 6 full passes. Ambiguous or
            # code-switched (Hindi/English) audio routinely fails those
            # checks, so it was hitting most/all of that chain: this is
            # almost certainly why a 5s utterance was taking 40+ seconds,
            # and the final fallback attempt was still a poor transcript.
            # Pinning to a single float disables the chain entirely --
            # bounded, predictable latency (one pass, not up to six).
            temperature=0.0,
            # Domain-vocabulary bias -- see SttSettings.initial_prompt.
            initial_prompt=target_prompt,
        )
        text_parts: list[str] = []
        logprobs: list[float] = []
        no_speech_probs: list[float] = []
        for segment in segments:
            stripped = segment.text.strip()
            if stripped:
                text_parts.append(stripped)
                logprobs.append(segment.avg_logprob)
                no_speech_probs.append(segment.no_speech_prob)

        full_text = " ".join(text_parts).strip()
        full_text = _collapse_pathological_repeats(full_text)
        if not full_text:
            return None

        # Filter out punctuation-only or symbol-only hallucinations (e.g. Urdu dot '۔', '.', '...', etc.)
        letters_only = re.sub(r"[^\w\u0900-\u097F]", "", full_text).strip()
        if not letters_only:
            logger.debug("Discarding punctuation-only/hallucinated transcript: %r", full_text)
            return None

        # Guard against Whisper hallucinating a plausible-sounding phrase
        # (classically "Thank you." / "Thanks for watching.") from a
        # short, low-signal clip -- silence, a breath, background hum.
        # `no_speech_prob` is Whisper's OWN confidence that the segment
        # wasn't really speech at all; a high value alongside text being
        # returned anyway is exactly the hallucination signature. Discard
        # rather than treat it as a real caller utterance.
        avg_no_speech_prob = sum(no_speech_probs) / len(no_speech_probs) if no_speech_probs else 0.0
        if avg_no_speech_prob >= self._settings.no_speech_prob_reject_threshold:
            logger.debug(
                "Discarding likely-hallucinated transcript (no_speech_prob=%.2f): %r",
                avg_no_speech_prob, full_text,
            )
            return None

        # Guard against trusting a wild, low-confidence language guess on
        # a short/ambiguous clip (seen in testing: Tamil at 0.27
        # confidence from what was really noise). This app only knows how
        # to route replies to English or Hindi -- an unreliable language
        # tag doesn't just mislabel the turn, it sends garbled
        # foreign-script text straight to the LLM as if it were real
        # caller speech, producing confused, made-up-sounding replies.
        if info.language_probability < self._settings.language_probability_reject_threshold:
            logger.debug(
                "Discarding low language-confidence transcript (language=%s, probability=%.2f): %r",
                info.language, info.language_probability, full_text,
            )
            return None

        lang = info.language
        # If Faster-Whisper guessed Hindi ('hi') but the text is purely ASCII letters (no Devanagari script),
        # correct it to English ('en') so Indian-accented English isn't misrouted as Hindi
        if lang == "hi" and all(ord(c) < 128 or c.isspace() for c in full_text):
            lang = "en"

        return TranscriptionResult(
            text=full_text,
            language=lang,
            duration_s=info.duration,
            average_logprob=sum(logprobs) / len(logprobs) if logprobs else 0.0,
            language_probability=getattr(info, "language_probability", 1.0),
        )

    async def transcribe_partial_pcm16(
        self, pcm_bytes: bytes, sample_rate_hz: int, language: Optional[str] = None
    ) -> Optional[PartialTranscriptionResult]:
        """
        Fast progressive transcribe on partially accumulated speech while caller is still speaking.
        Greedy decoding (beam_size=1) for minimal compute overhead.
        """
        if not pcm_bytes:
            return None
        min_bytes = int(sample_rate_hz * 2 * 0.6)  # at least 600ms of audio
        if len(pcm_bytes) < min_bytes:
            return None
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._executor, self._transcribe_partial_blocking, pcm_bytes, sample_rate_hz, language
            )
        except Exception:
            logger.debug("Partial STT decode skipped/failed")
            return None

    def _transcribe_partial_blocking(
        self, pcm_bytes: bytes, sample_rate_hz: int, language: Optional[str] = None
    ) -> Optional[PartialTranscriptionResult]:
        from processing.audio_buffer import resample_pcm16

        if sample_rate_hz != 16000:
            pcm_bytes = resample_pcm16(pcm_bytes, from_hz=sample_rate_hz, to_hz=16000)
        audio = pcm16_bytes_to_float32(pcm_bytes)

        target_lang = language or self._settings.language

        try:
            segments, info = self._model.transcribe(
                audio,
                language=target_lang,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
                temperature=0.0,
                initial_prompt=self._settings.initial_prompt,
            )
            text_parts = [s.text.strip() for s in segments if s.text.strip()]
            full_text = " ".join(text_parts).strip()
            full_text = _collapse_pathological_repeats(full_text)
            if not full_text:
                return None
            return PartialTranscriptionResult(
                text=full_text,
                language=info.language,
                duration_s=info.duration,
                is_final=False,
            )
        except Exception as exc:
            logger.debug("Partial transcription failed: %s", exc)
            return None

    def shutdown(self) -> None:
        """Release the thread pool. Call once at application shutdown."""
        self._executor.shutdown(wait=True, cancel_futures=True)