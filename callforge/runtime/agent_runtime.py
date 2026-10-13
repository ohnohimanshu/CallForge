"""Live AudioSocket listeners for deployed agents — start/stop without process restart."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import Settings
from callforge.runtime.asterisk_manager import reload_asterisk
from callforge.runtime.dialplan import write_agents_dialplan
from callforge.runtime.voices import telephony_settings_for_port, tts_settings_for_agent
from callforge.store.db import PlatformStore
from callforge.store.models import AgentRecord
from pipeline import AgentPersona, build_pipeline_factory
from services.llm_service import LlmService
from services.rag_service import RagService
from services.stt_service import SttService
from services.tts_service import TtsService
from telephony.server import AudioSocketServer

logger = logging.getLogger(__name__)


@dataclass
class _LiveLine:
    agent_id: str
    server: AudioSocketServer
    serve_task: asyncio.Task
    port: int
    tts: Optional[TtsService] = None


class AgentRuntime:
    """
    Owns shared STT/LLM plus one AudioSocket listener per deployed agent.
    Deploy/undeploy hot-swaps lines without unloading Whisper/Ollama.
    """

    def __init__(
        self,
        settings: Settings,
        store: PlatformStore,
        dialplan_path: Path,
        ollama_base_url: str,
    ) -> None:
        self._settings = settings
        self._store = store
        self._dialplan_path = dialplan_path
        self._ollama_base_url = ollama_base_url
        self._stt: Optional[SttService] = None
        self._llm: Optional[LlmService] = None
        self._lines: dict[str, _LiveLine] = {}
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self._stt is not None and self._llm is not None

    async def start(self) -> None:
        logger.info("AgentRuntime: loading shared STT + LLM...")
        self._stt = SttService(self._settings.stt)
        self._llm = LlmService(self._settings.llm)
        await self._llm.warm_up()
        for agent in self._store.list_deployed_agents():
            await self._start_line(agent)
        await self._sync_dialplan()
        logger.info("AgentRuntime ready (%d live agent line(s))", len(self._lines))

    async def shutdown(self) -> None:
        async with self._lock:
            for agent_id in list(self._lines):
                await self._stop_line_unlocked(agent_id)
        if self._llm is not None:
            await self._llm.aclose()
            self._llm = None
        if self._stt is not None:
            self._stt.shutdown()
            self._stt = None

    async def deploy(self, agent_id: str) -> AgentRecord:
        async with self._lock:
            agent = self._store.get_agent(agent_id)
            if agent is None:
                raise KeyError(f"agent {agent_id} not found")
            if agent.status == "deployed" and agent_id in self._lines:
                return agent

            port = agent.port or self._store.allocate_port(self._settings.telephony.port)
            agent = self._store.update_agent(agent_id, status="deployed", port=port)
            assert agent is not None
            if agent_id in self._lines:
                await self._stop_line_unlocked(agent_id)
            await self._start_line(agent)
            await self._sync_dialplan()
            return agent

    async def undeploy(self, agent_id: str) -> AgentRecord:
        async with self._lock:
            agent = self._store.get_agent(agent_id)
            if agent is None:
                raise KeyError(f"agent {agent_id} not found")
            if agent_id in self._lines:
                await self._stop_line_unlocked(agent_id)
            agent = self._store.update_agent(agent_id, status="stopped")
            assert agent is not None
            await self._sync_dialplan()
            return agent

    async def reload_agent(self, agent_id: str) -> AgentRecord:
        """Restart a live line after config edits (prompt/voice/model)."""
        async with self._lock:
            agent = self._store.get_agent(agent_id)
            if agent is None:
                raise KeyError(f"agent {agent_id} not found")
            if agent.status != "deployed":
                return agent
            if agent_id in self._lines:
                await self._stop_line_unlocked(agent_id)
            await self._start_line(agent)
            await self._sync_dialplan()
            return agent

    def live_status(self) -> list[dict]:
        return [
            {"agent_id": aid, "port": line.port, "listening": not line.serve_task.done()}
            for aid, line in self._lines.items()
        ]

    def get_live_calls(self) -> list[dict]:
        """Collect all currently active calls across all deployed agent lines."""
        now = datetime.now(timezone.utc)
        results = []
        for aid, line in self._lines.items():
            agent = self._store.get_agent(aid)
            agent_name = agent.name if agent else "Unknown"
            agent_ext = agent.extension if agent else ""
            for call_uuid in line.server.active_sessions:
                call_rec = self._store.get_call_by_uuid(str(call_uuid))
                duration = 0.0
                if call_rec and call_rec.started_at:
                    try:
                        start_dt = datetime.fromisoformat(call_rec.started_at)
                        duration = max(0.0, (now - start_dt).total_seconds())
                    except Exception:
                        duration = 0.0
                results.append({
                    "call_uuid": str(call_uuid),
                    "call_id": call_rec.id if call_rec else str(call_uuid),
                    "agent_id": aid,
                    "agent_name": agent_name,
                    "extension": agent_ext,
                    "port": line.port,
                    "caller_id": call_rec.caller_id if call_rec else "unknown",
                    "started_at": call_rec.started_at if call_rec else now.isoformat(),
                    "duration_s": round(duration, 1),
                    "ab_variant": call_rec.ab_variant if call_rec else "A",
                    "status": "active",
                })
        return results

    def hangup_call(self, call_uuid: str) -> bool:
        """Terminate an active call by UUID across all live agent lines."""
        for line in self._lines.values():
            if line.server.hangup_session(call_uuid):
                call_rec = self._store.get_call_by_uuid(call_uuid)
                if call_rec:
                    self._store.end_call(call_rec.id, status="completed", disposition="Terminated by Operator")
                return True
        return False

    def check_sip_trunk(self) -> dict:
        """Probe Asterisk SIP connectivity and list configured endpoints."""
        reachable = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.4)
            s.connect(("127.0.0.1", 5060))
            reachable = True
            s.close()
        except Exception:
            reachable = False

        phone_exts = [p.extension for p in self._store.list_phones()]
        endpoints = list(dict.fromkeys(phone_exts + ["guest", "anonymous"]))
        return {
            "host": "127.0.0.1",
            "port": 5060,
            "protocol": "SIP / UDP",
            "reachable": reachable,
            "codecs": ["ulaw", "alaw", "slin16"],
            "configured_endpoints": endpoints,
        }

    def get_wallboard_data(self) -> dict:
        """Aggregate real-time metrics for the Live Call Wallboard."""
        live_calls = self.get_live_calls()
        total_active = len(live_calls)
        max_capacity = self._settings.telephony.max_concurrent_calls
        occupancy_pct = round((total_active / max(1, max_capacity)) * 100, 1)
        sip_trunk = self.check_sip_trunk()

        lines = []
        for aid, line in self._lines.items():
            agent = self._store.get_agent(aid)
            lines.append({
                "agent_id": aid,
                "agent_name": agent.name if agent else "Unknown",
                "extension": agent.extension if agent else "",
                "port": line.port,
                "listening": not line.serve_task.done(),
                "active_calls": len(line.server.active_sessions),
                "llm_model": agent.llm_model if agent else "",
                "language": agent.language if agent else "auto",
                "ab_testing": agent.ab_testing_enabled if agent else False,
                "dialogue_policy": agent.dialogue_policy_enabled if agent else False,
            })

        return {
            "system": {
                "telephony_ready": sip_trunk["reachable"],
                "runtime_ready": self.ready,
                "total_active_calls": total_active,
                "concurrent_capacity": max_capacity,
                "channel_occupancy_pct": occupancy_pct,
            },
            "sip_trunk": sip_trunk,
            "active_calls": live_calls,
            "lines": lines,
        }

    async def _start_line(self, agent: AgentRecord) -> None:
        assert self._stt is not None and self._llm is not None
        if not agent.port:
            raise ValueError(f"agent {agent.id} has no port")

        cloned_path = agent.cloned_voice_sample_path if agent.voice_cloning_enabled else None
        persona = AgentPersona(
            name=agent.name,
            system_prompt=agent.system_prompt,
            greeting_text=agent.greeting_text,
            initial_silence_timeout_s=self._settings.llm.initial_silence_timeout_s,
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
            voice_cloning_enabled=agent.voice_cloning_enabled,
            cloned_voice_sample_path=agent.cloned_voice_sample_path,
            speculative_generation_enabled=agent.speculative_generation_enabled,
            speculative_branch_count=agent.speculative_branch_count,
        )
        tts = TtsService(
            tts_settings_for_agent(agent, self._settings.tts),
            telephony_settings_for_port(self._settings.telephony, agent.port),
            cloned_voice_path=cloned_path,
        )

        persona_b = None
        tts_b = None
        if agent.ab_testing_enabled:
            persona_b = AgentPersona(
                name=f"{agent.name} (Variant B)",
                system_prompt=agent.ab_variant_b_prompt or agent.system_prompt,
                greeting_text=agent.ab_variant_b_greeting or agent.greeting_text,
                initial_silence_timeout_s=self._settings.llm.initial_silence_timeout_s,
                agent_id=agent.id,
                language=agent.language,
                llm_model=agent.ab_variant_b_llm_model or agent.llm_model,
                ab_variant="B",
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
                voice_cloning_enabled=agent.voice_cloning_enabled,
                cloned_voice_sample_path=agent.cloned_voice_sample_path,
                speculative_generation_enabled=agent.speculative_generation_enabled,
                speculative_branch_count=agent.speculative_branch_count,
            )
            from callforge.runtime.voices import tts_settings_for_agent_variant_b
            tts_b = TtsService(
                tts_settings_for_agent_variant_b(agent, self._settings.tts),
                telephony_settings_for_port(self._settings.telephony, agent.port),
                cloned_voice_path=cloned_path,
            )

        rag = RagService(
            ollama_base_url=self._ollama_base_url,
            collection_name=f"agent_{agent.id.replace('-', '')[:16]}",
        )
        factory = build_pipeline_factory(
            settings=self._settings,
            stt=self._stt,
            llm=self._llm,
            tts=tts,
            persona=persona,
            rag=rag,
            store=self._store,
            persona_b=persona_b,
            tts_b=tts_b,
            ab_split_ratio=agent.ab_split_ratio,
        )

        telephony = telephony_settings_for_port(self._settings.telephony, agent.port)
        server = AudioSocketServer(telephony, factory)
        await server.start()
        task = asyncio.create_task(server.serve_forever(), name=f"agent-{agent.id[:8]}")
        self._lines[agent.id] = _LiveLine(
            agent_id=agent.id, server=server, serve_task=task, port=agent.port, tts=tts
        )
        logger.info(
            "Deployed agent '%s' on :%d (ext %s, model=%s)",
            agent.name, agent.port, agent.extension, agent.llm_model,
        )

    async def _stop_line_unlocked(self, agent_id: str) -> None:
        line = self._lines.pop(agent_id, None)
        if line is None:
            return
        await line.server.stop()
        line.serve_task.cancel()
        try:
            await line.serve_task
        except asyncio.CancelledError:
            pass
        if getattr(line, "tts", None) is not None:
            try:
                line.tts.shutdown()
            except Exception as e:
                logger.warning("Error shutting down TTS for line %s: %s", agent_id, e)
        import gc
        gc.collect()
        logger.info("Stopped agent line %s (port %d)", agent_id, line.port)

    async def _sync_dialplan(self) -> dict:
        agents = self._store.list_deployed_agents()
        write_agents_dialplan(agents, self._dialplan_path)
        logger.info("Wrote dialplan → %s (%d agents)", self._dialplan_path, len(agents))
        reload_result = await reload_asterisk()
        logger.info("Asterisk auto-reload status: %s", reload_result)
        return reload_result

