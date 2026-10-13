from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CannedIntent(str, Enum):
    GREETING = "greeting"
    THANKS = "thanks"
    CAPABILITY = "capability"
    FAREWELL = "farewell"
    ACKNOWLEDGE = "acknowledge"


@dataclass(frozen=True, slots=True)
class CannedResponse:
    """A predefined reply for one intent, in both supported languages."""

    intent: CannedIntent
    text_en: str
    text_hi: str


# One predefined reply per intent. Edit these freely -- this is the
# actual spoken text, in both languages, for each canned intent.
CANNED_RESPONSES: dict[CannedIntent, CannedResponse] = {
    CannedIntent.GREETING: CannedResponse(
        intent=CannedIntent.GREETING,
        text_en="I'm doing great, thanks for asking! How can I help you today?",
        text_hi="मैं बढ़िया हूँ, थैंक्स! बताओ मैं आपकी क्या मदद कर सकता हूँ?",
    ),
    CannedIntent.THANKS: CannedResponse(
        intent=CannedIntent.THANKS,
        text_en="You're welcome! Anything else I can help with?",
        text_hi="कोई बात नहीं! कुछ और पूछना है क्या?",
    ),
    CannedIntent.CAPABILITY: CannedResponse(
        intent=CannedIntent.CAPABILITY,
        text_en="I can answer questions and help you out right here on the call -- just ask me anything.",
        text_hi="मैं फ़ोन पर आपके सवालों के जवाब दे सकता हूँ और मदद कर सकता हूँ -- कुछ भी पूछो।",
    ),
    CannedIntent.FAREWELL: CannedResponse(
        intent=CannedIntent.FAREWELL,
        text_en="Alright, take care! Bye!",
        text_hi="ठीक है, ख़याल रखना! बाय!",
    ),
    CannedIntent.ACKNOWLEDGE: CannedResponse(
        intent=CannedIntent.ACKNOWLEDGE,
        text_en="Got it.",
        text_hi="ठीक है।",
    ),
}


# Normalized trigger phrase -> intent. Phrases are matched WHOLE against
# the normalized transcript (see `_normalize`), not as substrings. Add
# more variants here as you notice real callers phrasing these
# differently -- this table is meant to be grown from your call logs.
_TRIGGERS: dict[str, CannedIntent] = {
    # -- English greetings --
    "hi": CannedIntent.GREETING,
    "hello": CannedIntent.GREETING,
    "hey": CannedIntent.GREETING,
    "hi there": CannedIntent.GREETING,
    "how are you": CannedIntent.GREETING,
    "how are you doing": CannedIntent.GREETING,
    "how are you doing today": CannedIntent.GREETING,
    "whats up": CannedIntent.GREETING,
    # -- Hindi/Hinglish greetings (Devanagari, as Whisper transcribes them) --
    "कैसे हो": CannedIntent.GREETING,
    "आप कैसे हैं": CannedIntent.GREETING,
    "तुम कैसे हो": CannedIntent.GREETING,
    "क्या हाल है": CannedIntent.GREETING,
    "क्या हाल चाल है": CannedIntent.GREETING,
    "कैसी हो": CannedIntent.GREETING,

    # -- English thanks --
    "thank you": CannedIntent.THANKS,
    "thanks": CannedIntent.THANKS,
    "thank you so much": CannedIntent.THANKS,
    "thanks a lot": CannedIntent.THANKS,
    "thank you very much": CannedIntent.THANKS,
    # -- Hindi thanks --
    "धन्यवाद": CannedIntent.THANKS,
    "शुक्रिया": CannedIntent.THANKS,
    "थैंक्स": CannedIntent.THANKS,
    "थैंक यू": CannedIntent.THANKS,
    "बहुत बहुत धन्यवाद": CannedIntent.THANKS,

    # -- English capability --
    "what can you do": CannedIntent.CAPABILITY,
    "what do you do": CannedIntent.CAPABILITY,
    "who are you": CannedIntent.CAPABILITY,
    "what are you": CannedIntent.CAPABILITY,
    "how can you help me": CannedIntent.CAPABILITY,
    # -- Hindi capability --
    "तुम क्या कर सकते हो": CannedIntent.CAPABILITY,
    "आप क्या कर सकते हैं": CannedIntent.CAPABILITY,
    "तुम कौन हो": CannedIntent.CAPABILITY,
    "आप कौन हैं": CannedIntent.CAPABILITY,
    "आप मेरी क्या मदद कर सकते हैं": CannedIntent.CAPABILITY,

    # -- English farewell --
    "bye": CannedIntent.FAREWELL,
    "goodbye": CannedIntent.FAREWELL,
    "ok bye": CannedIntent.FAREWELL,
    "okay bye": CannedIntent.FAREWELL,
    "see you": CannedIntent.FAREWELL,
    "bye bye": CannedIntent.FAREWELL,
    # -- Hindi farewell --
    "अलविदा": CannedIntent.FAREWELL,
    "बाय": CannedIntent.FAREWELL,
    "ठीक है बाय": CannedIntent.FAREWELL,
    "चलता हूं": CannedIntent.FAREWELL,
    "चलती हूं": CannedIntent.FAREWELL,

    # -- English acknowledge/filler --
    "ok": CannedIntent.ACKNOWLEDGE,
    "okay": CannedIntent.ACKNOWLEDGE,
    "alright": CannedIntent.ACKNOWLEDGE,
    "fine": CannedIntent.ACKNOWLEDGE,
    "cool": CannedIntent.ACKNOWLEDGE,
    # -- Hindi acknowledge/filler --
    "ठीक है": CannedIntent.ACKNOWLEDGE,
    "अच्छा": CannedIntent.ACKNOWLEDGE,
    "हाँ ठीक है": CannedIntent.ACKNOWLEDGE,
    "समझ गया": CannedIntent.ACKNOWLEDGE,
    "समझ गई": CannedIntent.ACKNOWLEDGE,
}

_PUNCT_RE = re.compile(r"[.,!?।;:'\"]")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_WORDS = 6  # transcripts longer than this are never treated as canned-only


def _normalize(text: str) -> str:
    """
    Lowercase, strip punctuation/diacritics, collapse whitespace -- keeps
    matching robust to Whisper's minor formatting variance (a trailing
    '.', a stray '?', double spaces, Devanagari's own '।' punctuation)
    without needing fuzzy/approximate matching.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.strip().lower()
    text = _PUNCT_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def match_canned_response(transcript: str) -> Optional[CannedResponse]:
    """
    Return a `CannedResponse` if `transcript` is a (near-)exact match for
    one of the known trivial trigger phrases, else None.

    Deliberately requires the WHOLE normalized transcript to match (see
    module docstring) and caps matching at `_MAX_WORDS` words -- a longer
    utterance that happens to contain "thanks" partway through is a real
    question and must reach the LLM, not get short-circuited here.
    """
    normalized = _normalize(transcript)
    if not normalized:
        return None
    if len(normalized.split()) > _MAX_WORDS:
        return None
    intent = _TRIGGERS.get(normalized)
    if intent is None:
        return None
    return CANNED_RESPONSES[intent]