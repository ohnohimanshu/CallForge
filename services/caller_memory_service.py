"""
services/caller_memory_service.py
==================================
Cross-Call Memory & Caller Recognition Service.

Architectural Concept:
    Key a lightweight profile store on caller phone number:
      - Caller name
      - Past call summaries
      - Sentiment history (frustrated, positive, neutral)
      - Last disposition (Lead Captured, Escalated to Human, Information Provided, etc.)
      - Turn & entity details

    When a returning caller connects:
    1. Look up profile before the call greeting even plays.
    2. Inject structured cross-call memory into the LLM context:
       "This caller called 3 days ago about appointment booking, was frustrated about wait time."
    3. Generate and play an immediate personalized recognition greeting:
       "Hi again — following up on your appointment from Tuesday?"
    4. At call conclusion, summarize the conversation and update the caller profile.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from callforge.store.models import CallerProfileRecord

logger = logging.getLogger(__name__)


class CallerMemoryService:
    """
    Manages caller recognition, cross-call memory synthesis, and post-call summarization.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """
        Normalize telephone number to a clean comparable string.
        Strips whitespace, dashes, dots, parentheses, and leading zeros if country code is present.
        """
        if not phone:
            return ""
        clean = phone.strip()
        if clean.lower() in ("unknown", "anonymous", "private", "unavailable"):
            return "unknown"

        # Keep leading + if present
        has_plus = clean.startswith("+")
        digits = "".join(c for c in clean if c.isdigit())
        if not digits:
            return "unknown"

        return f"+{digits}" if has_plus else digits

    @staticmethod
    def format_relative_time(iso_timestamp: str) -> str:
        """
        Convert an ISO 8601 UTC timestamp into human-readable relative time:
        e.g. 'just now', '10 minutes ago', '2 hours ago', 'yesterday', '3 days ago (Tuesday)'.
        """
        if not iso_timestamp:
            return "recently"

        try:
            call_dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            if call_dt.tzinfo is None:
                call_dt = call_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)

            delta = now - call_dt
            total_seconds = max(0, int(delta.total_seconds()))

            if total_seconds < 60:
                return "just moments ago"
            elif total_seconds < 3600:
                minutes = total_seconds // 60
                return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
            elif total_seconds < 86400:
                hours = total_seconds // 3600
                return f"{hours} hour{'s' if hours != 1 else ''} ago"
            elif total_seconds < 172800:
                return "yesterday"
            elif total_seconds < 604800:
                days = total_seconds // 86400
                weekday_name = call_dt.strftime("%A")
                return f"{days} days ago ({weekday_name})"
            else:
                weeks = total_seconds // 604800
                date_str = call_dt.strftime("%b %d")
                return f"{weeks} week{'s' if weeks != 1 else ''} ago (on {date_str})"
        except Exception as exc:
            logger.debug("Failed to format relative time for %r: %s", iso_timestamp, exc)
            return "previously"

    def extract_topic_from_summary(self, summary: str) -> str:
        """
        Extract the salient conversational topic from a summary sentence.
        e.g.:
          'Caller inquired about booking an appointment for tomorrow' -> 'appointment booking'
          'Caller asked for business hours and pricing' -> 'pricing and business hours'
        """
        if not summary:
            return "previous inquiry"

        clean = summary.lower()

        def _has_word(words: list[str]) -> bool:
            return any(re.search(r"\b" + re.escape(w) + r"\b", clean) for w in words)

        if _has_word(["appointment", "booking", "slot", "slots", "schedule", "reserve"]):
            return "appointment"
        if _has_word(["wellness", "feeling", "feelings", "mental", "emotion", "emotions", "support", "overwhelm"]):
            return "mental wellness and support"
        if _has_word(["pricing", "price", "cost", "fee", "fees", "charge", "rate"]):
            return "pricing questions"
        if _has_word(["hours", "open", "timing", "weekend"]):
            return "business hours"
        if _has_word(["service", "consultation", "help"]):
            return "service inquiry"
        if _has_word(["refund", "billing", "payment", "invoice"]):
            return "billing questions"
        if _has_word(["cancel", "reschedule"]):
            return "rescheduling request"

        # Fallback to a truncated snippet
        return "previous conversation"

    def build_caller_context(self, profile: CallerProfileRecord) -> str:
        """
        Construct the cross-call memory prompt injection for the LLM.
        """
        rel_time = self.format_relative_time(profile.last_call_at)
        history_str = ", ".join(profile.sentiment_history[-4:]) if profile.sentiment_history else "neutral"

        past_summary_bullet = ""
        if profile.last_summary:
            past_summary_bullet = f"- Last Conversation Summary: {profile.last_summary}\n"
        elif profile.past_summaries:
            past_summary_bullet = f"- Last Conversation Summary: {profile.past_summaries[-1]}\n"

        sentiment_directive = ""
        if profile.last_sentiment == "frustrated":
            sentiment_directive = (
                "- Caller Sentiment History: Caller was frustrated in their previous contact. "
                "CRITICAL: Be exceptionally calm, empathetic, and proactive. Acknowledge any past difficulty "
                "with sincere care and assure them you will take care of their request smoothly."
            )
        elif profile.last_sentiment == "positive":
            sentiment_directive = "- Caller Sentiment History: Caller had a positive previous experience. Build warmly on this rapport."
        else:
            sentiment_directive = f"- Caller Sentiment History: {history_str}"

        name_info = f"{profile.name} (Address caller by name warmly!)" if profile.name else "Name not yet provided"

        context = (
            "=== RETURNING CALLER RECOGNITION & CROSS-CALL MEMORY ===\n"
            f"- Status: RETURNING CALLER (Call #{profile.call_count})\n"
            f"- Phone Number: {profile.phone_number}\n"
            f"- Caller Name: {name_info}\n"
            f"- Last Contact: {rel_time} ({profile.last_call_at[:10] if profile.last_call_at else ''})\n"
            f"- Previous Disposition: {profile.last_disposition}\n"
            f"{past_summary_bullet}"
            f"{sentiment_directive}\n\n"
            "CROSS-CALL INSTRUCTIONS:\n"
            "1. You recognize this caller. Do NOT ask who they are or act like this is the first time speaking.\n"
            f"2. Reference their previous inquiry about '{self.extract_topic_from_summary(profile.last_summary)}' naturally in your conversation.\n"
            f"3. {f'Address them as {profile.name}.' if profile.name else 'If their name was not on file, you may confirm it politely.'}\n"
            "=========================================================\n"
        )
        return context

    def generate_returning_greeting(
        self,
        profile: CallerProfileRecord,
        agent_name: str = "",
        language: str = "en",
    ) -> str:
        """
        Generate a recognized, personalized opening greeting for returning callers.
        Delivers the 'call once, hang up, call again, watch it remember' experience.
        """
        rel_time = self.format_relative_time(profile.last_call_at)
        topic = self.extract_topic_from_summary(profile.last_summary)
        is_hindi = language == "hi"

        if is_hindi:
            if profile.name:
                if "appointment" in topic:
                    return f"नमस्ते {profile.name} जी! हमारे पास फिर से कॉल करने के लिए धन्यवाद। क्या आप अपने अपॉइंटमेंट के सिलसिले में बात कर रहे हैं?"
                return f"नमस्ते {profile.name} जी! आपका फिर से स्वागत है। मैं आपकी आज कैसे सहायता कर सकता हूँ?"
            else:
                if "appointment" in topic:
                    return "नमस्ते! हमारे पास फिर से कॉल करने के लिए धन्यवाद। क्या आप अपने अपॉइंटमेंट के सिलसिले में बात कर रहे हैं?"
                return "नमस्ते! हमारे पास फिर से कॉल करने के लिए धन्यवाद। आज मैं आपकी क्या मदद कर सकता हूँ?"

        # English Greetings
        if profile.name:
            if "appointment" in topic:
                return f"Hi {profile.name}, welcome back! Are you following up on your appointment from {rel_time}?"
            elif topic != "previous conversation":
                return f"Hi {profile.name}, welcome back! Are you following up on your {topic} from {rel_time}?"
            else:
                return f"Hi {profile.name}, welcome back! How may I assist you today?"
        else:
            if "appointment" in topic:
                return f"Hi again! Welcome back — are you following up on your appointment from {rel_time}?"
            elif topic != "previous conversation":
                return f"Hi again! Welcome back — are you following up on your {topic} from {rel_time}?"
            else:
                return "Hi again, welcome back! How can I help you today?"

    async def summarize_call(
        self,
        user_turns: list[str],
        assistant_turns: list[str],
        disposition: str,
        sentiment: str,
        llm_service: Optional[Any] = None,
    ) -> str:
        """
        Extract a concise, informative 1-sentence summary of the conversation.
        Uses local LLM if available and quick; otherwise uses deterministic entity/intent heuristics.
        """
        if not user_turns:
            return "Caller connected but remained silent."

        combined_user = " ".join(user_turns).strip()
        lower_user = combined_user.lower()

        # Heuristic topic detection using word boundaries
        def _has_user_word(words: list[str]) -> bool:
            return any(re.search(r"\b" + re.escape(w) + r"\b", lower_user) for w in words)

        has_booking = _has_user_word(["book", "booking", "appointment", "schedule", "slot", "slots", "reserve", "timing", "कल", "अपॉइंटमेंट"])
        has_wellness = _has_user_word(["feeling", "feelings", "feel", "wellness", "mental", "sad", "depressed", "anxious", "anxiety", "stress", "stressed", "overwhelmed", "overthinking"])
        has_pricing = _has_user_word(["price", "pricing", "cost", "rate", "fee", "fees", "charge", "charges", "kitna"])
        has_hours = _has_user_word(["hours", "open", "timing", "weekend", "kab tak"])
        has_human = _has_user_word(["human", "operator", "person", "representative", "insaan"])

        # Try fast LLM 1-shot summary if available
        if llm_service is not None and len(user_turns) >= 2:
            try:
                prompt = (
                    "Summarize this phone conversation in exactly ONE concise sentence (max 18 words). "
                    "Focus on the caller's main question/intent and the outcome. No filler, no markdown.\n\n"
                    f"Caller: {combined_user[:400]}\n"
                    f"Outcome: {disposition}\n"
                    "Summary:"
                )
                loop = asyncio.get_running_loop()
                # Run with short timeout
                summary_text = ""
                async for chunk in llm_service.stream_reply(
                    history=[],
                    user_utterance=prompt,
                    interrupt_event=asyncio.Event(),
                    system_prompt="You are a concise call summarization tool.",
                    max_tokens=40,
                ):
                    summary_text += chunk
                    if len(summary_text) > 120:
                        break

                clean_sum = summary_text.strip().replace("\n", " ")
                if 10 <= len(clean_sum) <= 180:
                    return clean_sum
            except Exception as exc:
                logger.debug("LLM summarization skipped: %s", exc)

        # High-precision deterministic fallback summary:
        if has_booking:
            if disposition == "Lead Captured":
                return "Caller inquired about appointment availability and confirmed a booking."
            return "Caller inquired about appointment scheduling and available slots."
        elif has_wellness:
            return "Caller discussed personal feelings and sought mental-wellness support."
        elif has_human or disposition == "Escalated to Human":
            return "Caller requested escalation to a live human operator."
        elif has_pricing:
            return "Caller asked for service pricing and fee details."
        elif has_hours:
            return "Caller inquired about business hours and availability."
        else:
            first_turn = user_turns[0][:80]
            return f"Caller inquired: '{first_turn}' (outcome: {disposition})."


# Shared singleton instance
caller_memory_service = CallerMemoryService()
