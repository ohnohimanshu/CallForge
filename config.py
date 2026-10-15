"""
config.py
=========
Centralized, typed application configuration.

Architectural decision:
    All tunable parameters (network endpoints, VAD thresholds, model paths,
    concurrency limits) are defined here as a single frozen Pydantic model,
    loaded once at process start from environment variables / a `.env`
    file. This gives us:
      * A single source of truth (no magic numbers scattered across modules).
      * Fail-fast startup: Pydantic validates types/ranges before any
        socket is opened or model is loaded.
      * Trivial testability: any module that needs configuration takes a
        `Settings` instance via constructor injection rather than reading
        `os.environ` directly (Dependency Inversion Principle).

    Each nested settings class (TelephonySettings, VadSettings, etc.) is
    itself a `BaseSettings` subclass and is instantiated independently via
    `default_factory` on the root `Settings` class. Because of that, each
    one must declare its OWN `env_file=".env"` — inheriting/relying on the
    parent's `env_file` config does NOT propagate to independently
    constructed nested settings. Omitting this on any subclass means that
    class silently reads only real process environment variables and
    ignores `.env` entirely, which is a very easy, very quiet bug to
    reintroduce if a new settings class is added later without copying
    this pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelephonySettings(BaseSettings):
    """AudioSocket TCP server configuration."""

    model_config = SettingsConfigDict(env_prefix="TELEPHONY_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = Field(default="0.0.0.0", description="Bind address for the AudioSocket TCP server.")
    port: int = Field(default=9092, ge=1, le=65535, description="Bind port for the AudioSocket TCP server.")
    sample_rate_hz: int = Field(default=8000, description="AudioSocket wire sample rate (fixed by Asterisk).")
    frame_bytes: int = Field(default=320, description="Bytes per 20ms frame at 8kHz/16-bit mono (160 samples * 2).")
    max_concurrent_calls: int = Field(
        default=2,
        ge=1,
        description=(
            "Simultaneous sessions per agent AudioSocket line. On ~8GB CPU hosts "
            "keep this at 2–4; raise only if STT/LLM/TTS headroom allows."
        ),
    )
    outbound_queue_max_frames: int = Field(
        default=200, ge=1, description="Max buffered outbound frames per call before we drop (barge-in safety)."
    )


class VadSettings(BaseSettings):
    """Silero VAD tuning parameters."""

    model_config = SettingsConfigDict(env_prefix="VAD_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    target_sample_rate_hz: int = Field(
        default=8000,
        description=(
            "Sample rate Silero VAD scores at. Silero natively supports 8000 and 16000; "
            "8000 matches AudioSocket's native rate and avoids resampling entirely."
        ),
    )
    speech_threshold: float = Field(default=0.48, ge=0.0, le=1.0, description="Probability above which a frame is 'speech'.")
    min_silence_ms: int = Field(
        default=550,
        ge=100,
        description=(
            "Trailing silence required to close an utterance. 550ms allows natural "
            "conversational pauses while maintaining low turn-taking latency."
        ),
    )
    pre_speech_padding_ms: int = Field(
        default=300, ge=0, description="Amount of pre-roll audio retained so word onsets aren't clipped."
    )
    min_speech_ms: int = Field(default=150, ge=0, description="Discard speech segments shorter than this (noise).")
    max_utterance_ms: int = Field(default=20000, ge=1000, description="Hard cap to force end-of-turn on run-on speech.")
    trailing_silence_keep_ms: int = Field(
        default=200,
        ge=0,
        description=(
            "The accumulated utterance necessarily includes the full trailing-silence "
            "run used to detect end-of-turn (up to min_silence_ms), since that's needed "
            "for the turn-taking decision itself. But handing Whisper a clip with a "
            "second-plus of dead air at the end is a known trigger for degenerate "
            "repeated-token hallucination (e.g. a word or syllable repeated dozens of "
            "times in a row). The tail is trimmed back down to this many ms before STT "
            "sees it -- enough margin to avoid clipping a trailing consonant/breath at "
            "the very end of real speech, but far short of the full turn-detection "
            "silence window."
        ),
    )
    barge_in_speech_threshold: float = Field(
        default=0.48,
        ge=0.0,
        le=1.0,
        description=(
            "Speech probability threshold required to trigger barge-in while "
            "TTS is actively speaking. Tuned for responsive interruption."
        ),
    )
    barge_in_min_speech_ms: int = Field(
        default=180,
        ge=40,
        description=(
            "Consecutive/sustained speech duration required to confirm genuine caller interruption (e.g. 150-250ms)."
        ),
    )
    barge_in_min_rms: float = Field(
        default=75.0,
        ge=0.0,
        description=(
            "Minimum RMS amplitude for incoming audio to trigger barge-in."
        ),
    )


class SttSettings(BaseSettings):
    """faster-whisper (CTranslate2) configuration."""

    model_config = SettingsConfigDict(env_prefix="STT_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    model_size: str = Field(
        default="small",
        description=(
            "faster-whisper model name or local CT2 path. Must NOT use a '.en' "
            "suffixed variant (e.g. 'small.en') -- those are English-only and "
            "cannot detect or transcribe Hindi at all, which silently breaks "
            "the language-routing behavior CallPipeline depends on (it trusts "
            "transcription.language to pick English vs Hindi reply mode). "
            "'.en' models are also not faster than the multilingual model of "
            "the same size, so this costs nothing on latency."
        ),
    )
    device: Literal["cpu", "cuda"] = Field(default="cpu")
    compute_type: str = Field(default="int8", description="CTranslate2 quantization: int8, int8_float16, float16...")
    beam_size: int = Field(default=1, ge=1, description="Beam size; 1 = greedy for lowest latency.")
    language: str | None = Field(default=None, description="Force a language (e.g. 'en') or leave None to auto-detect.")
    thread_pool_workers: int = Field(default=2, ge=1, description="Worker threads for offloading blocking inference.")
    no_speech_prob_reject_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "If a segment's own no_speech_prob (Whisper's confidence that it wasn't "
            "real speech) averages above this, the transcript is discarded instead of "
            "treated as a real utterance -- guards against Whisper hallucinating a "
            "plausible phrase (classically 'Thank you.') from a short, low-signal clip."
        ),
    )
    language_probability_reject_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "If Whisper's own confidence in its detected language is below this, the "
            "transcript is discarded rather than trusted -- a short/ambiguous/noisy "
            "clip can get misidentified as an unexpected language (e.g. Tamil at 0.27 "
            "confidence from what was actually noise) and, since this app only knows "
            "how to route replies to English or Hindi, a wrongly-detected language "
            "leads to nonsense downstream rather than being caught and discarded."
        ),
    )
    initial_prompt: str | None = Field(
        default="Hello, I want to book an appointment. Available slots are 10:00 AM, 02:30 PM, 04:00 PM.",
        description=(
            "Optional text handed to Whisper as decoding context/bias -- does not get "
            "transcribed itself, but nudges word choice and spelling toward the given "
            "vocabulary/style. Useful for domain terms and code-switched Hindi/English "
            "speech (e.g. listing expected English loanwords like 'MSc', 'computer "
            "science', 'job', 'Japan' helps Whisper recognize them correctly instead of "
            "mangling them into phonetic Hindi guesses)."
        ),
    )


class LlmSettings(BaseSettings):
    """Local Ollama streaming client configuration."""

    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    base_url: str = Field(default="http://ollama:11434", description="Ollama HTTP API base URL.")
    model: str = Field(
        default="llama3.2:3b-instruct-q4_K_M",
        description=(
            "Ollama model tag. A ~3B Q4 model is the right size class for 8GB "
            "RAM / no-GPU: a 7B model at Q4 is ~4.5GB of weights alone, which "
            "pushes the whole box (Whisper + Piper + Asterisk + this model all "
            "resident together) into swap -- disk-speed token generation, not "
            "RAM-speed. This is the deployed choice; if reply quality needs a "
            "bump, try qwen2.5:3b-instruct-q4_0 before going back up to 7B."
        ),
    )
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    num_predict: int = Field(
        default=110,
        ge=1,
        description=(
            "Max tokens generated per turn. Lowered from 256 -- worst-case "
            "generation latency scales directly with this, and a phone-call "
            "reply that needs more than ~110 tokens (a few sentences) is "
            "already too long for a voice call. The system prompt also caps "
            "replies at three sentences, so this is a backstop, not the "
            "primary length control."
        ),
    )
    num_thread: int | None = Field(
        default=None,
        description=(
            "CPU threads Ollama uses for inference (Ollama's 'num_thread' "
            "option). Left as None by default (Ollama's own auto-detection), "
            "but worth setting explicitly on a Ryzen 5-class box: set to your "
            "physical core count (not hyperthread count) -- e.g. 5 or 6, "
            "leaving 1-2 cores free for Whisper/Piper/Asterisk running "
            "concurrently on the same machine. Try a couple of values and "
            "measure; auto-detection doesn't always pick the fastest setting "
            "on a shared, resource-constrained box like this one."
        ),
    )
    request_timeout_s: float = Field(
        default=45.0,
        gt=0.0,
        description=(
            "Increased from an earlier 30.0 default -- RAG-augmented prompts on "
            "CPU-only hardware can legitimately take longer than 30s to finish "
            "generating, and a client-side timeout mid-turn currently means the "
            "caller gets total silence back (no fallback speech) for that turn. "
            "45s gives more headroom; see also CallPipeline._handle_utterance's "
            "fallback-speech behavior for when a turn fails outright regardless."
        ),
    )
    system_prompt: str = Field(
        default=(
            "You are a professional phone agent for a business call. "
            "Speak clearly, calmly, and courteously — like a trained receptionist. "
            "Use short complete sentences (1–2 per turn). Never use markdown, lists, "
            "emojis, stage directions, or filler like 'um' or 'as an AI'. "
            "Confirm what the caller needs, answer directly, and offer one helpful "
            "next step. If you do not know something, say so briefly and ask a "
            "clarifying question. Keep language plain and easy to understand over a phone."
        )
    )
    greeting_text: str = Field(
        default="Thank you for calling. How may I help you today?",
        description="Proactive greeting spoken if the caller stays silent after connecting.",
    )
    initial_silence_timeout_s: float = Field(
        default=3.0,
        gt=0.0,
        description="Seconds of caller silence after connect before the agent proactively greets instead of waiting.",
    )
    keep_alive: str = Field(
        default="30m",
        description=(
            "Ollama 'keep_alive' duration -- how long the model stays resident in "
            "memory after a request before Ollama unloads it. Ollama's own default is "
            "5m; a cold (re-)load on the next request after that is a major source of "
            "time-to-first-token latency (multi-second to tens-of-seconds on CPU), so "
            "this is set longer to keep the model warm across the gaps between calls. "
            "Also used for an explicit warm-up request at process startup -- see "
            "LlmService.warm_up()."
        ),
    )


class TtsSettings(BaseSettings):
    """Piper TTS voice configuration."""

    model_config = SettingsConfigDict(env_prefix="TTS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    voice_model_path: Path = Field(
        default=Path("models/piper/en_US-lessac-medium.onnx"),
        description="Path to a Piper .onnx file."
    )
    language: str = Field(
        default="en",
        description="Target language code (e.g. 'en').",
    )
    voice_model_path_hi: Path = Field(
        default=Path("models/piper/hi_IN-priyamvada-medium.onnx"),
        description="Path to a Piper .onnx file for Hindi."
    )
    length_scale: float = Field(
        default=1.12,
        ge=0.5,
        le=2.0,
        description=(
            "Piper phoneme length scale. >1 speaks slightly slower and clearer "
            "(better for phone); <1 is faster."
        ),
    )
    noise_scale: float = Field(
        default=0.5,
        ge=0.0,
        le=1.5,
        description="Lower = cleaner/less 'buzzy' synthesis; Piper default is ~0.667.",
    )
    noise_w_scale: float = Field(
        default=0.7,
        ge=0.0,
        le=1.5,
        description="Phoneme-width noise; slightly below Piper default (0.8) for steadier speech.",
    )
    volume: float = Field(
        default=1.05,
        ge=0.2,
        le=2.0,
        description="Output gain before telephony resampling.",
    )
    voice_config_path: str = Field(
        default="",
        description="Path to the .onnx.json config file for English Piper TTS."
    )
    voice_config_path_hi: str = Field(
        default="",
        description="Path to the .onnx.json config file for Hindi Piper TTS."
    )
    piper_binary_path: str = Field(
        default="piper",
        description=(
            "Unused as of the in-process TtsService rewrite -- TtsService now "
            "loads Piper voice models directly via the `piper` Python package "
            "(PiperVoice.load) instead of shelling out to this CLI binary per "
            "sentence. Left in place in case a CLI-based deployment path is "
            "still needed elsewhere; safe to remove if not."
        ),
    )
    output_sample_rate_hz: int = Field(default=8000, description="Sample rate required by AudioSocket/Asterisk.")
    sentence_min_chars: int = Field(default=6, description="Ignore fragments shorter than this when chunking.")
    pitch_shift_factor: float = Field(
        default=1.0,
        gt=0.5,
        le=2.0,
        description=(
            "Naive pitch-shift multiplier applied to synthesized speech. Implemented by "
            "lying to the resampler about the audio's true source sample rate: multiplying "
            "it up makes the resampler compress more original samples into the same output "
            "duration, which raises pitch and (as a side effect) speeds playback up slightly "
            "-- the classic 'chipmunk' effect. 1.0 = unmodified voice. Values around 1.08-1.18 "
            "give a noticeably lighter/younger character without sounding cartoonish; values "
            "above ~1.3 start to sound unnatural. This is a cheap DSP trick, not a proper "
            "pitch-preserving-duration shift (which would need a phase vocoder) -- but it's "
            "sufficient for pushing a voice toward a lighter, more 'anime-style' register."
        ),
    )

    @field_validator("voice_model_path", "voice_model_path_hi", mode="before")
    @classmethod
    def _coerce_path(cls, v: str | Path) -> Path:
        p = Path(v)
        if not p.exists():
            for root in [Path("/models/piper"), Path("models/piper"), Path("/app/models/piper")]:
                cand = root / p.name
                if cand.exists():
                    return cand
        return p


class Settings(BaseSettings):
    """Root settings object aggregating all subsystem configurations."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = Field(default="INFO")
    telephony: TelephonySettings = Field(default_factory=TelephonySettings)
    vad: VadSettings = Field(default_factory=VadSettings)
    stt: SttSettings = Field(default_factory=SttSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    tts: TtsSettings = Field(default_factory=TtsSettings)


def load_settings() -> Settings:
    """Load and validate settings once. Call at process startup only."""
    return Settings()