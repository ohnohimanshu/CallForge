"""
callforge/runtime/dialogue.py
=============================
Dialogue policy and slot-filling engine for structured voice conversations.

Architectural decision:
    Instead of relying purely on unconstrained LLM chat (which frequently forgets
    to collect critical contact details or drifts away from business objectives),
    the DialoguePolicy state machine explicitly tracks which required pieces of
    information (slots: e.g. name, phone, intent) have been collected.

    On every turn, it extracts candidate values (via fast regular expressions and
    pattern extractors), tracks completion, and injects a high-priority steering
    directive into the LLM system prompt so the assistant stays on mission.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Standard telephone regex: matches 10-digit numbers, international prefixes, dashed/spaced
_PHONE_REGEX = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\b[6-9]\d{9}\b"
)

# Standard email regex
_EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")

# Words that cannot be part of a legitimate person name in phone conversations
_NON_NAME_WORDS = {
    # Pronouns, articles, auxiliaries
    "and", "my", "the", "or", "with", "phone", "number", "email", "is", "a", "an", "this", "that", "it", "its",
    "you", "your", "we", "our", "they", "them", "he", "she", "his", "her", "me", "myself", "us", "him",
    # Greetings & fillers
    "hello", "hi", "hey", "yes", "yeah", "yep", "sure", "ok", "okay", "no", "nope", "please", "thanks", "thank",
    # Adjectives, emotions, states of being
    "doing", "great", "fine", "good", "well", "better", "best", "bad", "sick", "tired", "happy", "sad", "upset",
    "angry", "busy", "free", "available", "ready", "interested", "alive", "cool", "alright", "awesome",
    # Location/temporal/directional
    "here", "there", "now", "later", "tomorrow", "yesterday", "today", "tonight", "back", "again", "soon",
    # Common verbs
    "am", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "call", "calling", "talk", "talking", "speak", "speaking", "listen", "listening", "hear", "hearing",
    "ask", "asking", "wonder", "wondering", "think", "thinking", "feel", "feeling",
    "try", "trying", "work", "working", "go", "going", "come", "coming", "live", "living",
    # Adverbs, prepositions & conjunctions
    "not", "just", "really", "very", "too", "also", "only", "actually", "probably", "maybe", "definitely", "absolutely",
    "who", "what", "where", "when", "why", "how", "which",
    "about", "for", "from", "in", "on", "at", "to", "by", "up", "down", "out",
}
_NAME_STOP_WORDS = _NON_NAME_WORDS  # backward compatibility

_NAME_PHRASES = [
    re.compile(r"(?:my name is|i am|this is|it is|it's|call me|myself)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", re.IGNORECASE),
    re.compile(r"(?:मेरा नाम|नाम है|मैं हूँ|मैं)\s+([^\s,.]+)", re.IGNORECASE),
]

_WORD_TO_NUM: list[tuple[str, int]] = sorted(
    [
        ("zero", 0), ("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5), ("six", 6), ("seven", 7),
        ("eight", 8), ("nine", 9), ("ten", 10), ("eleven", 11), ("twelve", 12), ("thirteen", 13), ("fourteen", 14),
        ("fifteen", 15), ("sixteen", 16), ("seventeen", 17), ("eighteen", 18), ("nineteen", 19), ("twenty", 20),
        ("twenty one", 21), ("twenty two", 22), ("twenty three", 23), ("twenty four", 24), ("twenty five", 25),
        ("twenty six", 26), ("twenty seven", 27), ("twenty eight", 28), ("twenty nine", 29), ("thirty", 30),
        ("thirty one", 31), ("thirty two", 32), ("thirty three", 33), ("thirty four", 34), ("thirty five", 35),
        ("forty", 40), ("forty five", 45), ("fifty", 50), ("fifty five", 55), ("sixty", 60), ("seventy", 70), ("eighty", 80),
        ("bees", 20), ("ikkees", 21), ("baees", 22), ("teees", 23), ("chaubees", 24), ("pachees", 25),
        ("chhabees", 26), ("sattaees", 27), ("athhaees", 28), ("untees", 29), ("tees", 30), ("chaalis", 40), ("pachaas", 50),
    ],
    key=lambda x: len(x[0]),
    reverse=True,
)

# Intent phrases
_INTENT_PHRASES = [
    re.compile(r"(?:i want to|calling to|calling about|need help with|looking for|i need)\s+([^.!?]+)", re.IGNORECASE),
    re.compile(r"(?:मुझे|के बारे में बात करनी है|जानना है)\s+([^.!?]+)", re.IGNORECASE),
]


@dataclass(slots=True)
class SlotDefinition:
    """Definition of a single slot to be filled during the call."""

    name: str  # unique key, e.g. "caller_name", "phone", "intent"
    label: str  # human readable, e.g. "Full Name"
    required: bool = True
    prompt_question: str = ""  # question to prompt when missing
    pattern: str = ""  # optional custom regex

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlotDefinition":
        return cls(
            name=data.get("name", ""),
            label=data.get("label", data.get("name", "")),
            required=bool(data.get("required", True)),
            prompt_question=data.get("prompt_question", ""),
            pattern=data.get("pattern", ""),
        )


STANDARD_SLOTS_PRESET: list[dict[str, Any]] = [
    {
        "name": "name",
        "label": "Full Name",
        "required": True,
        "prompt_question": "May I please have your name?",
    },
    {
        "name": "phone",
        "label": "Phone Number",
        "required": True,
        "prompt_question": "What is the best phone number to reach you at?",
    },
    {
        "name": "intent",
        "label": "Call Reason / Intent",
        "required": True,
        "prompt_question": "How can I help you today?",
    },
]


def _default_prompt_question_for_field(label: str) -> str:
    lbl = label.lower()
    if "name" in lbl:
        return "May I please have your name?"
    elif "age" in lbl:
        return "Could you please tell me your age?"
    elif "phone" in lbl or "mobile" in lbl:
        return "What is your best phone number?"
    elif "email" in lbl:
        return "What is your email address?"
    elif "city" in lbl or "location" in lbl or "address" in lbl:
        return "What city or location are you located in?"
    elif "company" in lbl or "organization" in lbl or "workplace" in lbl:
        return "What company or organization do you represent?"
    elif "profession" in lbl or "role" in lbl or "job" in lbl or "occupation" in lbl:
        return "What is your current role or occupation?"
    elif "experience" in lbl:
        return "How many years of experience do you have?"
    elif "rating" in lbl or "score" in lbl:
        return "How would you rate your experience on a scale of 1 to 5?"
    elif "feedback" in lbl:
        return "Do you have any feedback or comments to share?"
    elif "date" in lbl:
        return "What date works best for you?"
    elif "time" in lbl:
        return "What time of day do you prefer?"
    elif "budget" in lbl or "price" in lbl:
        return "What is your estimated budget?"
    elif "reason" in lbl or "purpose" in lbl or "need" in lbl:
        return "What is the primary reason for your inquiry?"
    else:
        return f"Could you please provide your {label}?"


@dataclass
class DialogueStateTracker:
    """
    Per-session dialogue state tracker that extracts and maintains filled slots.
    """

    slots_schema: list[SlotDefinition]
    filled_slots: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_field_names(cls, field_names: list[str]) -> "DialogueStateTracker":
        """Construct a DialogueStateTracker dynamically for campaign collected fields."""
        definitions = []
        for f in field_names:
            clean_name = f.strip().lower().replace(" ", "_")
            if not clean_name:
                continue
            definitions.append(
                SlotDefinition(
                    name=clean_name,
                    label=f.strip(),
                    required=True,
                    prompt_question=_default_prompt_question_for_field(f.strip()),
                )
            )
        if not definitions:
            definitions = [SlotDefinition.from_dict(s) for s in STANDARD_SLOTS_PRESET]
        return cls(slots_schema=definitions)

    @classmethod
    def from_json(cls, json_str: str) -> "DialogueStateTracker":
        if not json_str or json_str.strip() in ("", "[]"):
            definitions = [SlotDefinition.from_dict(s) for s in STANDARD_SLOTS_PRESET]
        else:
            try:
                parsed = json.loads(json_str)
                definitions = [SlotDefinition.from_dict(s) for s in parsed]
            except Exception as exc:
                logger.warning("Failed to parse dialogue slots json, using defaults: %s", exc)
                definitions = [SlotDefinition.from_dict(s) for s in STANDARD_SLOTS_PRESET]
        return cls(slots_schema=definitions)

    def extract_from_utterance(self, text: str, last_assistant_text: str = "") -> dict[str, str]:
        """Extract candidate slot values from caller utterance with contextual intelligence."""
        newly_filled: dict[str, str] = {}
        cleaned = text.strip()
        if not cleaned:
            return newly_filled

        cleaned_words = [re.sub(r"[^\w]", "", w) for w in cleaned.split()]
        cleaned_words = [w for w in cleaned_words if w]
        next_unfilled = self.get_next_unfilled_slot()
        last_asst_lower = last_assistant_text.lower() if last_assistant_text else ""

        for slot in self.slots_schema:
            if slot.name in self.filled_slots and self.filled_slots[slot.name]:
                continue  # already filled

            is_slot_target = (next_unfilled and next_unfilled.name == slot.name) or (
                slot.name in last_asst_lower or slot.label.lower() in last_asst_lower
            )

            val: Optional[str] = None
            # 1. Check custom pattern if provided
            if slot.pattern:
                try:
                    match = re.search(slot.pattern, cleaned, re.IGNORECASE)
                    if match:
                        val = match.group(1) if match.groups() else match.group(0)
                except Exception:
                    pass

            # 2. Built-in slot extractors
            if val is None:
                # PHONE
                if slot.name in ("phone", "phone_number", "mobile", "contact"):
                    match = _PHONE_REGEX.search(cleaned)
                    if match:
                        val = re.sub(r"[^\d+]", "", match.group(0))

                # EMAIL
                elif slot.name in ("email", "email_address"):
                    match = _EMAIL_REGEX.search(cleaned)
                    if match:
                        val = match.group(0)

                # NAME
                elif slot.name in ("name", "caller_name", "user_name", "full_name"):
                    for phrase_re in _NAME_PHRASES:
                        match = phrase_re.search(cleaned)
                        if match:
                            raw_words = match.group(1).strip().split()
                            candidate_words = []
                            for w in raw_words:
                                if w.lower() in _NON_NAME_WORDS:
                                    break
                                if w.isalpha() and len(w) >= 2:
                                    candidate_words.append(w.capitalize())
                                else:
                                    break
                            if candidate_words:
                                val = " ".join(candidate_words)
                                break
                    if not val and is_slot_target and len(cleaned_words) <= 3 and not _PHONE_REGEX.search(cleaned):
                        candidate_words = []
                        for w in cleaned_words:
                            if w.lower() in _NON_NAME_WORDS:
                                break
                            if w.isalpha() and len(w) >= 2:
                                candidate_words.append(w.capitalize())
                            else:
                                break
                        if candidate_words:
                            val = " ".join(candidate_words)

                # AGE
                elif slot.name in ("age", "caller_age", "user_age"):
                    age_match = re.search(
                        r"(?:i am|i'm|age is|age|aged|am)\s+(\d{1,3})(?:\s+years old|\s+years|\s+yrs|\s+yr)?",
                        cleaned,
                        re.IGNORECASE,
                    )
                    if age_match:
                        num = int(age_match.group(1))
                        if 1 <= num <= 120:
                            val = str(num)
                    if not val:
                        age_match2 = re.search(
                            r"\b(\d{1,3})\s*(?:years old|years|yrs|yr|sal|saal)\b",
                            cleaned,
                            re.IGNORECASE,
                        )
                        if age_match2:
                            num = int(age_match2.group(1))
                            if 1 <= num <= 120:
                                val = str(num)
                    if not val:
                        for word_phrase, num in _WORD_TO_NUM:
                            if re.search(r"\b" + re.escape(word_phrase) + r"\b", cleaned, re.IGNORECASE):
                                if 1 <= num <= 120:
                                    val = str(num)
                                    break
                    if not val and is_slot_target:
                        num_match = re.search(r"\b(\d{1,3})\b", cleaned)
                        if num_match:
                            num = int(num_match.group(1))
                            if 1 <= num <= 120:
                                val = str(num)

                # CITY / LOCATION / ADDRESS
                elif any(w in slot.name for w in ("city", "location", "address", "state", "country")):
                    city_match = re.search(
                        r"(?:i live in|living in|i am from|located in|city is|in)\s+([A-Za-z\s]+)",
                        cleaned,
                        re.IGNORECASE,
                    )
                    if city_match:
                        cand = city_match.group(1).strip().split()
                        filtered = [w for w in cand if w.lower() not in _NON_NAME_WORDS]
                        if filtered:
                            val = " ".join(w.capitalize() for w in filtered)
                    if not val and is_slot_target and len(cleaned_words) <= 4:
                        if not cleaned.endswith("?") and not any(cleaned.lower().startswith(q) for q in ("who", "what", "where", "why", "how", "can", "could")):
                            filtered = [w for w in cleaned_words if w.lower() not in _NON_NAME_WORDS]
                            if filtered:
                                val = " ".join(w.capitalize() for w in filtered)

                # COMPANY / WORKPLACE
                elif any(w in slot.name for w in ("company", "organization", "workplace", "work")):
                    comp_match = re.search(
                        r"(?:i work at|working at|work for|company is|at)\s+([A-Za-z0-9\s]+)",
                        cleaned,
                        re.IGNORECASE,
                    )
                    if comp_match:
                        cand = comp_match.group(1).strip().split()
                        filtered = [w for w in cand if w.lower() not in _NON_NAME_WORDS]
                        if filtered:
                            val = " ".join(w.capitalize() for w in filtered)
                    if not val and is_slot_target and len(cleaned_words) <= 5:
                        if not cleaned.endswith("?") and not any(cleaned.lower().startswith(q) for q in ("who", "what", "where", "why", "how", "can", "could")):
                            filtered = [w for w in cleaned_words if w.lower() not in {"i", "am", "at", "my", "the", "a", "an", "is"}]
                            if filtered:
                                val = " ".join(w.capitalize() for w in filtered)

                # DATE
                elif any(w in slot.name for w in ("date", "day")):
                    date_match = re.search(
                        r"\b(tomorrow|today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                        r"\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|"
                        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?|"
                        r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
                        cleaned,
                        re.IGNORECASE,
                    )
                    if date_match:
                        val = date_match.group(0)
                    elif is_slot_target and len(cleaned) >= 3 and not cleaned.endswith("?"):
                        val = cleaned

                # TIME
                elif any(w in slot.name for w in ("time", "timing")):
                    time_match = re.search(
                        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|morning|afternoon|evening|noon|night)\b",
                        cleaned,
                        re.IGNORECASE,
                    )
                    if time_match:
                        val = time_match.group(0)
                    elif is_slot_target and len(cleaned) >= 3 and not cleaned.endswith("?"):
                        val = cleaned

                # BUDGET / PRICE
                elif any(w in slot.name for w in ("budget", "price", "cost", "fee")):
                    budget_match = re.search(
                        r"(?:\$|rs\.?|inr|usd)?\s*(\d+[\d,.]*(?:\s*(?:k|thousand|lakh|crore|million|bucks|dollars|rupees))?)",
                        cleaned,
                        re.IGNORECASE,
                    )
                    if budget_match and budget_match.group(1):
                        val = budget_match.group(0).strip()
                    elif is_slot_target and len(cleaned) >= 2 and not cleaned.endswith("?"):
                        val = cleaned

                # INTENT / REASON
                elif slot.name in ("intent", "purpose", "reason"):
                    for phrase_re in _INTENT_PHRASES:
                        match = phrase_re.search(cleaned)
                        if match:
                            val = match.group(1).strip()
                            break
                    if not val and is_slot_target and len(cleaned) >= 4 and not cleaned.endswith("?") and not _PHONE_REGEX.search(cleaned):
                        val = cleaned

                # GENERIC / CUSTOM FIELD
                else:
                    if is_slot_target:
                        is_question = cleaned.endswith("?") or any(
                            cleaned.lower().startswith(w) for w in ("who", "what", "where", "why", "how", "can you", "could you", "repeat", "pardon")
                        )
                        is_filler = cleaned.lower() in {
                            "yes", "yeah", "yep", "sure", "ok", "okay", "no", "nope",
                            "hello", "hi", "hey", "i am doing great", "doing great", "fine", "good",
                        }
                        if not is_question and not is_filler and len(cleaned) >= 2:
                            c_val = re.sub(r"^(?:my\s+\w+\s+is|it\s+is|it's|i\s+have|i\s+am)\s+", "", cleaned, flags=re.IGNORECASE).strip()
                            val = c_val or cleaned

            if val:
                val = val.strip()
                self.filled_slots[slot.name] = val
                newly_filled[slot.name] = val
                logger.info("Dialogue slot filled: %s = %r", slot.name, val)

        return newly_filled

    def get_unfilled_slots(self, required_only: bool = True) -> list[SlotDefinition]:
        return [
            s for s in self.slots_schema
            if (not required_only or s.required) and (s.name not in self.filled_slots or not self.filled_slots[s.name])
        ]

    def get_next_unfilled_slot(self) -> Optional[SlotDefinition]:
        unfilled = self.get_unfilled_slots(required_only=True)
        return unfilled[0] if unfilled else None

    def all_required_filled(self) -> bool:
        return len(self.get_unfilled_slots(required_only=True)) == 0

    def build_prompt_directive(self, language: str = "en") -> str:
        """
        Generate strict system-prompt steering directives telling the LLM
        what information is collected and what to request next.
        """
        if not self.slots_schema:
            return ""

        collected_lines = []
        for s in self.slots_schema:
            val = self.filled_slots.get(s.name)
            status = f"'{val}' [COLLECTED]" if val else "[MISSING - NOT YET COLLECTED]"
            collected_lines.append(f"- {s.label} ({s.name}): {status}")

        next_slot = self.get_next_unfilled_slot()

        if next_slot:
            question_hint = f" Example question: '{next_slot.prompt_question}'" if next_slot.prompt_question else ""
            if language == "hi":
                goal = (
                    f"अगला आवश्यक कदम: कॉलर से '{next_slot.label}' की जानकारी लें। "
                    f"पहले उनके कथन का संक्षेप में उत्तर दें, फिर विनम्रता से '{next_slot.label}' पूछें।"
                )
            else:
                goal = (
                    f"IMMEDIATE GOAL: Ask the caller for their '{next_slot.label}'.{question_hint} "
                    f"Briefly acknowledge what they said, then naturally and politely ask for this detail."
                )
        else:
            collected_summary = ", ".join(f"{s.label}: {self.filled_slots.get(s.name, '')}" for s in self.slots_schema if self.filled_slots.get(s.name))
            if language == "hi":
                goal = (
                    f"सभी आवश्यक जानकारी एकत्र हो गई है ({collected_summary})! "
                    "पुष्टि करें कि उनके सभी विवरण नोट कर लिए गए हैं, धन्यवाद कहें और कॉल समाप्त करें।"
                )
            else:
                goal = (
                    f"ALL REQUIRED DETAILS COLLECTED ({collected_summary})! "
                    "Confirm the collected details to the contact, thank them warmly, and conclude the call."
                )

        return (
            "\n\n[STRUCTURED DIALOGUE POLICY ACTIVE]\n"
            "Collected caller information so far:\n"
            + "\n".join(collected_lines)
            + f"\n\n{goal}\n"
            "Do not ask for information that is already marked as [COLLECTED] above.\n"
        )

    def to_json(self) -> str:
        return json.dumps(self.filled_slots, ensure_ascii=False)
