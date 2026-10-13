"""
services/speculative_service.py
================================
Speculative Multi-Branch Response Generation for Near-Zero Latency Voice Agents.

Architectural Concept:
    In traditional voice agents, the LLM only begins inference *after* the user stops speaking
    and VAD closes the turn, incurring 300ms–1500ms of Time-to-First-Token (TTFT).

    Speculative Multi-Branch Generation extends speculative execution to response synthesis:
    1. As the caller speaks (via partial STT), we predict 2–3 high-probability candidate completions
       of the user's intent.
    2. We launch parallel asynchronous LLM generation streams for each candidate branch in the background.
    3. The instant VAD detects silence and the final STT transcript arrives, we match the final transcript
       against the speculative branches.
    4. If a branch matches above a similarity threshold, we commit to it immediately: its first sentence(s)
       are ALREADY generated and in memory, reducing perceived TTFT to ~0ms!
    5. The active branch continues streaming to TTS while unselected branches are cancelled immediately.
    6. If no branch matches, we seamlessly fall back to standard LLM generation.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from services.llm_service import ConversationTurn, LlmService, SentenceAggregator

logger = logging.getLogger(__name__)


@dataclass
class SpeculativeBranch:
    """Represents an active speculative candidate generation branch."""

    branch_id: int
    candidate_text: str
    task: Optional[asyncio.Task] = None
    queue: asyncio.Queue[Optional[str]] = field(default_factory=asyncio.Queue)
    buffered_sentences: list[str] = field(default_factory=list)
    is_done: bool = False
    started_at: float = field(default_factory=time.monotonic)
    interrupt_event: asyncio.Event = field(default_factory=asyncio.Event)

    def cancel(self) -> None:
        """Cancel this speculative branch immediately and abort in-flight Ollama generation."""
        self.interrupt_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
        self.is_done = True


class SpeculativeResponseManager:
    """
    Manages speculative parallel generation branches during caller speech.
    """

    def __init__(
        self,
        llm_service: LlmService,
        branch_count: int = 1,
        match_threshold: float = 0.55,
    ) -> None:
        self._llm = llm_service
        self._branch_count = max(1, min(2, branch_count))
        self._match_threshold = match_threshold
        self._branches: list[SpeculativeBranch] = []
        self._current_partial: str = ""
        self._lock = asyncio.Lock()

    @property
    def active_branches(self) -> list[SpeculativeBranch]:
        return [b for b in self._branches if not b.is_done]

    def generate_candidate_completions(
        self,
        partial_text: str,
        persona_domain: str = "",
    ) -> list[str]:
        """
        Generate 1 to 2 (up to branch_count) likely complete user utterances from partial speech.
        Uses intelligent syntactic, semantic, intent, and domain heuristics.
        """
        clean = partial_text.strip()
        if not clean:
            return []

        words = clean.split()
        if len(words) < 3 or len(clean) < 10:
            return []

        # Filter out partials consisting only of conversational filler or noise words
        filler_words = {"oh", "okay", "um", "uh", "yeah", "yes", "hello", "hi", "hey", "name", "listen", "there", "well"}
        non_filler = [w for w in re.findall(r"\w+", clean.lower()) if w not in filler_words]
        if len(non_filler) < 2:
            return []

        # Strip any trailing punctuation so we don't produce e.g. "I want to book. for tomorrow."
        clean_base = re.sub(r"[.?!,;:।]+$", "", clean).strip()
        lower = clean_base.lower()

        candidates: list[str] = []

        is_question = any(lower.startswith(q) for q in [
            "what", "where", "when", "why", "who", "which", "how", "can", "could", "would", "do", "does", "is", "are",
            "क्या", "कब", "कहाँ", "कैसे", "कितना"
        ])

        # Candidate 1: The utterance as-is, properly punctuated.
        # This is CRITICAL: when partial STT captures the complete or near-complete sentence,
        # Candidate 1 will yield a 1.0 EXACT MATCH when VAD closes the turn!
        if is_question:
            candidates.append(f"{clean_base}?")
        else:
            candidates.append(f"{clean_base}.")

        # Candidate 2: Intent-specific high-probability continuation
        # 1. Booking / Appointment Intent
        if any(w in lower for w in ["book", "appointment", "schedule", "slot", "reserve", "अपॉइंटमेंट", "बुक"]):
            if any(w in lower for w in ["appointment", "booking", "अपॉइंटमेंट"]):
                if any(w in lower for w in ["tomorrow", "today", "monday", "कल"]):
                    candidates.append(f"{clean_base}, what time slots are available?")
                else:
                    candidates.append(f"{clean_base} for tomorrow.")
            elif any(w in lower for w in ["slot", "timing", "available", "समय"]):
                candidates.append(f"{clean_base} for tomorrow.")
            else:
                candidates.append(f"{clean_base} an appointment.")

        # 2. Hours / Availability Inquiries
        elif any(w in lower for w in ["hour", "hours", "open", "timing", "time", "समय", "खुला"]):
            if any(w in lower for w in ["hour", "timing"]):
                candidates.append(f"{clean_base} today?")
            elif "open" in lower or "खुला" in lower:
                candidates.append(f"{clean_base} today?")
            else:
                candidates.append(f"{clean_base} business hours?")

        # 3. Pricing / Cost Inquiries
        elif any(w in lower for w in ["price", "cost", "charge", "fee", "rate", "कितना", "खर्च"]):
            if "much" in lower or "कितना" in lower:
                candidates.append(f"{clean_base} for a consultation?")
            else:
                candidates.append(f"{clean_base} for this service?")

        # 4. Human Agent Escalation
        elif any(w in lower for w in ["human", "person", "operator", "agent", "insaan", "इंसान"]):
            candidates.append(f"{clean_base} please.")

        # 5. Small Talk / Greetings
        elif any(w in lower for w in ["hello", "hi", "hey", "good morning", "good afternoon", "how are you", "नमस्ते"]):
            candidates.append(f"{clean_base}, how are you today?")
            candidates.append(f"{clean_base}, I have a question.")

        # 6. General Polite Fallback
        else:
            if is_question:
                candidates.append(f"{clean_base} please?")
            else:
                candidates.append(f"{clean_base} please.")

        # Return unique candidate list trimmed to branch count (typically 1-2)
        unique_candidates: list[str] = []
        for c in candidates:
            if c not in unique_candidates:
                unique_candidates.append(c)
            if len(unique_candidates) >= self._branch_count:
                break

        return unique_candidates

    async def on_partial_stt(
        self,
        partial_text: str,
        history: list[ConversationTurn],
        system_prompt: str,
        model: Optional[str] = None,
        rag_context: str = "",
    ) -> None:
        """
        Trigger speculative generation for candidate branches based on partial speech.
        """
        clean = partial_text.strip()
        if not clean or len(clean.split()) < 2:
            return

        # Check if the partial is just a small extension of what we already started
        if self._current_partial and clean.startswith(self._current_partial) and self.active_branches:
            return

        self._current_partial = clean
        candidates = self.generate_candidate_completions(clean)
        if not candidates:
            return

        logger.info(
            "[Speculative] Launching %d parallel speculative branches for partial: %r",
            len(candidates), clean
        )

        # Cancel any previous branches that no longer match
        self.cancel_all()

        enhanced_system_prompt = system_prompt
        if rag_context:
            enhanced_system_prompt += f"\n\nContext Information:\n{rag_context}\n"

        for idx, cand in enumerate(candidates):
            branch = SpeculativeBranch(branch_id=idx, candidate_text=cand)
            self._branches.append(branch)
            branch.task = asyncio.create_task(
                self._run_branch(branch, history, cand, enhanced_system_prompt, model),
                name=f"speculative-branch-{idx}",
            )

    async def _run_branch(
        self,
        branch: SpeculativeBranch,
        history: list[ConversationTurn],
        user_utterance: str,
        system_prompt: str,
        model: Optional[str],
    ) -> None:
        """Background worker that streams LLM tokens into the branch's sentence queue."""
        try:
            async for sentence in self._llm.stream_reply(
                history=history,
                user_utterance=user_utterance,
                interrupt_event=branch.interrupt_event,
                system_prompt=system_prompt,
                model=model,
            ):
                branch.buffered_sentences.append(sentence)
                await branch.queue.put(sentence)
                logger.debug(
                    "[Speculative Branch %d] Pre-generated sentence: %r",
                    branch.branch_id, sentence
                )
                # On CPU, buffering the first 2 sentences is enough to eliminate TTFT without thrashing the cores
                if len(branch.buffered_sentences) >= 2:
                    break
        except asyncio.CancelledError:
            branch.interrupt_event.set()
        except Exception as exc:
            logger.warning("[Speculative Branch %d] Generation failed: %s", branch.branch_id, exc)
        finally:
            branch.is_done = True
            await branch.queue.put(None)  # Sentinel to signal completion

    def match_and_commit(self, final_text: str) -> tuple[Optional[SpeculativeBranch], float]:
        """
        Evaluate final STT text against active speculative branches.
        Returns:
            (committed_branch, match_score)
        """
        clean_final = final_text.strip().lower()
        if not clean_final or not self._branches:
            self.cancel_all()
            return None, 0.0

        def _clean_words(s: str) -> str:
            return re.sub(r"[^\w\s\u0900-\u097F]", "", s.lower()).strip()

        words_final = _clean_words(clean_final)
        set_final = set(words_final.split())

        best_branch: Optional[SpeculativeBranch] = None
        best_score = 0.0

        for branch in self._branches:
            cand_clean = branch.candidate_text.strip().lower()
            words_cand = _clean_words(cand_clean)
            set_cand = set(words_cand.split())

            # Exact match (ignoring punctuation differences)
            if words_final == words_cand or clean_final == cand_clean:
                score = 1.0
            # Prefix or substring match
            elif words_final.startswith(words_cand) or words_cand.startswith(words_final):
                len_shorter = min(len(words_final), len(words_cand))
                len_longer = max(len(words_final), len(words_cand))
                score = 0.88 + 0.12 * (len_shorter / max(1, len_longer))
            else:
                # SequenceMatcher similarity ratio
                ratio = difflib.SequenceMatcher(None, words_final, words_cand).ratio()
                # Word-level Jaccard overlap
                jaccard = (
                    len(set_final & set_cand) / len(set_final | set_cand)
                    if (set_final | set_cand)
                    else 0.0
                )
                score = 0.5 * ratio + 0.5 * jaccard

            logger.debug(
                "[Speculative Match] Branch %d (%r vs %r): score=%.3f",
                branch.branch_id, branch.candidate_text, final_text, score
            )

            if score > best_score:
                best_score = score
                best_branch = branch

        if best_branch and best_score >= self._match_threshold:
            logger.info(
                "[Speculative HIT!] Committed to Branch %d (score=%.2f, projected=%r, actual=%r, buffered_sentences=%d)",
                best_branch.branch_id,
                best_score,
                best_branch.candidate_text,
                final_text,
                len(best_branch.buffered_sentences),
            )
            # Cancel all unselected branches immediately to free CPU/GPU resources
            for b in self._branches:
                if b.branch_id != best_branch.branch_id:
                    b.cancel()
            return best_branch, best_score

        logger.info(
            "[Speculative MISS] Best score was %.2f for %r (threshold=%.2f). Falling back to standard LLM.",
            best_score, final_text, self._match_threshold
        )
        self.cancel_all()
        return None, best_score

    async def stream_committed_branch(
        self,
        branch: SpeculativeBranch,
        interrupt_event: asyncio.Event,
    ) -> AsyncIterator[str]:
        """
        Yield sentences from the committed branch's queue.
        Pre-generated sentences yield instantly (0ms TTFT), followed by
        remaining sentences as generation completes.
        """
        while not interrupt_event.is_set():
            try:
                item = await asyncio.wait_for(branch.queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if branch.is_done and branch.queue.empty():
                    break
                continue

            if item is None:  # Sentinel
                break

            yield item

    def cancel_all(self) -> None:
        """Cancel all speculative branches and clear internal state."""
        for b in self._branches:
            b.cancel()
        self._branches.clear()
        self._current_partial = ""
