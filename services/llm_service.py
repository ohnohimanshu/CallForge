"""
services/llm_service.py
========================
Streaming client for a local Ollama instance, with a sentence-boundary
aggregator that dispatches complete phrases to TTS as soon as they're
available rather than waiting for the full generation to finish.

Architectural decision:
    Time-to-first-audio (TTFA) is dominated by how quickly we can hand the
    *first* speakable sentence to TTS. `LlmService.stream_reply` therefore
    yields `str` sentence chunks as an async generator the moment a
    sentence boundary is detected in the token stream, rather than
    returning one accumulated string at the end. The regex-based
    `SentenceAggregator` is deliberately simple (no NLP dependency) since
    correctness matters less than *latency* here — a slightly imperfect
    split (e.g. on "Mr.") is far cheaper than adding a heavyweight
    sentence-tokenizer to the hot path.

    Interruption/barge-in is handled by accepting an `asyncio.Event` that,
    when set, causes the generator to stop pulling further tokens and the
    underlying HTTP stream to be closed immediately (no wasted generation).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx

from config import LlmSettings

logger = logging.getLogger(__name__)

# Split on sentence-ending punctuation: period, exclamation, question mark, newline, or Hindi purna viram (।)
# Deliberately NOT splitting on every comma or semicolon to prevent short clause fragments (e.g. "Yes,", "Well,")
# from being synthesized in isolation, which causes Piper prosody glitches and weird high-pitch spikes.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?।\n])\s+")
_LONG_CLAUSE_BOUNDARY = re.compile(r"(?<=[,;:])\s+")


@dataclass
class ConversationTurn:
    """One turn in the rolling chat history sent to Ollama."""

    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class SentenceAggregator:
    """
    Buffers streamed LLM tokens and yields complete sentences/clauses as
    soon as a boundary is detected, so downstream TTS can start speaking
    before the LLM has finished generating the full reply.
    """

    min_chars: int
    _buffer: str = field(default="", repr=False)
    _first_chunk_emitted: bool = field(default=False, repr=False)

    def feed(self, token: str) -> list[str]:
        """Add a token; return zero or more complete sentences now ready to speak."""
        self._buffer += token

        # For the FIRST chunk, emit early only on short natural conversational openers
        # e.g. "Sure,", "Hello,", "Certainly,", "Yes,", "No problem,"
        # This reduces Time-to-First-Audio (TTFA) without chopping normal compound sentences.
        if not self._first_chunk_emitted:
            early_match = re.split(r"(?<=[,;:!?-])\s+", self._buffer, maxsplit=1)
            if len(early_match) > 1 and 3 <= len(early_match[0].strip()) <= 20:
                first_chunk = early_match[0].strip()
                self._buffer = early_match[1]
                self._first_chunk_emitted = True
                return [first_chunk]

        parts = _SENTENCE_BOUNDARY.split(self._buffer)
        if len(parts) > 1:
            complete, self._buffer = parts[:-1], parts[-1]
            self._first_chunk_emitted = True
            return [p.strip() for p in complete if len(p.strip()) >= self.min_chars]

        # For truly long run-on sentences without punctuation,
        # split on comma/semicolon only if buffer exceeds 70 chars
        if len(self._buffer) >= 70:
            clause_parts = _LONG_CLAUSE_BOUNDARY.split(self._buffer)
            if len(clause_parts) > 1 and len(clause_parts[0].strip()) >= self.min_chars:
                complete, self._buffer = clause_parts[:-1], clause_parts[-1]
                self._first_chunk_emitted = True
                return [p.strip() for p in complete if len(p.strip()) >= self.min_chars]

        return []

    def flush(self) -> Optional[str]:
        """Call once generation ends; returns any remaining trailing fragment."""
        remainder = self._buffer.strip()
        self._buffer = ""
        if len(remainder) >= self.min_chars:
            return remainder
        return None


class LlmService:
    """Async streaming facade over Ollama's `/api/chat` endpoint."""

    def __init__(self, settings: LlmSettings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(base_url=settings.base_url, timeout=settings.request_timeout_s)

    async def stream_reply(
        self,
        history: list[ConversationTurn],
        user_utterance: str,
        interrupt_event: asyncio.Event,
        system_prompt: Optional[str] = None,
        sentence_min_chars: int = 6,
        model: Optional[str] = None,
        max_sentences: Optional[int] = 2,
        **kwargs,
    ) -> AsyncIterator[str]:
        """
        Stream an assistant reply for `user_utterance` given `history`,
        yielding complete sentences as they become available. Stops early
        (closing the HTTP stream) if `interrupt_event` is set or if `max_sentences`
        have been yielded to prevent run-on rambling on phone calls.
        """
        effective_system_prompt = system_prompt if system_prompt is not None else self._settings.system_prompt
        effective_model = model if model else self._settings.model
        messages = [{"role": "system", "content": effective_system_prompt}]
        messages.extend({"role": t.role, "content": t.content} for t in history)
        messages.append({"role": "user", "content": user_utterance})

        options = {
            "temperature": self._settings.temperature,
            "num_predict": self._settings.num_predict,
        }
        if self._settings.num_thread is not None:
            options["num_thread"] = self._settings.num_thread

        payload = {
            "model": effective_model,
            "messages": messages,
            "stream": True,
            "keep_alive": self._settings.keep_alive,
            "options": options,
        }

        aggregator = SentenceAggregator(min_chars=sentence_min_chars)
        emitted_sentences = 0
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                async for raw_line in response.aiter_lines():
                    if interrupt_event.is_set():
                        logger.info("LLM stream interrupted by barge-in")
                        return
                    if not raw_line.strip():
                        continue
                    chunk = json.loads(raw_line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        for sentence in aggregator.feed(token):
                            yield sentence
                            emitted_sentences += 1
                            if max_sentences and emitted_sentences >= max_sentences:
                                return
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            logger.error("Ollama request failed: %s", exc)
            return

        if not interrupt_event.is_set() and (not max_sentences or emitted_sentences < max_sentences):
            trailing = aggregator.flush()
            if trailing:
                yield trailing

    async def warm_up(self) -> None:
        """
        Send a minimal, throwaway request so Ollama loads the model into
        memory (and JIT/graph-compiles whatever it needs to) *before* the
        first real caller's turn, rather than paying that cold-start cost
        as part of their time-to-first-token. Call once from application
        startup, after construction and before accepting calls.

        `num_predict: 1` keeps this cheap -- we only care that the model
        gets loaded and resident, not about the (discarded) output.
        `keep_alive` matches the connection-level default so the model
        stays warm through the gaps between real calls too.
        """
        payload = {
            "model": self._settings.model,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
            "keep_alive": self._settings.keep_alive,
            "options": {"num_predict": 1},
        }
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            logger.info("LLM warm-up complete (model '%s' resident in memory)", self._settings.model)
        except httpx.HTTPError as exc:
            logger.warning(
                "LLM warm-up failed (model will cold-load on first real call instead): %s", exc
            )

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool. Call at application shutdown."""
        await self._client.aclose()