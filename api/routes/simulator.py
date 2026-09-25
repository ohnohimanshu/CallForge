"""
api/routes/simulator.py
=======================
In-Browser Web Audio Test Console WebSocket endpoint.
Allows real-time voice and text simulation of agents directly in the browser
without requiring a physical phone or SIP softphone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from config import TelephonySettings
from callforge.runtime.voices import telephony_settings_for_port, tts_settings_for_agent
from pipeline import AgentPersona, CallPipeline
from services.llm_service import LlmService
from services.rag_service import RagService
from services.stt_service import SttService
from services.tts_service import TtsService
from telephony.server import VoiceSession

logger = logging.getLogger(__name__)

router = APIRouter()

_tts_cache: dict[tuple[str, str], TtsService] = {}
_tts_cache_lock = asyncio.Lock()


async def _get_or_create_tts(agent: Any, settings: Any) -> TtsService:
    cloned_path = agent.cloned_voice_sample_path if getattr(agent, "voice_cloning_enabled", False) else None
    key = (str(agent.voice_en), str(agent.voice_hi), str(cloned_path))
    async with _tts_cache_lock:
        if key not in _tts_cache:
            port = agent.port or 9000
            tts_settings = tts_settings_for_agent(agent, settings.tts)
            sim_telephony = TelephonySettings(
                host=settings.telephony.host,
                port=port,
                sample_rate_hz=settings.telephony.sample_rate_hz,
                frame_bytes=settings.telephony.frame_bytes,
                max_concurrent_calls=2,
                outbound_queue_max_frames=settings.telephony.outbound_queue_max_frames,
            )
            _tts_cache[key] = TtsService(tts_settings, sim_telephony, cloned_voice_path=cloned_path)
        return _tts_cache[key]


@router.websocket("/agents/{agent_id}/simulator/ws")
async def agent_simulator_ws(websocket: WebSocket, agent_id: str) -> None:
    """
    WebSocket endpoint for in-browser interactive testing.
    Bi-directional transport:
      - Client -> Server: 8kHz 16-bit mono PCM chunks (binary) or JSON control/text messages
      - Server -> Client: 8kHz 16-bit mono PCM synthesized frames (binary) or JSON state/transcript/latency events
    """
    await websocket.accept()

    app = websocket.app
    store = app.state.store
    settings = app.state.settings
    runtime = app.state.runtime
    upload_root = app.state.upload_root

    agent = store.get_agent(agent_id)
    if agent is None:
        await websocket.send_json({"type": "error", "message": f"Agent {agent_id} not found"})
        await websocket.close(code=4004)
        return

    try:
        # Ensure shared STT and LLM services are initialized
        if runtime._stt is None:
            runtime._stt = SttService(settings.stt)
        if runtime._llm is None:
            runtime._llm = LlmService(settings.llm)
            await runtime._llm.warm_up()

        # Create AgentPersona
        persona = AgentPersona(
            name=agent.name,
            system_prompt=agent.system_prompt,
            greeting_text=agent.greeting_text,
            initial_silence_timeout_s=settings.llm.initial_silence_timeout_s,
            agent_id=agent.id,
            language=agent.language,
            llm_model=agent.llm_model,
            ab_variant="A",
            handoff_enabled=agent.handoff_enabled,
            handoff_extension=agent.handoff_extension,
            handoff_fallback_threshold=agent.handoff_fallback_threshold,
            handoff_message=agent.handoff_message,
            handoff_message_hi=agent.handoff_message_hi,
            dialogue_policy_enabled=agent.dialogue_policy_enabled,
            dialogue_slots_json=agent.dialogue_slots_json,
            multilingual_routing=agent.multilingual_routing,
            lang_confidence_threshold=agent.lang_confidence_threshold,
            fallback_language=agent.fallback_language,
            supported_languages=agent.supported_languages,
            tools_enabled=agent.tools_enabled,
            tools_webhook_url=agent.tools_webhook_url,
            voice_cloning_enabled=getattr(agent, "voice_cloning_enabled", False),
            cloned_voice_sample_path=getattr(agent, "cloned_voice_sample_path", None),
            speculative_generation_enabled=getattr(agent, "speculative_generation_enabled", False),
            speculative_branch_count=getattr(agent, "speculative_branch_count", 3),
        )

        tts = await _get_or_create_tts(agent, settings)
        rag = RagService(
            ollama_base_url=settings.llm.base_url,
            collection_name=f"agent_{agent.id.replace('-', '')[:16]}",
        )

        call_id = uuid.uuid4()
        caller_id = websocket.query_params.get("caller_id", "unknown").strip() or "unknown"
        session = VoiceSession(call_id=call_id, caller_id=caller_id)

        # Thread-safe event dispatcher to WebSocket client
        async def on_event(ev: dict[str, Any]) -> None:
            if websocket.client_state == WebSocketState.CONNECTED:
                try:
                    await websocket.send_json(ev)
                except Exception:
                    pass

        pipeline = CallPipeline(
            session=session,
            settings=settings,
            stt=runtime._stt,
            llm=runtime._llm,
            tts=tts,
            persona=persona,
            rag=rag,
            store=store,
            on_event=on_event,
        )

        pipeline_task = asyncio.create_task(pipeline.run(), name=f"simulator-pipeline-{call_id}")

        # Outbound audio task: streams 8kHz PCM16 binary chunks to browser
        async def outbound_streamer() -> None:
            try:
                while not session.closed and not session.hangup_event.is_set():
                    frame = await session.outbound_audio.get()
                    if frame is None:
                        break
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_bytes(frame)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Simulator outbound error: %s", exc)

        outbound_task = asyncio.create_task(outbound_streamer(), name=f"simulator-outbound-{call_id}")

        # Notify browser that connection is established
        await websocket.send_json({
            "type": "connected",
            "call_id": str(call_id),
            "agent_name": agent.name,
            "sample_rate": 8000,
            "greeting": agent.greeting_text,
        })
    except Exception as init_err:
        logger.exception("Failed to initialize simulator pipeline: %s", init_err)
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"type": "error", "message": f"Initialization failed: {init_err}"})
                await websocket.close(code=1011)
        except Exception:
            pass
        return

    # Inbound message loop: receives microphone PCM or JSON controls
    inbound_buffer = bytearray()
    try:
        while not session.closed and not session.hangup_event.is_set():
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if "bytes" in msg and msg["bytes"]:
                inbound_buffer.extend(msg["bytes"])
                chunk_size = 320
                while len(inbound_buffer) >= chunk_size:
                    chunk = bytes(inbound_buffer[:chunk_size])
                    del inbound_buffer[:chunk_size]
                    try:
                        session.inbound_audio.put_nowait(chunk)
                    except asyncio.QueueFull:
                        pass
            elif "text" in msg and msg["text"]:
                try:
                    payload = json.loads(msg["text"])
                    p_type = payload.get("type")
                    if p_type == "hangup":
                        session.request_hangup()
                        break
                    elif p_type == "text_input":
                        user_text = payload.get("text", "").strip()
                        if user_text:
                            asyncio.create_task(pipeline.inject_user_utterance(user_text))
                    elif p_type == "interrupt":
                        session.barge_in_event.set()
                except Exception as parse_err:
                    logger.warning("Error parsing simulator text payload: %s", parse_err)
    except WebSocketDisconnect:
        logger.info("Simulator client disconnected: %s", call_id)
    except Exception as exc:
        logger.warning("Simulator loop exception: %s", exc)
    finally:
        session.closed = True
        session.request_hangup()
        if not outbound_task.done():
            outbound_task.cancel()
        if not pipeline_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(pipeline_task), timeout=0.6)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                if not pipeline_task.done():
                    pipeline_task.cancel()
        await asyncio.gather(outbound_task, pipeline_task, return_exceptions=True)
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass
        logger.info("Simulator session closed for call %s", call_id)
