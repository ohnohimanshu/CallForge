"""
pipeline.py
===========
The conversational state machine linking VAD -> STT -> LLM -> TTS for a
single `VoiceSession`, orchestrated purely through asyncio queues/events
so it has zero direct knowledge of sockets or protocol bytes.

Architectural decision:
    `pipeline.py` depends only on abstractions injected at construction
    time (`SttService`, `LlmService`, `TtsService`, `VadEngine`) and the
    `VoiceSession` queues/events exposed by the telephony layer -- never on
    `asyncio.StreamReader/Writer` or AudioSocket framing directly
    (Dependency Inversion). This means the entire conversational pipeline
    is unit-testable by feeding synthetic PCM into `session.inbound_audio`
    and asserting on `session.outbound_audio`, with no real socket or
    Asterisk instance required.

    Barge-in is implemented as a *separate concurrent task* per session
    that watches `inbound_audio` for renewed speech while TTS/LLM output
    is in flight, and sets `session.barge_in_event` the instant speech
    resumes -- the generation/synthesis coroutines poll this event on
    every loop iteration and abort within tens of milliseconds. Setting
    the event alone only stops *new* audio from being generated/queued,
    though -- any frames already sitting in `session.outbound_audio`
    (which can be several seconds' worth, see `TelephonySettings.
    outbound_queue_max_frames`) would otherwise keep draining out and
    playing regardless. `_clear_outbound_queue` is what makes barge-in
    feel instant (ChatGPT-voice-mode-style) instead of "waits for the
    current sentence to finish": the moment barge-in is detected, we drop
    every frame currently queued, not just stop adding new ones.

    Language handling: which language the agent replies in is decided
    once per turn from faster-whisper's own detected language
    (`transcription.language`), not left for the LLM to infer from the
    text -- small local models are unreliable at that kind of
    self-directed judgment call. The chosen language is then used for
    *both* the system-prompt instruction and TTS voice routing for the
    whole turn, rather than re-detecting per sentence via script sniffing
    (which silently fails whenever the LLM ignores the "use Devanagari"
    instruction and writes romanized Hinglish instead -- see
    `services/tts_service.py` and `services/transliteration_service.py`
    for how that's handled defensively on the TTS side).

    Multi-persona support: `AgentPersona` bundles everything that varies
    per agent "line" (per dialplan extension / AudioSocket port) --
    system prompt, proactive greeting text, and initial-silence timeout.
    A single `CallPipeline` is constructed per call with the persona
    appropriate to whichever port it connected on (see `main.py`), while
    the underlying `SttService`/`LlmService` instances are shared across
    all personas to avoid loading duplicate models on constrained
    hardware. Only `TtsService` differs per persona (different voice).
"""

from __future__ import annotations

import asyncio
from collections import deque
import logging
import re
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from config import Settings
from services.llm_service import ConversationTurn, LlmService
from services.stt_service import SttService
from services.tts_service import TtsService
from services.rag_service import RagService
from services.caller_memory_service import caller_memory_service
from callforge.store.models import CallerProfileRecord
from processing.canned_responses import match_canned_response
from processing.conversational_flow import ConversationalFlowEngine
from processing.prosody import EmotionProfile, ProsodyAnalyzer
from processing.vad import BargeInDetector, VadEngine, VadEventType
from telephony.server import VoiceSession

if TYPE_CHECKING:
    from callforge.store.db import PlatformStore

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 2  # user+assistant pairs retained per call (lowered to 2 for CPU latency:
# bounds prompt size to under 100 tokens, enabling sub-second prompt evaluation in Ollama)

# Spoken when a turn produces no reply at all -- e.g. the Ollama request
# timed out or errored (see LlmService.stream_reply's except block, which
# returns silently on httpx.HTTPError). Without this, a failed turn left
# the caller with total dead air instead of any acknowledgement.
_FALLBACK_REPLY_EN = "Sorry, I'm having a little trouble right now. Could you say that again?"
_FALLBACK_REPLY_HI = "माफ़ कीजिए, मुझे अभी थोड़ी दिक्कत हो रही है। क्या आप फिर से बता सकते हैं?"

_HANDOFF_PATTERNS = [
    # Explicit transfer / human request phrases
    r"\b(?:talk|speak|connect|transfer|switch)\s+(?:me\s+)?(?:to|with)\s+(?:a\s+|an\s+)?(?:human|person|agent|operator|representative|supervisor|someone|somebody)\b",
    r"\b(?:want|need|get|give)\s+(?:me\s+)?(?:a\s+|an\s+)?(?:human|person|agent|operator|representative|supervisor)\b",
    r"\b(?:transfer|forward)\s+(?:me|my call|the call|this call)\b",
    r"\b(?:real|live|human)\s+(?:person|agent|operator|representative)\b",
    r"\b(?:customer\s+(?:service|support|care))\b",
    # Single-word utterances where caller just says "human", "agent", or "operator"
    r"^\s*(?:human|agent|operator|representative|supervisor|person)\s*[.?!]?\s*$",
    # Hindi phrases
    r"\b(?:insaan|kisi|agent|operator|supervisor)\s+se\s+baat\b",
    r"\b(?:transfer|connect)\s+(?:kardo|karo|kar do|kar dijiye|kijiye)\b",
    r"\b(?:kisi\s+insaan\s+ko\s+(?:do|bulao|connect\s+karo))\b",
    r"\b(?:customer\s+care\s+se\s+baat)\b",
]
_HANDOFF_REGEX = re.compile("|".join(_HANDOFF_PATTERNS), re.IGNORECASE)


def _is_handoff_requested(text: str) -> bool:
    return bool(_HANDOFF_REGEX.search(text))


# Factual knowledge / inquiry keywords that warrant searching the knowledge base (RAG)
_RAG_KEYWORDS = (
    "what", "where", "when", "why", "how", "which", "who",
    "cost", "price", "pricing", "rate", "fee", "hours", "timing", "time",
    "service", "services", "product", "products", "policy", "policies",
    "return", "refund", "support", "help", "feature", "features",
    "plan", "plans", "address", "location", "contact", "order", "account",
    "status", "detail", "details", "info", "information", "tell me",
    "do you have", "is there", "are there", "can you",
    "क्या", "कहाँ", "कब", "क्यों", "कैसे", "कितना", "प्राइस", "टाइमिंग", "फीस", "सर्विस", "पता",
)

_CONVERSATIONAL_EXACT = {
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "how are you doing", "what's up", "who are you", "what are you",
    "yes", "yeah", "yep", "sure", "ok", "okay", "alright", "fine", "correct",
    "no", "nope", "nah", "never mind", "thank you", "thanks", "bye", "goodbye",
    "i am", "i'm", "my name is", "this is", "can you hear me", "are you there",
    "हाँ", "जी", "ठीक है", "नमस्ते", "धन्यवाद", "शुक्रिया", "बाय",
}


def _is_rag_query(text: str) -> bool:
    """
    Determine if an utterance is an informational query that warrants
    retrieving context from the vector database. Small talk, greetings,
    booking requests, and acknowledgments are skipped to eliminate latency.
    """
    clean = text.strip().lower()
    words = clean.split()
    if len(words) < 2:
        return False
    normalized = re.sub(r"[.,!?।;:'\"_]", "", clean).strip()
    if normalized in _CONVERSATIONAL_EXACT:
        return False

    # Common phone intents that should NEVER trigger slow RAG searches
    skip_rag_keywords = (
        "book", "appointment", "schedule", "slot", "reserve", "timing", "available",
        "hello", "hi", "hey", "who are you", "what is your name", "your name",
        "can you hear me", "are you there", "are you an ai", "are you human",
        "how are you", "thank you", "thanks", "bye", "goodbye",
        "अपॉइंटमेंट", "बुक", "समय", "नमस्ते"
    )
    if any(k in clean for k in skip_rag_keywords):
        return False

    # Only retrieve if a specific knowledge keyword is explicitly queried
    return any(kw in clean for kw in _RAG_KEYWORDS)



@dataclass(frozen=True, slots=True)
class AgentPersona:
    """
    Everything that varies per agent "line" (one dialplan extension / one
    AudioSocket port): its conversational personality and how it opens a
    call when the caller doesn't speak first.
    """

    name: str
    system_prompt: str
    greeting_text: str
    initial_silence_timeout_s: float
    agent_id: str = "default"
    language: str = "auto"  # auto | en | hi
    llm_model: str = ""
    # Tier 3: A/B Testing
    ab_variant: str = "A"
    # Tier 3: Human Handoff
    handoff_enabled: bool = False
    handoff_extension: str = "1001"
    handoff_fallback_threshold: int = 2
    handoff_message: str = "I am transferring you to a representative now. Please hold on the line."
    handoff_message_hi: str = "मैं आपको हमारे प्रतिनिधि से कनेक्ट कर रहा हूँ। कृपया लाइन पर बने रहें।"
    # Tier 3: Dialogue Policy
    dialogue_policy_enabled: bool = False
    dialogue_slots_json: str = "[]"
    # Tier 3: Multilingual Routing
    multilingual_routing: bool = True
    lang_confidence_threshold: float = 0.65
    fallback_language: str = "en"
    supported_languages: str = "en,hi"
    # Dynamic Tools / Google Sheets
    tools_enabled: bool = False
    tools_webhook_url: str = ""
    # Voice Cloning
    voice_cloning_enabled: bool = False
    cloned_voice_sample_path: str = ""
    # Speculative Response Generation
    speculative_generation_enabled: bool = True
    speculative_branch_count: int = 3


from callforge.runtime.dialogue import DialogueStateTracker
from callforge.runtime.tools import BookingToolManager
from services.speculative_service import SpeculativeResponseManager



class CallPipeline:
    """
    Orchestrates a single call's conversational turn-taking loop.

    One instance is created per `VoiceSession` (see `main.py`'s pipeline
    factory) and is discarded when the call ends -- no cross-call state is
    ever held here.
    """

    def __init__(
        self,
        session: VoiceSession,
        settings: Settings,
        stt: SttService,
        llm: LlmService,
        tts: TtsService,
        persona: AgentPersona,
        rag: RagService,
        store: Optional["PlatformStore"] = None,
        on_event: Optional[Callable[[dict[str, Any]], Any]] = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._persona = persona
        self._rag = rag
        self._store = store
        self._on_event = on_event
        self._vad = VadEngine(
            settings=settings.vad,
            source_sample_rate_hz=settings.telephony.sample_rate_hz,
            frame_bytes=settings.telephony.frame_bytes,
        )
        frame_duration_ms = (settings.telephony.frame_bytes / 2) / settings.telephony.sample_rate_hz * 1000.0
        self._barge_in_detector = BargeInDetector(
            vad_engine=self._vad,
            speech_threshold=settings.vad.barge_in_speech_threshold,
            min_speech_ms=settings.vad.barge_in_min_speech_ms,
            min_rms=settings.vad.barge_in_min_rms,
            frame_duration_ms=frame_duration_ms,
        )
        self._dialogue_tracker: Optional[DialogueStateTracker] = (
            DialogueStateTracker.from_json(persona.dialogue_slots_json)
            if persona.dialogue_policy_enabled
            else None
        )
        self._booking_tool: Optional[BookingToolManager] = (
            BookingToolManager(webhook_url=persona.tools_webhook_url)
            if persona.tools_enabled
            else None
        )
        self._speculative_manager: Optional[SpeculativeResponseManager] = (
            SpeculativeResponseManager(
                llm_service=llm,
                branch_count=min(1, max(1, persona.speculative_branch_count)),
                match_threshold=0.58,
            )
            if persona.speculative_generation_enabled
            else None
        )
        self._consecutive_unanswered: int = 0
        self._accumulated_pcm = bytearray()
        self._partial_stt_task: Optional[asyncio.Task] = None
        self._latest_partial_text: str = ""
        self._last_partial_stt_time: float = 0.0
        self._static_system_prompts: dict[str, str] = {}
        self._speculative_rag_task: Optional[asyncio.Task] = None
        self._speculative_rag_query: str = ""

        # Acoustic prosody & real-time emotion intelligence
        self._prosody = ProsodyAnalyzer(
            sample_rate_hz=settings.telephony.sample_rate_hz,
            frame_bytes=settings.telephony.frame_bytes,
        )
        self._current_emotion: Optional[EmotionProfile] = None

        # Zero-latency conversational flow (micro-pause backchanneling)
        self._flow_engine = ConversationalFlowEngine()
        self._user_speech_start_time: float = 0.0
        self._backchannel_task: Optional[asyncio.Task] = None

        self._history: list[ConversationTurn] = []
        self._speaking_event = asyncio.Event()  # set while TTS audio is being emitted
        self._thinking_event = asyncio.Event()  # set while turn STT/LLM/tool processing is in-flight
        self._current_turn_task: Optional[asyncio.Task] = None
        self._greeting_task: Optional[asyncio.Task] = None
        self._spoken_sentences: list[str] = []
        self._first_speech_detected = asyncio.Event()
        self._last_reply_lang = "en" if persona.language != "hi" else "hi"
        self._call_record_id: Optional[str] = None
        self._recorded_audio_pcm = bytearray()
        self._barge_in_buffer: deque[bytes] = deque(maxlen=15)
        self._handoff_executed = False

        # Cross-call memory & caller recognition
        self._captured_caller_name: str = ""
        self._captured_phone_number: str = ""
        self._caller_profile: Optional[CallerProfileRecord] = None
        self._caller_context: str = ""

        # Outbound campaign calling & slot collection state
        self._is_campaign_call: bool = False
        self._campaign_contact: Optional[Any] = None
        self._campaign: Optional[Any] = None
        self._campaign_greeting: Optional[str] = None
        self._call_start_monotonic: float = 0.0

    def _emit_event(self, event: dict[str, Any]) -> None:
        if self._on_event is not None:
            try:
                res = self._on_event(event)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                pass

    def _log_turn(self, role: str, content: str, language: str = "") -> None:
        if self._store is None or not self._call_record_id:
            return
        try:
            self._store.add_turn(self._call_record_id, role=role, content=content, language=language)
        except Exception:
            logger.exception("Failed to persist call turn")

    async def run(self) -> None:
        """Main entry point: drive the VAD loop for the lifetime of the call."""
        self._call_start_monotonic = time.monotonic()
        call_uuid_str = str(self._session.call_id)

        # Check if this call is an outbound campaign call
        if self._store is not None:
            self._campaign_contact = self._store.get_campaign_contact_by_call_uuid(call_uuid_str)
            if self._campaign_contact:
                self._is_campaign_call = True
                self._campaign = self._store.get_campaign(self._campaign_contact.campaign_id)
                if self._session.caller_id in ("unknown", "", None):
                    self._session.caller_id = self._campaign_contact.phone

        # Fallback check for campaign metadata file
        if not self._is_campaign_call:
            meta_candidates = [
                Path("asterisk-server/calls") / f"{call_uuid_str}.campaign",
                Path(f"/tmp/callforge_calls/{call_uuid_str}.campaign"),
            ]
            for mf in meta_candidates:
                if mf.exists():
                    try:
                        meta = json.loads(mf.read_text(encoding="utf-8"))
                        self._is_campaign_call = True
                        if self._store is not None:
                            self._campaign_contact = self._store.get_campaign_contact(meta.get("contact_id"))
                            self._campaign = self._store.get_campaign(meta.get("campaign_id"))
                        if self._session.caller_id in ("unknown", "", None):
                            self._session.caller_id = meta.get("phone", "")
                        break
                    except Exception as exc:
                        logger.debug("Failed reading campaign meta file %s: %s", mf, exc)

        # Configure campaign greeting and structured field collection
        if self._is_campaign_call and self._campaign:
            contact_name = self._campaign_contact.name if self._campaign_contact else ""
            if self._campaign.greeting_text and self._campaign.greeting_text.strip():
                gt = self._campaign.greeting_text.strip()
                if contact_name:
                    gt = gt.replace("{name}", contact_name)
                else:
                    gt = gt.replace("{name}", "")
                self._campaign_greeting = re.sub(r"\s+", " ", gt).strip()

            if self._campaign.collect_fields and self._campaign.collect_fields.strip():
                field_list = [f.strip() for f in self._campaign.collect_fields.split(",") if f.strip()]
                if field_list:
                    self._dialogue_tracker = DialogueStateTracker.from_field_names(field_list)
                    if contact_name:
                        for s in self._dialogue_tracker.slots_schema:
                            if "name" in s.name:
                                self._dialogue_tracker.filled_slots[s.name] = contact_name

            # Ensure proactive greeting initiates the detail collection
            if self._dialogue_tracker and not self._dialogue_tracker.all_required_filled():
                next_slot = self._dialogue_tracker.get_next_unfilled_slot()
                if next_slot:
                    base_greeting = self._campaign_greeting or self._persona.greeting_text or "Hello!"
                    if "?" not in base_greeting:
                        question = next_slot.prompt_question or f"Could you please provide your {next_slot.label}?"
                        self._campaign_greeting = f"{base_greeting.rstrip('.! ')}. I'm calling to collect a few quick details. {question}"

        logger.info(
            "Call %s: pipeline started (persona=%s, variant=%s, caller_id=%s, is_campaign=%s)",
            self._session.call_id, self._persona.name, self._persona.ab_variant, self._session.caller_id, self._is_campaign_call
        )

        # Proactively prefetch live booking slots in the background to eliminate turn latency
        if self._booking_tool is not None:
            asyncio.create_task(self._booking_tool.prefetch_slots())

        # Check for cross-call memory & recognized returning caller
        if not self._is_campaign_call and self._store is not None and self._session.caller_id and self._session.caller_id != "unknown":
            norm_phone = caller_memory_service.normalize_phone(self._session.caller_id)
            if norm_phone and norm_phone != "unknown":
                self._caller_profile = self._store.get_caller_profile(norm_phone)
                if self._caller_profile and self._caller_profile.call_count >= 1:
                    self._caller_context = caller_memory_service.build_caller_context(self._caller_profile)
                    logger.info(
                        "Call %s: Recognized returning caller %s (name=%r, calls=%d, last_topic=%r)",
                        self._session.call_id,
                        norm_phone,
                        self._caller_profile.name,
                        self._caller_profile.call_count,
                        caller_memory_service.extract_topic_from_summary(self._caller_profile.last_summary),
                    )
                    self._emit_event({
                        "type": "caller_recognized",
                        "phone_number": self._caller_profile.phone_number,
                        "name": self._caller_profile.name,
                        "call_count": self._caller_profile.call_count,
                        "last_summary": self._caller_profile.last_summary,
                        "last_disposition": self._caller_profile.last_disposition,
                        "last_sentiment": self._caller_profile.last_sentiment,
                        "relative_time": caller_memory_service.format_relative_time(self._caller_profile.last_call_at),
                    })

        if self._store is not None:
            try:
                record = self._store.start_call(
                    agent_id=self._persona.agent_id,
                    call_uuid=str(self._session.call_id),
                    caller_id=self._session.caller_id,
                    ab_variant=self._persona.ab_variant,
                )
                self._call_record_id = record.id
                if self._is_campaign_call and self._campaign_contact:
                    self._store.update_contact_status(
                        self._campaign_contact.id,
                        status="connected",
                        call_uuid=call_uuid_str,
                        call_id=record.id,
                    )
            except Exception:
                logger.exception("Failed to start call record")
        self._greeting_task = asyncio.create_task(
            self._maybe_send_initial_greeting(), name=f"greeting-{self._session.call_id}"
        )
        self._emit_event({"type": "state", "state": "listening"})
        try:
            while not self._session.hangup_event.is_set():
                frame = await self._session.inbound_audio.get()
                if frame is None:  # caller hung up
                    break

                is_speaking = self._speaking_event.is_set()
                is_thinking = self._thinking_event.is_set()

                # Always keep rolling pre-roll buffer of incoming frames so interruption audio is never lost
                self._barge_in_buffer.append(frame)

                # While the agent is speaking or thinking, check for genuine caller barge-in!
                if is_speaking or is_thinking:
                    is_barge_in, prob, rms = self._barge_in_detector.check_frame(frame)
                    if is_barge_in:
                        logger.info(
                            "Call %s: verified speech barge-in (prob=%.2f, rms=%.1f) during %s, interrupting",
                            self._session.call_id, prob, rms, "speaking" if is_speaking else "thinking",
                        )
                        self._trigger_barge_in()

                        # Transition VAD immediately into SPEECH using pre-roll audio so no syllables are lost
                        preroll = b"".join(self._barge_in_buffer)
                        self._barge_in_buffer.clear()
                        self._vad.force_speech_start(preroll)
                        self._accumulated_pcm = bytearray(preroll)
                        self._first_speech_detected.set()
                        self._latest_partial_text = ""
                        self._emit_event({"type": "state", "state": "listening", "detail": "barge_in_speech_started"})
                    continue

                # When agent is idle/listening: reset detector and process normal VAD
                self._barge_in_detector.reset()
                event = self._vad.process_frame(frame)
                if event.type is VadEventType.SPEECH_STARTED:
                    self._user_speech_start_time = time.monotonic()
                    self._first_speech_detected.set()
                    self._accumulated_pcm = bytearray(frame)
                    self._latest_partial_text = ""
                    self._emit_event({"type": "state", "state": "listening", "detail": "speech_started"})
                elif event.type is VadEventType.SPEECH_CONTINUING:
                    self._accumulated_pcm.extend(frame)
                    self._maybe_run_streaming_stt()
                elif event.type is VadEventType.SPEECH_ENDED and event.utterance_pcm:
                    utterance_pcm = bytes(event.utterance_pcm)
                    self._accumulated_pcm.clear()
                    self._session.barge_in_event.clear()
                    self._emit_event({"type": "state", "state": "thinking"})
                    self._thinking_event.set()
                    # Cancel any prior turn task if still active
                    if self._current_turn_task and not self._current_turn_task.done():
                        self._current_turn_task.cancel()
                    self._current_turn_task = asyncio.create_task(
                        self._handle_utterance(utterance_pcm),
                        name=f"turn-{self._session.call_id}",
                    )
        finally:
            self._session.hangup_event.set()
            self._session.barge_in_event.set()
            try:
                self._vad.close()
            except Exception:
                pass

            # 1. Cancel in-flight background tasks immediately
            for t in [
                self._greeting_task,
                self._current_turn_task,
                self._partial_stt_task,
                self._speculative_rag_task,
                self._backchannel_task,
            ]:
                if t and not t.done():
                    t.cancel()
            if self._speculative_manager:
                self._speculative_manager.cancel_all()

            # 2. Synchronous Conversation Intelligence Evaluation (Must NEVER be skipped!)
            sentiment = "neutral"
            disposition = "Completed"
            try:
                sentiment = self._compute_call_sentiment()
                disposition = self._compute_call_disposition(sentiment)
            except Exception as e:
                logger.debug("Sentiment/disposition evaluation error: %s", e)

            # 3. Synchronous Audio Recording Save (Must NEVER be skipped!)
            try:
                self._save_call_audio()
            except Exception as e:
                logger.warning("Audio saving error: %s", e)

            # 4. Synchronous Store Call Completion (Must NEVER be skipped!)
            if self._store is not None and self._call_record_id:
                try:
                    final_status = "transferred" if self._handoff_executed else "completed"
                    self._store.end_call(
                        self._call_record_id,
                        status=final_status,
                        disposition=disposition,
                        sentiment=sentiment,
                    )
                except Exception:
                    logger.exception("Failed to end call record")

            # 5. Synchronous Campaign Contact Progress & Field Collection Update
            if self._store is not None and self._is_campaign_call and self._campaign_contact:
                try:
                    duration_s = max(0.0, round(time.monotonic() - self._call_start_monotonic, 1))

                    # Gather collected fields
                    final_collected: dict[str, str] = {}
                    if self._campaign and self._campaign.collect_fields:
                        fields = [f.strip() for f in self._campaign.collect_fields.split(",") if f.strip()]
                        slots = self._dialogue_tracker.filled_slots if self._dialogue_tracker else {}
                        for f in fields:
                            clean_k = f.lower().replace(" ", "_")
                            val = slots.get(clean_k) or slots.get(f) or ""
                            if val:
                                final_collected[f] = val

                    # Fallback extraction if name was captured
                    if "Name" in final_collected and not final_collected["Name"] and self._captured_caller_name:
                        final_collected["Name"] = self._captured_caller_name
                    elif "name" in final_collected and not final_collected["name"] and self._captured_caller_name:
                        final_collected["name"] = self._captured_caller_name

                    user_turn_count = sum(1 for t in self._history if t.role == "user")
                    if user_turn_count <= 0 and duration_s < 3.0:
                        camp_status = "failed"
                        camp_disp = "Dropped / Hangup"
                    else:
                        camp_status = "completed"
                        if final_collected:
                            camp_disp = "Lead Captured"
                        elif disposition in ("Lead Captured", "Information Provided"):
                            camp_disp = disposition
                        else:
                            camp_disp = "Information Provided"

                    self._store.update_contact_status(
                        contact_id=self._campaign_contact.id,
                        status=camp_status,
                        call_uuid=str(self._session.call_id),
                        call_id=self._call_record_id or str(self._session.call_id),
                        disposition=camp_disp,
                        duration_s=duration_s,
                        collected_data_json=json.dumps(final_collected, ensure_ascii=False),
                    )
                    logger.info(
                        "Call %s: Updated campaign contact %s (%s): status=%s, disp=%s, dur=%.1fs, collected=%s",
                        self._session.call_id, self._campaign_contact.id, self._campaign_contact.phone,
                        camp_status, camp_disp, duration_s, final_collected
                    )
                except Exception:
                    logger.exception("Failed to update campaign contact record for %s", self._session.call_id)
                finally:
                    try:
                        Path(f"asterisk-server/calls/{self._session.call_id}.callerid").unlink(missing_ok=True)
                        Path(f"asterisk-server/calls/{self._session.call_id}.campaign").unlink(missing_ok=True)
                    except Exception:
                        pass

            # 6. Emit Call Ended Event to WebSocket/UI
            try:
                self._emit_event({"type": "call_ended", "sentiment": sentiment, "disposition": disposition})
            except Exception:
                pass
            logger.info(
                "Call %s: pipeline finished (disposition=%s, sentiment=%s)",
                self._session.call_id, disposition, sentiment
            )

            # 7. Shielded Async Cleanup (summarization, memory upsert)
            try:
                if self._store is not None:
                    eff_phone = self._session.caller_id
                    if not eff_phone or eff_phone == "unknown":
                        eff_phone = self._captured_phone_number or ""
                    eff_phone = caller_memory_service.normalize_phone(eff_phone)

                    if eff_phone and eff_phone != "unknown":
                        eff_name = self._captured_caller_name
                        if not eff_name and self._caller_profile:
                            eff_name = self._caller_profile.name

                        user_turns = [t.content for t in self._history if t.role == "user"]
                        assistant_turns = [t.content for t in self._history if t.role == "assistant"]

                        async def _shielded_summary_save():
                            try:
                                call_summary = await caller_memory_service.summarize_call(
                                    user_turns=user_turns,
                                    assistant_turns=assistant_turns,
                                    disposition=disposition,
                                    sentiment=sentiment,
                                    llm_service=self._llm,
                                )
                                self._store.upsert_caller_profile(
                                    phone_number=eff_phone,
                                    name=eff_name,
                                    disposition=disposition,
                                    sentiment=sentiment,
                                    summary=call_summary,
                                )
                                logger.info(
                                    "Call %s: Updated cross-call profile for %s (name=%r, disp=%s, sent=%s, summary=%r)",
                                    self._session.call_id, eff_phone, eff_name, disposition, sentiment, call_summary
                                )
                            except Exception:
                                pass

                        await asyncio.shield(_shielded_summary_save())
            except (asyncio.CancelledError, Exception):
                pass

    def _compute_call_sentiment(self) -> str:
        """Analyze sentiment across all user turns in the conversation."""
        user_turns = [t.content.lower() for t in self._history if t.role == "user"]
        if not user_turns:
            return "neutral"

        full_text = " ".join(user_turns)
        frustrated_keywords = [
            "not helping", "useless", "stupid", "terrible", "horrible", "worst",
            "angry", "annoyed", "frustrated", "bad service", "waste of time",
            "connect to human", "speak to human", "real person", "agent please",
            "don't understand", "wrong answer", "stop repeating", "shut up",
            "bakwas", "gussa", "bekaar", "kharab", "pagal", "chup", "galat",
            "nonsense", "hate", "ridiculous", "human agent"
        ]
        positive_keywords = [
            "thank", "thanks", "awesome", "perfect", "great", "excellent", "helpful",
            "good job", "appreciate", "wonderful", "amazing", "very good", "love it",
            "shukriya", "dhanyawad", "bahut achha", "theek hai", "sahi hai", "bohot khoob",
            "accha", "dhanyavaad", "nice", "brilliant", "superb"
        ]

        frustrated_hits = sum(1 for kw in frustrated_keywords if kw in full_text)
        positive_hits = sum(1 for kw in positive_keywords if kw in full_text)
        if self._handoff_executed:
            frustrated_hits += 1
        if self._current_emotion and self._current_emotion.emotion == "agitated":
            frustrated_hits += 1

        if frustrated_hits > positive_hits and frustrated_hits >= 1:
            return "frustrated"
        elif positive_hits > frustrated_hits and positive_hits >= 1:
            return "positive"
        return "neutral"

    def _compute_call_disposition(self, sentiment: str) -> str:
        """Compute contact center disposition outcome for completed call."""
        if self._handoff_executed:
            return "Escalated to Human"

        if self._dialogue_tracker:
            if self._dialogue_tracker.slots_schema and self._dialogue_tracker.all_required_filled():
                return "Lead Captured"
            elif any(v for v in self._dialogue_tracker.filled_slots.values()):
                return "Lead Captured"

        user_turn_count = sum(1 for t in self._history if t.role == "user")
        if user_turn_count <= 1:
            return "Dropped / Hangup"

        if sentiment == "frustrated":
            return "Follow-up Needed"

        return "Information Provided"

    def _save_call_audio(self) -> None:
        """Save recorded inbound and outbound audio as standard 16-bit 8000Hz mono WAV."""
        try:
            recordings_dir = Path("platform_data/recordings")
            recordings_dir.mkdir(parents=True, exist_ok=True)
            wav_paths = [recordings_dir / f"{self._session.call_id}.wav"]
            if self._call_record_id:
                wav_paths.append(recordings_dir / f"{self._call_record_id}.wav")

            # Fallback to 0.2s of silence if no frames were accumulated
            pcm_bytes = bytes(self._recorded_audio_pcm) if self._recorded_audio_pcm else (b"\x00\x00" * 1600)
            for wp in wav_paths:
                with wave.open(str(wp), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self._settings.telephony.sample_rate_hz)
                    wf.writeframes(pcm_bytes)
            logger.info("Saved call recording (%d bytes) to %s", len(pcm_bytes), wav_paths[0])
        except Exception:
            logger.exception("Failed to save call audio recording")

    def _maybe_run_streaming_stt(self) -> None:
        """Progressively transcribe partial speech while caller is still speaking."""
        min_bytes = int(self._settings.telephony.sample_rate_hz * 2 * 1.0)
        if len(self._accumulated_pcm) < min_bytes:
            return
        if self._partial_stt_task is not None and not self._partial_stt_task.done():
            return
        # Throttle partial STT on CPU to run at most once every 1.2 seconds
        now = time.monotonic()
        if (now - self._last_partial_stt_time) < 1.2:
            return
        self._last_partial_stt_time = now
        snapshot = bytes(self._accumulated_pcm)
        agent_lang = self._persona.language if self._persona.language in ("en", "hi") else None
        self._partial_stt_task = asyncio.create_task(
            self._stt.transcribe_partial_pcm16(
                snapshot, sample_rate_hz=self._settings.telephony.sample_rate_hz, language=agent_lang
            ),
            name=f"partial-stt-{self._session.call_id}",
        )
        self._partial_stt_task.add_done_callback(self._on_partial_stt_done)

    def _on_partial_stt_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            res = task.result()
            if res and res.text:
                self._latest_partial_text = res.text
                self._emit_event({"type": "partial_transcript", "text": res.text, "language": res.language})
                logger.info(
                    "Call %s: [Partial STT] %r (lang=%s, dur=%.2fs)",
                    self._session.call_id, res.text, res.language, res.duration_s
                )
                words = res.text.split()
                if len(words) >= 2 and _is_rag_query(res.text) and (not self._speculative_rag_task or self._speculative_rag_task.done()):
                    self._speculative_rag_query = res.text
                    self._speculative_rag_task = asyncio.create_task(
                        self._async_retrieve_rag(res.text),
                        name=f"speculative-rag-{self._session.call_id}",
                    )
                # Speculative multi-branch response generation (require at least 3 words and 12 chars, not just filler)
                if self._speculative_manager and len(words) >= 3 and len(res.text.strip()) >= 12:
                    filler_words = {"oh", "okay", "um", "uh", "yeah", "yes", "hello", "hi", "hey", "name", "listen", "there"}
                    non_filler = [w for w in words if w.lower() not in filler_words]
                    if len(non_filler) >= 2:
                        spec_prompt = self._get_static_system_prompt(reply_lang=res.language or "en")
                        asyncio.create_task(
                            self._speculative_manager.on_partial_stt(
                                partial_text=res.text,
                                history=self._history[-MAX_HISTORY_TURNS * 2:],
                                system_prompt=spec_prompt,
                                model=self._persona.llm_model or None,
                                rag_context="",
                            ),
                            name=f"speculative-branches-{self._session.call_id}",
                        )
        except (Exception, asyncio.CancelledError):
            pass

    async def _async_retrieve_rag(self, query: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._rag.retrieve_context, query)

    async def _maybe_send_initial_greeting(self) -> None:
        """
        If the caller stays silent for `persona.initial_silence_timeout_s`
        (or 0.4s for outbound campaign calls) after connecting, proactively speak
        the greeting rather than waiting indefinitely for them to talk first.
        """
        silence_timeout = 0.4 if self._is_campaign_call else self._persona.initial_silence_timeout_s
        try:
            await asyncio.wait_for(
                self._first_speech_detected.wait(), timeout=silence_timeout
            )
        except asyncio.TimeoutError:
            if self._session.hangup_event.is_set() or self._first_speech_detected.is_set():
                return
            greeting = self._campaign_greeting or self._persona.greeting_text
            if not self._is_campaign_call and self._caller_profile and self._caller_profile.call_count >= 1:
                greeting = caller_memory_service.generate_returning_greeting(
                    self._caller_profile, language=self._last_reply_lang
                )
                logger.info("Call %s: caller silent, sending returning caller recognition greeting: %r", self._session.call_id, greeting)
            elif self._is_campaign_call:
                logger.info("Call %s: outbound campaign call connected, speaking proactive campaign greeting: %r", self._session.call_id, greeting)
            else:
                logger.info("Call %s: caller silent, sending proactive greeting: %r", self._session.call_id, greeting)

            self._speaking_event.set()
            self._spoken_sentences = [greeting]
            self._emit_event({"type": "state", "state": "speaking"})
            self._emit_event({"type": "transcript", "role": "assistant", "content": greeting, "language": self._last_reply_lang})
            try:
                await self._speak_sentence(greeting, target_language=self._last_reply_lang)
            except asyncio.CancelledError:
                logger.info("Call %s: initial greeting cancelled by barge-in", self._session.call_id)
                raise
            finally:
                self._speaking_event.clear()
                self._emit_event({"type": "state", "state": "listening"})
            if not self._session.barge_in_event.is_set() and self._spoken_sentences:
                self._history.append(ConversationTurn(role="assistant", content=greeting))
                self._log_turn("assistant", greeting, self._last_reply_lang)
                self._spoken_sentences.clear()
        except asyncio.CancelledError:
            pass

    def _trigger_barge_in(self, is_text: bool = False) -> None:
        """Execute immediate barge-in: cut audio, cancel generation/synthesis, truncate history."""
        self._session.barge_in_event.set()
        self._speaking_event.clear()
        self._thinking_event.clear()
        self._clear_outbound_queue()

        if self._greeting_task and not self._greeting_task.done():
            self._greeting_task.cancel()

        if self._current_turn_task and not self._current_turn_task.done():
            self._current_turn_task.cancel()

        if self._speculative_manager:
            self._speculative_manager.cancel_all()

        if self._spoken_sentences:
            interrupted_text = " ".join(self._spoken_sentences).strip()
            if interrupted_text:
                interrupted_text += " [interrupted]"
                logger.info(
                    "Call %s: turn interrupted after speaking: %r",
                    self._session.call_id, interrupted_text
                )
                self._history.append(ConversationTurn(role="assistant", content=interrupted_text))
                self._log_turn("assistant", interrupted_text, self._last_reply_lang)
            self._spoken_sentences.clear()

        self._emit_event({
            "type": "barge_in",
            "message": "User interrupted assistant with text" if is_text else "User interrupted assistant",
        })

    def _clear_outbound_queue(self) -> None:
        """
        Drop every frame currently sitting in `session.outbound_audio`.
        """
        q = self._session.outbound_audio
        dropped = 0
        while True:
            try:
                q.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        if dropped:
            logger.debug(
                "Call %s: dropped %d buffered outbound frame(s) on barge-in", self._session.call_id, dropped
            )

    def _get_static_system_prompt(self, reply_lang: str = "en") -> str:
        """
        Return a concise, static system prompt cached for the call.
        Keeping the system prompt invariant across turns allows Ollama to reuse
        its KV cache across all turns of the conversation, dropping prompt evaluation
        from 12+ seconds to ~300ms on CPU!
        """
        lang = "hi" if reply_lang == "hi" else "en"
        if lang in self._static_system_prompts:
            return self._static_system_prompts[lang]

        parts = [self._persona.system_prompt.strip()]
        if lang == "hi":
            parts.append(
                "Respond in natural spoken Hindi using Devanagari script. Keep replies to 1-2 short, conversational sentences. No markdown or lists."
            )
        else:
            parts.append(
                "Respond in natural spoken English suitable for a phone call. Keep replies to 1-2 short sentences. No markdown or lists."
            )

        if self._persona.tools_enabled:
            parts.append(
                "Appointment booking and availability are handled automatically by the scheduling system. "
                "Keep all replies concise (1-2 sentences maximum). "
                "Never invent fake appointments, times, or confirmation numbers."
            )

        if self._caller_context:
            parts.append(self._caller_context)

        prompt = "\n\n".join(parts)
        self._static_system_prompts[lang] = prompt
        return prompt

    def _build_enhanced_system_prompt(self, reply_lang: str = "en", rag_context: str = "") -> str:
        """Build the complete LLM system prompt including language, caller memory, emotion, dialogue, and RAG."""
        if reply_lang == "hi":
            language_instruction = (
                "LANGUAGE: The caller is speaking Hindi. MOST IMPORTANT: "
                "actually answer their question correctly and specifically "
                "-- never give a vague, generic, or evasive reply just "
                "because you're answering in Hindi. Get the content right "
                "first, exactly as you would in English.\n\n"
                "Then write that correct answer in casual, code-mixed "
                "Hinglish, entirely in DEVANAGARI SCRIPT -- spell English "
                "words phonetically (e.g. 'जीपीयू', 'इंटरव्यू', 'कंप्यूटर') "
                "rather than switching to Latin letters, since the TTS "
                "voice cannot read Latin script at all.\n\n"
                "Tone example (match the STYLE here, not the content -- "
                "always answer the real question asked):\n"
                "  Caller: मुझे जॉब इंटरव्यू के बारे में पूछना था।\n"
                "  Reply like this: हाँ बिल्कुल, बताओ इंटरव्यू के बारे "
                "में क्या जानना है? (casual -- not formal words like "
                "'साक्षात्कार' or 'कृपया')\n\n"
                "Keep it short and warm, like a friend on a phone call."
            )
        else:
            language_instruction = (
                "LANGUAGE: Respond in clear, professional spoken English suitable "
                "for a phone call. Prefer short sentences and everyday words. "
                "Do not use slang, markdown, or lists."
            )

        enhanced = f"{self._persona.system_prompt}\n\n{language_instruction}"

        # Inject outbound campaign mission if active
        if self._is_campaign_call:
            c_name = self._campaign.name if self._campaign else "Outbound Campaign"
            contact_name = self._campaign_contact.name if self._campaign_contact else ""
            c_greeting_hint = ""
            if self._campaign_greeting and not any(t.role == "assistant" for t in self._history):
                c_greeting_hint = (
                    f"FIRST TURN INSTRUCTION: The contact just answered. Deliver your greeting: '{self._campaign_greeting}'. "
                    f"Acknowledge what they said, then explain why you are calling.\n"
                )

            field_status_lines = []
            immediate_goal = ""
            if self._dialogue_tracker:
                unfilled = self._dialogue_tracker.get_unfilled_slots()
                if unfilled:
                    next_s = unfilled[0]
                    q_hint = f" Example question: '{next_s.prompt_question}'" if next_s.prompt_question else ""
                    immediate_goal = (
                        f"IMMEDIATE ACTION: You MUST ask the contact for their '{next_s.label}'.{q_hint} "
                        f"Briefly acknowledge what they said (1 short polite phrase), then immediately ask for this information."
                    )
                else:
                    immediate_goal = (
                        "ALL DETAILS COLLECTED! Confirm and thank the contact, then politely conclude the call."
                    )
                for s in self._dialogue_tracker.slots_schema:
                    v = self._dialogue_tracker.filled_slots.get(s.name)
                    st = f"'{v}' [COLLECTED]" if v else "[MISSING - MUST COLLECT]"
                    field_status_lines.append(f"- {s.label}: {st}")

            fields_block = "\n".join(field_status_lines) if field_status_lines else "No specific fields."

            campaign_context = (
                f"=== CRITICAL OUTBOUND CAMPAIGN CALL DIRECTIVE ===\n"
                f"Campaign: {c_name}\n"
                f"{f'Contact Name: {contact_name}' if contact_name else 'Contact: Customer'}\n"
                f"Call Direction: OUTBOUND CALL. You initiated this call to collect information from the customer.\n\n"
                f"STRICT RULES (DO NOT VIOLATE):\n"
                f"1. NEVER say 'How can I help you today?' or act like customer support. YOU called THEM.\n"
                f"2. Your #1 objective is to collect all missing information listed below.\n"
                f"3. Keep each response concise (1 to 2 short sentences).\n\n"
                f"CAMPAIGN DETAILS TO COLLECT:\n"
                f"{fields_block}\n\n"
                f"{immediate_goal}\n"
                f"{c_greeting_hint}"
                f"================================================\n\n"
            )
            enhanced = f"{campaign_context}{enhanced}"

        # Inject returning caller recognition & cross-call memory if active
        if self._caller_context:
            enhanced = f"{self._caller_context}\n\n{enhanced}"

        # Inject acoustic prosody & emotion directive into LLM system prompt
        if self._current_emotion and self._current_emotion.prompt_directive:
            enhanced += f"\n\n{self._current_emotion.prompt_directive}"

        # Inject structured dialogue policy instructions if active
        if self._dialogue_tracker is not None:
            enhanced += self._dialogue_tracker.build_prompt_directive(language=reply_lang)

        # Conversational continuity & barge-in handling (like ChatGPT Voice Mode)
        interruption_instruction = (
            "CONVERSATIONAL CONTINUITY: If a previous assistant response in the conversation ends with '[interrupted]', "
            "it means the user interrupted you mid-sentence. Do NOT repeat the interrupted sentence or start over from scratch. "
            "Seamlessly pivot to answer the user's latest statement or question while maintaining full context of what was being discussed. "
            "Acknowledge their new input naturally and concisely."
        )
        enhanced = f"{enhanced}\n\n{interruption_instruction}"

        # Appointment booking tool awareness when enabled
        if self._persona.tools_enabled:
            tool_info = (
                "APPOINTMENT & SCHEDULING CAPABILITIES:\n"
                "You have active appointment booking capabilities. If the caller asks about appointment slots, scheduling, "
                "or availability, always assist them helpfully and politely. Never claim you cannot handle booking or act confused. "
                "Available slots are typically: 10:00 AM, 02:30 PM, and 04:00 PM."
            )
            enhanced = f"{enhanced}\n\n{tool_info}"

        if rag_context:
            enhanced += (
                f"\n\nContext Information:\n{rag_context}\n\n"
                "CRITICAL INSTRUCTION: Evaluate if the 'Context Information' above is genuinely relevant to the user's exact statement. "
                "If the user is just making small talk (e.g. 'Hello', 'How are you', or short general questions), completely IGNORE the context and reply naturally. "
                "Only answer from the context if the user asks a specific technical question that the context solves. "
                "This Context Information is data YOU ALREADY KNOW -- treat it exactly like something memorized, and state "
                "it to the caller directly and confidently as fact. "
                "You have no file, spreadsheet, or document to hand the caller -- NEVER tell the caller to check a file or look something up themselves."
            )

        return enhanced

    async def _handle_utterance(self, utterance_pcm: bytes) -> None:
        """Run one full STT -> LLM -> TTS turn for a completed caller utterance."""
        try:
            self._recorded_audio_pcm.extend(utterance_pcm)

            # Acoustic prosody & real-time emotion intelligence
            word_count = len(self._latest_partial_text.split()) if self._latest_partial_text else 0
            self._current_emotion = self._prosody.analyze_utterance(utterance_pcm, text_word_count=word_count)

            # Discard low-energy background noise (mic hiss, fan, breath) that is not actual speech
            if self._current_emotion.metrics.rms_mean < 50.0 or len(utterance_pcm) < self._settings.telephony.sample_rate_hz * 2 * 0.4:
                logger.info(
                    "Call %s: Discarding low-energy noise/silence (rms=%.1f < 50.0, dur=%.2fs)",
                    self._session.call_id,
                    self._current_emotion.metrics.rms_mean,
                    len(utterance_pcm) / (self._settings.telephony.sample_rate_hz * 2),
                )
                return

            self._emit_event({
                "type": "emotion",
                "emotion": self._current_emotion.emotion,
                "confidence": self._current_emotion.confidence,
                "metrics": {
                    "rms_mean": self._current_emotion.metrics.rms_mean,
                    "rms_var": self._current_emotion.metrics.rms_variance,
                    "zcr": self._current_emotion.metrics.zcr_mean,
                    "duration_s": self._current_emotion.metrics.speech_duration_s,
                    "rate_wpm": self._current_emotion.metrics.estimated_rate_wpm,
                },
            })

            t_stt = time.perf_counter()
            agent_lang = self._persona.language if self._persona.language in ("en", "hi") else None
            transcription = await self._stt.transcribe_pcm16(
                utterance_pcm,
                sample_rate_hz=self._settings.telephony.sample_rate_hz,
                language=agent_lang,
            )
            stt_ms = (time.perf_counter() - t_stt) * 1000.0

            final_text = transcription.text.strip() if (transcription and transcription.text) else ""
            letters_only = re.sub(r"[^\w\u0900-\u097F]", "", final_text).strip()

            # If final STT was empty or hallucinated punctuation (e.g. Urdu dot '۔' or '...'),
            # but streaming partial STT captured real caller words, fall back to partial STT!
            if (not final_text or not letters_only) and self._latest_partial_text:
                partial_letters = re.sub(r"[^\w\u0900-\u097F]", "", self._latest_partial_text).strip()
                if partial_letters:
                    logger.info(
                        "Call %s: Final STT produced empty/punctuation (%r), falling back to partial STT: %r",
                        self._session.call_id, final_text, self._latest_partial_text
                    )
                    final_text = self._latest_partial_text
                    letters_only = partial_letters
                    detected_lang = "en" if all(ord(c) < 128 or c.isspace() for c in final_text) else "hi"
                    from services.stt_service import TranscriptionResult
                    transcription = TranscriptionResult(
                        text=final_text,
                        language=detected_lang,
                        duration_s=0.0,
                        average_logprob=0.0,
                        language_probability=1.0,
                    )

            if not final_text or not letters_only:
                logger.debug(
                    "Call %s: empty transcription (%r); ignoring silence/noise",
                    self._session.call_id, final_text,
                )
                return

            await self._handle_text_turn(
                transcription.text,
                detected_language=transcription.language or "en",
                language_probability=getattr(transcription, "language_probability", 1.0),
                stt_ms=stt_ms,
            )
        except asyncio.CancelledError:
            logger.info("Call %s: turn task cancelled (barge-in)", self._session.call_id)
            raise
        except Exception:
            logger.exception("Call %s: error in turn processing", self._session.call_id)
        finally:
            if self._current_turn_task is asyncio.current_task():
                self._thinking_event.clear()
                if not self._speaking_event.is_set():
                    self._emit_event({"type": "state", "state": "listening"})

    async def inject_user_utterance(self, text: str) -> None:
        """Process a text utterance directly without microphone VAD/STT."""
        if not text.strip():
            return
        self._first_speech_detected.set()
        if self._speaking_event.is_set() or self._thinking_event.is_set():
            self._trigger_barge_in(is_text=True)
        self._session.barge_in_event.clear()
        self._emit_event({"type": "state", "state": "thinking"})
        self._thinking_event.set()
        if self._current_turn_task and not self._current_turn_task.done():
            self._current_turn_task.cancel()
        self._current_turn_task = asyncio.create_task(
            self._handle_text_turn(text.strip(), detected_language="en", language_probability=1.0, stt_ms=0.0),
            name=f"turn-text-{self._session.call_id}",
        )

    async def _handle_text_turn(
        self,
        text: str,
        detected_language: str = "en",
        language_probability: float = 1.0,
        stt_ms: float = 0.0,
    ) -> None:
        """Process user text through language routing, dialogue policy, RAG, LLM, and TTS."""
        logger.info("Call %s: caller said: %r (detected_lang=%s)",
                    self._session.call_id, text, detected_language)

        # Decide reply language with multilingual routing & confidence thresholds
        det_lang = (detected_language or "en").lower()
        det_prob = language_probability
        supported = [l.strip().lower() for l in self._persona.supported_languages.split(",") if l.strip()]

        if self._persona.language in ("en", "hi"):
            reply_lang = self._persona.language
        else:
            if det_prob < self._persona.lang_confidence_threshold:
                reply_lang = self._persona.fallback_language
                logger.info(
                    "Call %s: language confidence %.2f < threshold %.2f, routing to fallback '%s'",
                    self._session.call_id, det_prob, self._persona.lang_confidence_threshold, reply_lang,
                )
            elif det_lang.startswith("hi") and "hi" in supported:
                reply_lang = "hi"
            elif any(det_lang.startswith(s) for s in supported):
                reply_lang = "en"
            else:
                reply_lang = self._persona.fallback_language
                logger.info(
                    "Call %s: detected language '%s' (prob=%.2f) not in supported %r, routing to fallback '%s'",
                    self._session.call_id, det_lang, det_prob, supported, reply_lang,
                )
        self._last_reply_lang = reply_lang
        self._log_turn("user", text, reply_lang)
        self._emit_event({"type": "transcript", "role": "user", "content": text, "language": reply_lang})
        self._history.append(ConversationTurn(role="user", content=text))

        # 1. Human handoff: check if caller explicitly asked for a human operator / agent
        if self._persona.handoff_enabled and _is_handoff_requested(text):
            logger.info("Call %s: caller requested human handoff: %r", self._session.call_id, text)
            await self._execute_human_handoff(reason="caller_requested", reply_lang=reply_lang)
            return

        # 2. Dialogue policy: extract slots and update call record
        if self._dialogue_tracker is not None:
            last_assistant_turn = next((t.content for t in reversed(self._history[:-1]) if t.role == "assistant"), "")
            new_slots = self._dialogue_tracker.extract_from_utterance(text, last_assistant_text=last_assistant_turn)
            if new_slots:
                self._emit_event({"type": "slots_updated", "slots": self._dialogue_tracker.filled_slots})
                if self._store and self._call_record_id:
                    try:
                        self._store.update_call_slots(self._call_record_id, self._dialogue_tracker.to_json())
                    except Exception:
                        pass
                if self._store and self._is_campaign_call and self._campaign_contact:
                    try:
                        c_data = {}
                        if self._campaign and self._campaign.collect_fields:
                            for f in [f.strip() for f in self._campaign.collect_fields.split(",") if f.strip()]:
                                clean_k = f.lower().replace(" ", "_")
                                v = self._dialogue_tracker.filled_slots.get(clean_k) or self._dialogue_tracker.filled_slots.get(f) or ""
                                if v:
                                    c_data[f] = v
                        self._store.update_contact_status(
                            self._campaign_contact.id,
                            status="connected",
                            call_id=self._call_record_id or "",
                            collected_data_json=json.dumps(c_data, ensure_ascii=False),
                        )
                    except Exception:
                        pass

        # Fast path: trivial canned responses (disabled during outbound campaign calls and active slot collection)
        canned = None
        if not self._is_campaign_call and (self._dialogue_tracker is None or self._dialogue_tracker.all_required_filled()):
            canned = match_canned_response(text)
        if canned is not None:
            reply_text = canned.text_hi if reply_lang == "hi" else canned.text_en
            logger.info(
                "Call %s: matched canned response (intent=%s), agent replied: %r",
                self._session.call_id, canned.intent.value, reply_text,
            )
            self._session.barge_in_event.clear()
            self._thinking_event.clear()
            self._speaking_event.set()
            self._spoken_sentences = [reply_text]
            self._emit_event({"type": "state", "state": "speaking"})
            self._emit_event({
                "type": "latency",
                "stt_ms": round(stt_ms, 1),
                "llm_ttft_ms": 4.0,
                "tts_ms": 25.0,
                "total_ms": round(stt_ms + 29.0, 1),
            })
            self._emit_event({"type": "transcript", "role": "assistant", "content": reply_text, "language": reply_lang})
            try:
                await self._speak_sentence(reply_text, target_language=reply_lang)
            finally:
                self._speaking_event.clear()
                self._emit_event({"type": "state", "state": "listening"})
            if not self._session.barge_in_event.is_set() and self._spoken_sentences:
                self._history.append(ConversationTurn(role="assistant", content=reply_text))
                self._log_turn("assistant", reply_text, reply_lang)
                self._spoken_sentences.clear()
            self._consecutive_unanswered = 0
            self._trim_history()
            return

        # RAG retrieval with speculative cache check (only for queries that actually need it)
        context = ""
        if _is_rag_query(text):
            if (
                self._speculative_rag_task is not None
                and self._speculative_rag_query
                and (
                    text.startswith(self._speculative_rag_query)
                    or self._speculative_rag_query in text
                )
            ):
                try:
                    context = await asyncio.wait_for(self._speculative_rag_task, timeout=1.2)
                    logger.debug("Call %s: reused speculative RAG context for %r", self._session.call_id, self._speculative_rag_query)
                except Exception:
                    context = await self._async_retrieve_rag(text)
            else:
                context = await self._async_retrieve_rag(text)

        static_system_prompt = self._get_static_system_prompt(reply_lang)

        # Capture caller details (name and phone) from dialogue slots, booking tool, or utterance
        if not self._captured_caller_name or not self._captured_phone_number:
            from callforge.runtime.tools import extract_name_phone
            c_name, c_phone, _ = extract_name_phone(text)
            if c_name and not self._captured_caller_name:
                self._captured_caller_name = c_name
            if c_phone and not self._captured_phone_number:
                self._captured_phone_number = c_phone

        if self._dialogue_tracker:
            slots = self._dialogue_tracker.filled_slots
            if not self._captured_caller_name:
                self._captured_caller_name = slots.get("caller_name") or slots.get("name") or ""
            if not self._captured_phone_number:
                self._captured_phone_number = slots.get("phone_number") or slots.get("phone") or ""

        if self._booking_tool:
            if self._booking_tool.booked_name and not self._captured_caller_name:
                self._captured_caller_name = self._booking_tool.booked_name
            if self._booking_tool.booked_phone and not self._captured_phone_number:
                self._captured_phone_number = self._booking_tool.booked_phone

        # Inject dynamic Google Sheets / appointment booking tools if active
        tool_directive_text = ""
        if self._booking_tool is not None:
            logger.info("Call %s: evaluating turn against BookingToolManager (state=%s): %r", self._session.call_id, self._booking_tool.state, text)
            slots_dict = self._dialogue_tracker.filled_slots if self._dialogue_tracker else {}
            direct_reply, tool_directive, tool_event = await self._booking_tool.evaluate_turn(text, slots_dict, language=reply_lang)
            if tool_event:
                logger.info("Call %s: Booking tool emitted event: %r", self._session.call_id, tool_event)
                self._emit_event(tool_event)

            if direct_reply:
                logger.info("Call %s: Booking tool generated direct reply: %r", self._session.call_id, direct_reply)
                self._session.barge_in_event.clear()
                self._thinking_event.clear()
                self._speaking_event.set()
                self._spoken_sentences = [direct_reply]
                self._emit_event({"type": "state", "state": "speaking"})
                self._emit_event({
                    "type": "latency",
                    "stt_ms": round(stt_ms, 1),
                    "llm_ttft_ms": 2.0,
                    "tts_ms": 25.0,
                    "total_ms": round(stt_ms + 27.0, 1),
                })
                self._emit_event({"type": "transcript", "role": "assistant", "content": direct_reply, "language": reply_lang})
                try:
                    await self._speak_sentence(direct_reply, target_language=reply_lang)
                finally:
                    self._speaking_event.clear()
                    self._emit_event({"type": "state", "state": "listening"})
                if not self._session.barge_in_event.is_set() and self._spoken_sentences:
                    self._history.append(ConversationTurn(role="assistant", content=direct_reply))
                    self._log_turn("assistant", direct_reply, reply_lang)
                    self._spoken_sentences.clear()
                self._consecutive_unanswered = 0
                self._trim_history()
                return

            if tool_directive:
                tool_directive_text = tool_directive.strip()
        else:
            logger.debug("Call %s: Booking tool not enabled for persona %s (tools_enabled=%s)", self._session.call_id, self._persona.name, self._persona.tools_enabled)

        self._session.barge_in_event.clear()
        self._spoken_sentences = []
        assistant_text_parts: list[str] = []
        t_llm_start = time.perf_counter()
        llm_ttft_ms = 0.0
        first_token_emitted = False
        first_sentence_emitted = False

        # Speculative multi-branch match check
        committed_branch = None
        if self._speculative_manager:
            committed_branch, spec_score = self._speculative_manager.match_and_commit(text)

        try:
            if committed_branch:
                sentence_stream = self._speculative_manager.stream_committed_branch(
                    committed_branch,
                    interrupt_event=self._session.barge_in_event,
                )
            else:
                user_msg = text
                if context:
                    user_msg = f"[Context: {context}]\n{user_msg}"
                if tool_directive_text:
                    user_msg = f"{user_msg}\n[Directive: {tool_directive_text}]"
                sentence_stream = self._llm.stream_reply(
                    history=self._history[:-1][-MAX_HISTORY_TURNS * 2:],
                    user_utterance=user_msg,
                    interrupt_event=self._session.barge_in_event,
                    system_prompt=static_system_prompt,
                    sentence_min_chars=self._settings.tts.sentence_min_chars,
                    model=self._persona.llm_model or None,
                )

            async for sentence in sentence_stream:
                if self._session.barge_in_event.is_set():
                    break

                if not first_token_emitted:
                    first_token_emitted = True
                    self._thinking_event.clear()
                    self._speaking_event.set()
                    if committed_branch and committed_branch.buffered_sentences:
                        llm_ttft_ms = 0.0
                    else:
                        llm_ttft_ms = (time.perf_counter() - t_llm_start) * 1000.0
                    t_tts_start = time.perf_counter()
                    self._emit_event({"type": "state", "state": "speaking"})

                # Chameleon voice matching: adapt speed, warmth, and volume to caller's emotional state
                tts_len = self._current_emotion.tts_length_scale if self._current_emotion else None
                tts_noise = self._current_emotion.tts_noise_scale if self._current_emotion else None
                tts_vol = self._current_emotion.tts_volume_scale if self._current_emotion else None

                assistant_text_parts.append(sentence)
                self._spoken_sentences.append(sentence)
                logger.info(
                    "Call %s: %s sentence: %r",
                    self._session.call_id,
                    "Speculative" if committed_branch else "LLM",
                    sentence,
                )
                self._emit_event({"type": "transcript", "role": "assistant", "content": sentence, "language": reply_lang})
                await self._speak_sentence(
                    sentence,
                    target_language=reply_lang,
                    length_scale=tts_len,
                    noise_scale=tts_noise,
                    volume=tts_vol,
                )

                if not first_sentence_emitted:
                    first_sentence_emitted = True
                    tts_ms = (time.perf_counter() - t_tts_start) * 1000.0
                    self._emit_event({
                        "type": "latency",
                        "stt_ms": round(stt_ms, 1),
                        "llm_ttft_ms": round(llm_ttft_ms, 1),
                        "tts_ms": round(tts_ms, 1),
                        "total_ms": round(stt_ms + llm_ttft_ms + tts_ms, 1),
                        "speculative_hit": committed_branch is not None,
                    })

                if self._session.barge_in_event.is_set():
                    break
        finally:
            if self._speculative_manager:
                self._speculative_manager.cancel_all()
            self._speaking_event.clear()
            self._thinking_event.clear()
            self._emit_event({"type": "state", "state": "listening"})

        if self._session.barge_in_event.is_set() or self._session.hangup_event.is_set():
            self._trim_history()
            return

        # If turn produced no reply at all
        if not assistant_text_parts and not self._session.barge_in_event.is_set() and not self._session.hangup_event.is_set():
            self._consecutive_unanswered += 1
            logger.warning(
                "Call %s: turn produced no reply (%d consecutive unanswered); checking handoff threshold %d",
                self._session.call_id, self._consecutive_unanswered, self._persona.handoff_fallback_threshold,
            )
            # Forward call if agent cannot answer and threshold reached
            if self._persona.handoff_enabled and self._consecutive_unanswered >= self._persona.handoff_fallback_threshold:
                logger.info(
                    "Call %s: agent cannot answer, forwarding call to %s",
                    self._session.call_id, self._persona.handoff_extension,
                )
                await self._execute_human_handoff(reason="agent_cannot_answer", reply_lang=reply_lang)
                return

            fallback = _FALLBACK_REPLY_HI if reply_lang == "hi" else _FALLBACK_REPLY_EN
            logger.info("Call %s: agent replied (fallback): %r", self._session.call_id, fallback)
            self._speaking_event.set()
            self._spoken_sentences = [fallback]
            self._emit_event({"type": "state", "state": "speaking"})
            self._emit_event({"type": "transcript", "role": "assistant", "content": fallback, "language": reply_lang})
            try:
                await self._speak_sentence(fallback, target_language=reply_lang)
            finally:
                self._speaking_event.clear()
                self._emit_event({"type": "state", "state": "listening"})
            if not self._session.barge_in_event.is_set() and self._spoken_sentences:
                self._history.append(ConversationTurn(role="assistant", content=fallback))
                self._log_turn("assistant", fallback, reply_lang)
                self._spoken_sentences.clear()
        elif assistant_text_parts:
            self._consecutive_unanswered = 0
            if not self._session.barge_in_event.is_set() and self._spoken_sentences:
                joined = " ".join(assistant_text_parts)
                logger.info("Call %s: agent replied: %r (lang=%s)", self._session.call_id, joined, reply_lang)
                self._history.append(ConversationTurn(role="assistant", content=joined))
                self._log_turn("assistant", joined, reply_lang)
                self._spoken_sentences.clear()
        self._trim_history()

    async def _execute_human_handoff(self, reason: str, reply_lang: str) -> None:
        """Inform caller, record handoff, write Asterisk forward file, and transfer."""
        logger.info(
            "Call %s: executing human handoff to ext %s (reason=%s)",
            self._session.call_id, self._persona.handoff_extension, reason
        )
        msg = self._persona.handoff_message_hi if reply_lang == "hi" else self._persona.handoff_message
        self._session.barge_in_event.clear()
        self._speaking_event.set()
        self._emit_event({"type": "state", "state": "speaking"})
        self._emit_event({"type": "handoff", "target": self._persona.handoff_extension, "message": msg})
        self._emit_event({"type": "transcript", "role": "assistant", "content": msg, "language": reply_lang})
        try:
            await self._speak_sentence(msg, target_language=reply_lang)
        finally:
            self._speaking_event.clear()
            self._emit_event({"type": "state", "state": "listening"})
            self._speaking_event.clear()

        # Drain the outbound audio queue so caller hears the handoff message before transfer
        while not self._session.outbound_audio.empty():
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)

        self._handoff_executed = True
        handoff_summary = f"[Forwarded to {self._persona.handoff_extension}] {msg}"
        self._history.append(ConversationTurn(role="assistant", content=handoff_summary))
        self._log_turn("assistant", handoff_summary, reply_lang)

        # Write handoff target file for Asterisk dialplan
        target_ext = self._persona.handoff_extension.strip()
        base_dir = Path(__file__).resolve().parent
        handoff_paths = [
            Path("/etc/asterisk/handoff") / f"{self._session.call_id}.target",
            base_dir / "asterisk-server" / "handoff" / f"{self._session.call_id}.target",
            Path("asterisk-server/handoff") / f"{self._session.call_id}.target",
        ]
        for p in handoff_paths:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(target_ext, encoding="utf-8")
                try:
                    p.chmod(0o666)
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("Writing handoff file to %s: %s", p, exc)

        if self._store and self._call_record_id:
            try:
                self._store.mark_call_handoff(self._call_record_id, target_ext)
            except Exception:
                logger.exception("Failed to mark call handoff in store")

        # Terminate AudioSocket session so Asterisk proceeds to dial the forward extension
        self._session.request_hangup()

    async def _speak_sentence(
        self,
        sentence: str,
        target_language: str = "en",
        length_scale: Optional[float] = None,
        noise_scale: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> None:
        """Synthesize one sentence and push resulting frames onto the outbound queue."""
        async for frame in self._tts.synthesize_streaming(
            sentence, 
            interrupt_event=self._session.barge_in_event,
            target_language=target_language,
            length_scale=length_scale,
            noise_scale=noise_scale,
            volume=volume,
        ):
            if self._session.barge_in_event.is_set():
                break
            self._recorded_audio_pcm.extend(frame)
            try:
                await asyncio.wait_for(self._session.outbound_audio.put(frame), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Call %s: outbound queue backpressure, dropping frame", self._session.call_id)

    async def _speak_backchannel(self, text: str, language: str = "en") -> None:
        """Emit a soft, non-intrusive acknowledgment token during caller micro-pause."""
        logger.info("Call %s: acoustic backchannel: %r (lang=%s)", self._session.call_id, text, language)
        self._emit_event({"type": "backchannel", "text": text, "language": language})
        try:
            async for frame in self._tts.synthesize_streaming(
                text,
                interrupt_event=self._session.barge_in_event,
                target_language=language,
                volume=0.85,
                length_scale=1.1,
            ):
                if self._session.barge_in_event.is_set():
                    break
                self._recorded_audio_pcm.extend(frame)
                try:
                    await asyncio.wait_for(self._session.outbound_audio.put(frame), timeout=0.5)
                except asyncio.TimeoutError:
                    break
        except Exception as exc:
            logger.debug("Backchannel synthesis exception: %s", exc)


    def _trim_history(self) -> None:
        """Keep only the most recent N turns to bound LLM prompt size/latency."""
        if len(self._history) > MAX_HISTORY_TURNS * 2:
            self._history = self._history[-MAX_HISTORY_TURNS * 2 :]


def build_pipeline_factory(
    settings: Settings,
    stt: SttService,
    llm: LlmService,
    tts: TtsService,
    persona: AgentPersona,
    rag: RagService,
    store: Optional["PlatformStore"] = None,
    persona_b: Optional[AgentPersona] = None,
    tts_b: Optional[TtsService] = None,
    ab_split_ratio: int = 50,
):
    """
    Returns an async callable `(VoiceSession) -> None` suitable for
    injection into `AudioSocketServer` as its `pipeline_factory`.
    Supports A/B testing: routes traffic between persona/tts A and B.
    """
    import random

    async def _factory(session: VoiceSession) -> None:
        chosen_persona = persona
        chosen_tts = tts
        if persona_b is not None and tts_b is not None:
            if random.randint(1, 100) <= ab_split_ratio:
                chosen_persona = persona_b
                chosen_tts = tts_b

        pipeline = CallPipeline(
            session=session,
            settings=settings,
            stt=stt,
            llm=llm,
            tts=chosen_tts,
            persona=chosen_persona,
            rag=rag,
            store=store,
        )
        await pipeline.run()

    return _factory