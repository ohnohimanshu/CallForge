"""
processing/conversational_flow.py
==================================
Conversational turn-taking flow engine:
  Acoustic Backchanneling: Natural human acknowledgments ("Mmhmm", "Right", "I see", "हाँ", "जी")
  spoken softly during caller micro-pauses (300-600ms) without taking the conversational floor.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Quick acknowledgment tokens for backchanneling during caller pauses
BACKCHANNELS_EN = [
    "Mmhmm.",
    "Right.",
    "I see.",
    "Got it.",
]

BACKCHANNELS_HI = [
    "हाँ।",
    "जी।",
    "हाँ, बिल्कुल।",
]


class ConversationalFlowEngine:
    """
    Manages conversational turn-taking dynamics: acoustic backchannel timing during caller monologues.
    """

    def __init__(self, backchannel_cooldown_s: float = 6.0) -> None:
        self._backchannel_cooldown_s = backchannel_cooldown_s
        self._last_backchannel_time: float = 0.0

    def should_backchannel(
        self,
        current_time: float,
        consecutive_speech_s: float,
        silence_run_ms: float,
        is_speaking: bool,
    ) -> bool:
        """
        Determine if the current acoustic moment is ideal for a natural backchannel:
          - Agent is not currently speaking
          - Caller has been speaking for at least 1.8 seconds (substantial monologue)
          - Caller is in a brief breathing pause (300ms <= pause <= 600ms)
          - At least `backchannel_cooldown_s` has passed since the last backchannel
        """
        if is_speaking:
            return False

        if (current_time - self._last_backchannel_time) < self._backchannel_cooldown_s:
            return False

        if consecutive_speech_s < 1.8:
            return False

        # Micro-pause detection: caller is pausing to breathe, but turn is not yet finished
        if 320.0 <= silence_run_ms <= 580.0:
            # 70% probability to feel organic and non-mechanical
            if random.random() < 0.70:
                self._last_backchannel_time = current_time
                return True

        return False

    def get_backchannel_text(self, language: str = "en") -> str:
        """Select an organic backchannel phrase."""
        choices = BACKCHANNELS_HI if language == "hi" else BACKCHANNELS_EN
        return random.choice(choices)
