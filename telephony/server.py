"""
telephony/server.py
====================
Asynchronous TCP server implementing the Asterisk AudioSocket endpoint.

Architectural decision:
    Each accepted connection becomes one `VoiceSession`, an isolated unit
    of state (inbound/outbound audio queues, cancellation event, pipeline
    task). Sessions never share mutable state, so concurrent calls cannot
    interfere with one another and a crash in one call's pipeline cannot
    corrupt another. The server's only responsibilities are: accept
    connections, frame/deframe AudioSocket messages, and hand raw PCM to
    (and pull synthesized PCM from) a `VoiceSession`. All conversational
    intelligence lives in `pipeline.py` (Single Responsibility Principle).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from config import TelephonySettings
from telephony.protocol import (
    AudioSocketMessage,
    AudioSocketProtocolError,
    MessageKind,
    encode_audio_frame,
    encode_hangup,
    read_message,
)

logger = logging.getLogger(__name__)

# A pipeline factory takes an active VoiceSession and drives it to completion.
PipelineFactory = Callable[["VoiceSession"], Awaitable[None]]


@dataclass(slots=True)
class VoiceSession:
    """
    Per-call state shared between the network layer and the AI pipeline.

    Attributes:
        call_id: The UUID Asterisk assigned to this call.
        caller_id: The telephone number or identifier of the caller.
        inbound_audio: Queue of raw 8kHz/16-bit PCM frames received from the caller.
            `None` is pushed as a sentinel to signal the caller hung up.
        outbound_audio: Queue of raw 8kHz/16-bit PCM frames to be sent to the caller.
        barge_in_event: Set whenever new caller speech is detected; the pipeline's
            TTS/LLM stage watches this to support interruption.
        closed: True once the underlying socket has been torn down.
    """

    call_id: uuid.UUID
    caller_id: str = "unknown"
    inbound_audio: "asyncio.Queue[Optional[bytes]]" = field(default_factory=lambda: asyncio.Queue(maxsize=500))
    outbound_audio: "asyncio.Queue[Optional[bytes]]" = field(default_factory=lambda: asyncio.Queue(maxsize=500))
    barge_in_event: asyncio.Event = field(default_factory=asyncio.Event)
    hangup_event: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False

    def request_hangup(self) -> None:
        """Signal that this session should terminate (from either side)."""
        self.hangup_event.set()
        try:
            self.inbound_audio.put_nowait(None)
        except Exception:
            pass
        try:
            self.outbound_audio.put_nowait(None)
        except Exception:
            pass


class AudioSocketServer:
    """
    TCP server that speaks the Asterisk AudioSocket protocol and delegates
    per-call conversational logic to an injected pipeline factory.
    """

    def __init__(self, settings: TelephonySettings, pipeline_factory: PipelineFactory) -> None:
        self._settings = settings
        self._pipeline_factory = pipeline_factory
        self._server: Optional[asyncio.base_events.Server] = None
        self._active_sessions: dict[uuid.UUID, VoiceSession] = {}
        self._call_semaphore = asyncio.Semaphore(settings.max_concurrent_calls)

    async def start(self) -> None:
        """Bind and begin accepting AudioSocket connections."""
        self._server = await asyncio.start_server(
            self._handle_connection, host=self._settings.host, port=self._settings.port
        )
        sockets = ", ".join(str(sock.getsockname()) for sock in self._server.sockets or [])
        logger.info("AudioSocket server listening on %s", sockets)

    async def serve_forever(self) -> None:
        """Start (if needed) and block until the server is stopped."""
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Gracefully close the listening socket and all active sessions."""
        for session in list(self._active_sessions.values()):
            session.request_hangup()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        logger.info("AudioSocket server stopped")

    @property
    def active_sessions(self) -> dict[uuid.UUID, VoiceSession]:
        """Return a snapshot of active calls on this AudioSocket server."""
        return dict(self._active_sessions)

    def hangup_session(self, call_uuid: uuid.UUID | str) -> bool:
        """Signal hangup to an active session by UUID."""
        if isinstance(call_uuid, str):
            try:
                call_uuid = uuid.UUID(call_uuid)
            except ValueError:
                return False
        session = self._active_sessions.get(call_uuid)
        if session:
            session.request_hangup()
            logger.info("Manually requested hangup for call session %s", call_uuid)
            return True
        return False

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Per-connection entry point: handshake, then run reader/writer/pipeline concurrently."""
        peer = writer.get_extra_info("peername")
        async with self._call_semaphore:
            try:
                call_id = await self._perform_handshake(reader)
            except (AudioSocketProtocolError, asyncio.IncompleteReadError) as exc:
                logger.warning("Handshake failed from %s: %s", peer, exc)
                writer.close()
                return

            # outbound_audio's maxsize doubles as the hard cap on how much
            # already-synthesized TTS audio can be pre-buffered ahead of
            # real-time playback (see _write_loop's real-time pacing).
            # Wired to TelephonySettings.outbound_queue_max_frames rather
            # than left at an unrelated hardcoded default, since a larger
            # cap here directly means more buffered audio that has to be
            # drained on barge-in before playback actually stops.
            caller_id = "unknown"
            caller_id_candidates = [
                Path("asterisk-server/calls") / f"{call_id}.callerid",
                Path("/app/asterisk-server/calls") / f"{call_id}.callerid",
                Path("/etc/asterisk/calls") / f"{call_id}.callerid",
                Path(f"/tmp/callforge_calls/{call_id}.callerid"),
            ]
            for candidate in caller_id_candidates:
                if candidate.exists():
                    try:
                        cid = candidate.read_text(encoding="utf-8").strip()
                        if cid:
                            caller_id = cid
                            logger.info("Call %s: identified caller_id=%r from %s", call_id, caller_id, candidate)
                    except Exception as exc:
                        logger.debug("Failed reading caller_id from %s: %s", candidate, exc)
                    try:
                        candidate.unlink(missing_ok=True)
                    except Exception:
                        pass
                    if caller_id != "unknown":
                        break

            session = VoiceSession(
                call_id=call_id,
                caller_id=caller_id,
                outbound_audio=asyncio.Queue(maxsize=self._settings.outbound_queue_max_frames),
            )
            self._active_sessions[call_id] = session
            logger.info("Call %s connected from %s (caller_id=%s)", call_id, peer, caller_id)

            try:
                await self._run_session(session, reader, writer)
            finally:
                self._active_sessions.pop(call_id, None)
                session.closed = True
                try:
                    writer.write(encode_hangup())
                    await asyncio.wait_for(writer.drain(), timeout=1.0)
                except (ConnectionError, OSError, asyncio.TimeoutError):
                    pass
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                except (ConnectionError, OSError, asyncio.TimeoutError):
                    pass
                logger.info("Call %s disconnected", call_id)

    async def _perform_handshake(self, reader: asyncio.StreamReader) -> uuid.UUID:
        """The first AudioSocket message on a new connection must be the call UUID."""
        message = await read_message(reader)
        if message.kind is not MessageKind.UUID:
            raise AudioSocketProtocolError(f"Expected UUID as first message, got {message.kind!r}")
        return message.call_uuid

    async def _run_session(
        self, session: VoiceSession, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """
        Run the three concurrent tasks that make up a live call:
          1. `_read_loop`   - deframe inbound audio, push to session.inbound_audio
          2. `_write_loop`  - pull session.outbound_audio, frame + send to caller
          3. pipeline task  - VAD -> STT -> LLM -> TTS orchestration (external)

        All three are cancelled together the moment any one of them finishes
        (hangup, protocol error, or pipeline completion), preventing orphaned
        tasks or leaked queues.
        """
        read_task = asyncio.create_task(self._read_loop(session, reader), name=f"read-{session.call_id}")
        write_task = asyncio.create_task(self._write_loop(session, writer), name=f"write-{session.call_id}")
        pipeline_task = asyncio.create_task(self._pipeline_factory(session), name=f"pipeline-{session.call_id}")
        hangup_wait = asyncio.create_task(session.hangup_event.wait(), name=f"hangup-{session.call_id}")

        tasks = {read_task, write_task, pipeline_task, hangup_wait}
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not hangup_wait and task.exception() is not None:
                    logger.exception("Session %s task %s failed", session.call_id, task.get_name(), exc_info=task.exception())
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # Unblock anything still awaiting the outbound queue (e.g. write loop).
            try:
                session.outbound_audio.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _read_loop(self, session: VoiceSession, reader: asyncio.StreamReader) -> None:
        """Continuously decode inbound AudioSocket messages until hangup/EOF."""
        try:
            while True:
                try:
                    message = await read_message(reader)
                except asyncio.IncompleteReadError:
                    logger.info("Call %s: peer closed connection", session.call_id)
                    break

                if message.kind is MessageKind.AUDIO:
                    await session.inbound_audio.put(message.payload)
                elif message.kind is MessageKind.HANGUP:
                    logger.info("Call %s: received HANGUP from Asterisk", session.call_id)
                    break
                elif message.kind is MessageKind.ERROR:
                    logger.warning("Call %s: received ERROR frame from Asterisk", session.call_id)
                    break
                elif message.kind is MessageKind.DTMF:
                    digit = message.payload.decode("ascii", errors="replace") if message.payload else ""
                    logger.info("Call %s: DTMF digit received: %s", session.call_id, digit)
                # KIND_UUID after handshake is unexpected but not fatal; ignore.
        except AudioSocketProtocolError as exc:
            logger.warning("Call %s: protocol error, closing: %s", session.call_id, exc)
        finally:
            await session.inbound_audio.put(None)  # sentinel: end of caller audio
            session.request_hangup()

    async def _write_loop(self, session: VoiceSession, writer: asyncio.StreamWriter) -> None:
        """
        Continuously frame and flush outbound PCM to the caller at real-time
        pace (one 20ms frame roughly every 20ms of wall-clock time).

        Each frame represents a fixed 20ms of audio; if we write frames to
        the socket faster than that (which asyncio will happily do with no
        pacing at all -- limited only by drain()/TCP backpressure), Asterisk
        receives and plays them back sped up, which sounds like fast,
        broken/clipped speech. We track an expected next-send timestamp
        against `time.monotonic()` and sleep out the difference before each
        write, with drift correction (computed from the fixed frame
        interval and elapsed frame count, not accumulated sleep durations)
        so small scheduling jitter doesn't compound into audible drift over
        a long TTS utterance.
        """
        frame_interval_s = (self._settings.frame_bytes / 2) / self._settings.sample_rate_hz  # 20ms for 320B@8kHz
        loop = asyncio.get_running_loop()
        stream_start_time: Optional[float] = None
        frame_index = 0

        try:
            while True:
                chunk = await session.outbound_audio.get()
                if chunk is None:  # sentinel: pipeline finished / hangup requested
                    break
                if session.barge_in_event.is_set():
                    continue

                now = loop.time()
                if stream_start_time is None:
                    stream_start_time = now
                    frame_index = 0
                expected_send_time = stream_start_time + frame_index * frame_interval_s
                delay = expected_send_time - now
                if delay > 0:
                    await asyncio.sleep(delay)
                elif delay < -frame_interval_s * 4:
                    # We've fallen badly behind (e.g. after a GC pause or a
                    # burst of queued frames) -- resync to "now" rather than
                    # trying to catch up by firing a backlog of frames
                    # instantly, which would just reproduce the same bug.
                    stream_start_time = loop.time()
                    frame_index = 0

                writer.write(encode_audio_frame(chunk))
                await writer.drain()
                frame_index += 1
        except (ConnectionError, OSError) as exc:
            logger.info("Call %s: write loop terminated (%s)", session.call_id, exc)
        finally:
            try:
                writer.write(encode_hangup())
                await asyncio.wait_for(writer.drain(), timeout=1.0)
            except (ConnectionError, OSError, asyncio.TimeoutError):
                pass