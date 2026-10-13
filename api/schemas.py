"""Pydantic request/response schemas for the CallForge API."""

from __future__ import annotations

from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional phone agent for a business call. "
    "Speak clearly, calmly, and courteously — like a trained receptionist. "
    "Use short complete sentences (1–2 per turn). Never use markdown, lists, "
    "emojis, stage directions, or filler like 'um' or 'as an AI'. "
    "Confirm what the caller needs, answer directly, and offer one helpful "
    "next step. If you do not know something, say so briefly and ask a "
    "clarifying question. Keep language plain and easy to understand over a phone."
)

DEFAULT_GREETING = "Thank you for calling. How may I help you today?"


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = ""
    extension: str = Field(default="2000", pattern=r"^[0-9]{3,8}$")
    language: str = Field(default="auto", pattern=r"^(auto|en|hi)$")
    llm_model: str = "llama3.2:3b-instruct-q4_K_M"
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT)
    greeting_text: str = Field(default=DEFAULT_GREETING)
    voice_en: str = "en_US-lessac-medium"
    voice_hi: str = "hi_IN-priyamvada-medium"
    # Human Handoff
    handoff_enabled: bool = False
    handoff_extension: str = "1001"
    handoff_fallback_threshold: int = 2
    handoff_message: str = "I am transferring you to a representative now. Please hold on the line."
    handoff_message_hi: str = "मैं आपको हमारे प्रतिनिधि से कनेक्ट कर रहा हूँ। कृपया लाइन पर बने रहें।"
    # A/B Testing
    ab_testing_enabled: bool = False
    ab_variant_b_prompt: Optional[str] = ""
    ab_variant_b_greeting: Optional[str] = ""
    ab_variant_b_voice_en: Optional[str] = "en_US-amy-medium"
    ab_variant_b_voice_hi: Optional[str] = "hi_IN-priyamvada-medium"
    ab_variant_b_llm_model: Optional[str] = ""
    ab_split_ratio: Union[int, float] = 50
    # Dialogue Policy (Slot Filling)
    dialogue_policy_enabled: bool = False
    dialogue_slots_json: Optional[str] = "[]"
    # Multilingual Routing
    multilingual_routing: bool = True
    lang_confidence_threshold: float = 0.65
    fallback_language: str = "en"
    supported_languages: str = "en,hi"
    # Dynamic Tools / Google Sheets
    tools_enabled: bool = False
    tools_webhook_url: Optional[str] = ""
    # Voice Cloning
    voice_cloning_enabled: bool = False
    cloned_voice_sample_path: Optional[str] = None
    # Speculative Response Generation
    speculative_generation_enabled: bool = True
    speculative_branch_count: int = 3
    # Dedicated Customer Phone Number (DID)
    phone_number: Optional[str] = None
    phone_number_status: str = "none"
    phone_number_price: float = 4.99
    phone_number_country: str = "US"

    @field_validator("system_prompt", mode="before")
    @classmethod
    def _clean_system_prompt(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return DEFAULT_SYSTEM_PROMPT
        return str(v).strip()

    @field_validator("greeting_text", mode="before")
    @classmethod
    def _clean_greeting_text(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return DEFAULT_GREETING
        return str(v).strip()

    @field_validator("ab_split_ratio", mode="before")
    @classmethod
    def _clean_ab_split_ratio(cls, v: Any) -> int:
        if v is None or v == "":
            return 50
        try:
            val = float(v)
            if 0.0 <= val <= 1.0:
                return max(1, min(99, int(round(val * 100))))
            return max(1, min(99, int(round(val))))
        except (ValueError, TypeError):
            return 50

    @field_validator("extension", mode="before")
    @classmethod
    def _clean_extension(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return "2000"
        return str(v).strip()

    @field_validator(
        "description",
        "ab_variant_b_prompt",
        "ab_variant_b_greeting",
        "ab_variant_b_llm_model",
        "tools_webhook_url",
        mode="before",
    )
    @classmethod
    def _clean_optional_strings(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("dialogue_slots_json", mode="before")
    @classmethod
    def _clean_dialogue_slots_json(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return "[]"
        return str(v).strip()

    @field_validator("cloned_voice_sample_path", mode="before")
    @classmethod
    def _clean_cloned_voice_sample_path(cls, v: Any) -> Optional[str]:
        if not v:
            return None
        return str(v).strip()


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    extension: Optional[str] = Field(default=None, pattern=r"^[0-9]{3,8}$")
    language: Optional[str] = Field(default=None, pattern=r"^(auto|en|hi)$")
    llm_model: Optional[str] = None
    system_prompt: Optional[str] = None
    greeting_text: Optional[str] = None
    voice_en: Optional[str] = None
    voice_hi: Optional[str] = None
    # Human Handoff
    handoff_enabled: Optional[bool] = None
    handoff_extension: Optional[str] = None
    handoff_fallback_threshold: Optional[int] = None
    handoff_message: Optional[str] = None
    handoff_message_hi: Optional[str] = None
    # A/B Testing
    ab_testing_enabled: Optional[bool] = None
    ab_variant_b_prompt: Optional[str] = None
    ab_variant_b_greeting: Optional[str] = None
    ab_variant_b_voice_en: Optional[str] = None
    ab_variant_b_voice_hi: Optional[str] = None
    ab_variant_b_llm_model: Optional[str] = None
    ab_split_ratio: Optional[Union[int, float]] = None
    # Dialogue Policy
    dialogue_policy_enabled: Optional[bool] = None
    dialogue_slots_json: Optional[str] = None
    # Multilingual Routing
    multilingual_routing: Optional[bool] = None
    lang_confidence_threshold: Optional[float] = None
    fallback_language: Optional[str] = None
    supported_languages: Optional[str] = None
    # Dynamic Tools / Google Sheets
    tools_enabled: Optional[bool] = None
    tools_webhook_url: Optional[str] = None
    # Voice Cloning
    voice_cloning_enabled: Optional[bool] = None
    cloned_voice_sample_path: Optional[str] = None
    # Speculative Response Generation
    speculative_generation_enabled: Optional[bool] = None
    speculative_branch_count: Optional[int] = None
    # Dedicated Customer Phone Number (DID)
    phone_number: Optional[str] = None
    phone_number_status: Optional[str] = None
    phone_number_price: Optional[float] = None
    phone_number_country: Optional[str] = None

    @field_validator("ab_split_ratio", mode="before")
    @classmethod
    def _clean_ab_split_ratio(cls, v: Any) -> Optional[int]:
        if v is None:
            return None
        try:
            val = float(v)
            if 0.0 <= val <= 1.0:
                return max(1, min(99, int(round(val * 100))))
            return max(1, min(99, int(round(val))))
        except (ValueError, TypeError):
            return 50

    @field_validator("extension", mode="before")
    @classmethod
    def _clean_extension(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("system_prompt", mode="before")
    @classmethod
    def _clean_system_prompt(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else DEFAULT_SYSTEM_PROMPT

    @field_validator("greeting_text", mode="before")
    @classmethod
    def _clean_greeting_text(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else DEFAULT_GREETING


class PhoneNumberAssignRequest(BaseModel):
    phone_number: str = Field(..., min_length=5, max_length=25)
    country_code: str = Field(default="US", max_length=4)


class PhoneNumberReleaseRequest(BaseModel):
    phone_number: Optional[str] = None

