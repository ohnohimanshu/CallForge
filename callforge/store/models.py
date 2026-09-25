from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(slots=True)
class AgentRecord:
    id: str
    name: str
    description: str = ""
    extension: str = "2000"
    language: str = "auto"  # auto | en | hi
    llm_model: str = "llama3.2:3b-instruct-q4_K_M"
    system_prompt: str = (
        "You are a helpful voice assistant speaking on a phone call. "
        "Respond in short, natural, conversational sentences. Avoid lists, "
        "markdown, and long monologues. Keep replies under three sentences "
        "unless explicitly asked for detail."
    )
    greeting_text: str = "Thanks for calling. How can I help you today?"
    voice_en: str = "en_US-amy-medium"
    voice_hi: str = "hi_IN-priyamvada-medium"
    status: str = "draft"  # draft | deployed | stopped
    port: Optional[int] = None
    # Dedicated Customer Phone Number (DID)
    phone_number: Optional[str] = None
    phone_number_status: str = "none"  # none | active | released
    phone_number_price: float = 4.99
    phone_number_country: str = "US"
    # Human Handoff
    handoff_enabled: bool = False
    handoff_extension: str = "1001"
    handoff_fallback_threshold: int = 2
    handoff_message: str = "I am transferring you to a representative now. Please hold on the line."
    handoff_message_hi: str = "मैं आपको हमारे प्रतिनिधि से कनेक्ट कर रहा हूँ। कृपया लाइन पर बने रहें।"
    # A/B Testing
    ab_testing_enabled: bool = False
    ab_variant_b_prompt: str = ""
    ab_variant_b_greeting: str = ""
    ab_variant_b_voice_en: str = "en_US-amy-medium"
    ab_variant_b_voice_hi: str = "hi_IN-priyamvada-medium"
    ab_variant_b_llm_model: str = ""
    ab_split_ratio: int = 50
    # Dialogue Policy (Slot Filling)
    dialogue_policy_enabled: bool = False
    dialogue_slots_json: str = "[]"
    # Multilingual Routing
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
    speculative_branch_count: int = 2
    # Ownership
    owner_username: str = "himanshu"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UserRecord:
    id: str
    username: str
    password_hash: str
    full_name: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "created_at": self.created_at,
        }



@dataclass(slots=True)
class DocumentRecord:
    id: str
    agent_id: str
    filename: str
    stored_path: str
    status: str = "pending"  # pending | indexed | failed
    chunk_count: int = 0
    error: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CallRecord:
    id: str
    agent_id: str
    call_uuid: str
    caller_id: str = "unknown"
    started_at: str = ""
    ended_at: str = ""
    duration_s: float = 0.0
    status: str = "active"  # active | completed | failed | transferred
    transcript_preview: str = ""
    ab_variant: str = "A"
    handoff_to: str = ""
    slots_json: str = "{}"
    disposition: str = "Completed"
    sentiment: str = "neutral"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CallTurnRecord:
    id: str
    call_id: str
    role: str  # user | assistant
    content: str
    language: str = ""
    created_at: str = ""
    offset_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CampaignRecord:
    id: str
    name: str
    agent_id: str
    status: str = "draft"  # draft | running | paused | completed
    concurrency_limit: int = 1
    caller_id: str = "Outbound AI"
    greeting_text: str = ""
    collect_fields: str = ""
    total_contacts: int = 0
    completed_contacts: int = 0
    successful_contacts: int = 0
    failed_contacts: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CampaignContactRecord:
    id: str
    campaign_id: str
    phone: str
    name: str = ""
    custom_variables_json: str = "{}"
    collected_data_json: str = "{}"
    status: str = "pending"  # pending | dialing | connected | completed | failed
    attempts: int = 0
    call_uuid: str = ""
    call_id: str = ""
    disposition: str = ""
    duration_s: float = 0.0
    last_attempt_at: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CallerProfileRecord:
    phone_number: str
    name: str = ""
    call_count: int = 1
    last_call_at: str = ""
    last_disposition: str = "Completed"
    last_sentiment: str = "neutral"
    sentiment_history_json: str = "[]"
    past_summaries_json: str = "[]"
    last_summary: str = ""
    entities_json: str = "{}"
    created_at: str = ""
    updated_at: str = ""

    @property
    def past_summaries(self) -> list[str]:
        try:
            return json.loads(self.past_summaries_json) if self.past_summaries_json else []
        except Exception:
            return []

    @property
    def sentiment_history(self) -> list[str]:
        try:
            return json.loads(self.sentiment_history_json) if self.sentiment_history_json else []
        except Exception:
            return []

    @property
    def entities(self) -> dict[str, Any]:
        try:
            return json.loads(self.entities_json) if self.entities_json else {}
        except Exception:
            return {}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AVAILABLE_LANGUAGES: list[dict[str, str]] = [
    {"id": "auto", "label": "Auto-detect (EN / HI)"},
    {"id": "en", "label": "English"},
    {"id": "hi", "label": "Hindi"},
]

AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "llama3.2:3b-instruct-q4_K_M", "label": "Llama 3.2 3B (fast, low RAM)"},
    {"id": "qwen2.5:3b-instruct-q4_K_M", "label": "Qwen 2.5 3B (strong instruction following)"},
    {"id": "phi3:mini", "label": "Phi-3 Mini"},
    {"id": "gemma2:2b", "label": "Gemma 2 2B (lightest)"},
]

AVAILABLE_VOICES_EN: list[dict[str, str]] = [
    {"id": "en_US-ryan-medium", "label": "Ryan (Warm / Realistic Male - Recommended)"},
    {"id": "en_US-kristin-medium", "label": "Kristin (Warm / Natural Female - Recommended)"},
    {"id": "en_US-amy-medium", "label": "Amy (US English Female)"},
    {"id": "en_US-lessac-medium", "label": "Lessac (Professional Neutral)"},
]

AVAILABLE_VOICES_HI: list[dict[str, str]] = [
    {"id": "hi_IN-priyamvada-medium", "label": "Priyamvada (Hindi)"},
]
