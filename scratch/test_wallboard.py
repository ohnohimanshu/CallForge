"""Verification test for P4 Live Call Wallboard API and runtime control."""

import uuid
import asyncio
from pathlib import Path
from starlette.testclient import TestClient
from unittest.mock import MagicMock

from config import Settings
from callforge.store.db import PlatformStore
from callforge.runtime.agent_runtime import AgentRuntime
from api import create_api
from telephony.server import VoiceSession

def test_wallboard():
    db_path = "platform_data/callforge.db"
    store = PlatformStore(db_path)
    settings = Settings()

    print("1. Initializing AgentRuntime & testing wallboard data aggregation...")
    dialplan_path = Path("platform_data/extensions_test.conf")
    runtime = AgentRuntime(
        settings=settings,
        store=store,
        dialplan_path=dialplan_path,
        ollama_base_url="http://localhost:11434",
    )

    # Mock an active live line with an AudioSocket server and active session
    fake_server = MagicMock()
    fake_call_uuid = uuid.uuid4()
    fake_session = VoiceSession(call_id=fake_call_uuid)
    fake_server.active_sessions = {fake_call_uuid: fake_session}
    fake_server.hangup_session.side_effect = lambda uid: fake_session.request_hangup() or True

    fake_task = MagicMock()
    fake_task.done.return_value = False

    from callforge.runtime.agent_runtime import _LiveLine
    deployed_agents = store.list_deployed_agents()
    test_agent_id = deployed_agents[0].id if deployed_agents else "test-agent"
    runtime._lines[test_agent_id] = _LiveLine(
        agent_id=test_agent_id,
        server=fake_server,
        serve_task=fake_task,
        port=9099,
    )

    wb_data = runtime.get_wallboard_data()
    print("Wallboard data keys:", list(wb_data.keys()))
    print("System status:", wb_data["system"])
    print("SIP trunk status:", wb_data["sip_trunk"])
    print("Active calls detected:", len(wb_data["active_calls"]))
    print("Agent lines reporting:", len(wb_data["lines"]))

    assert wb_data["system"]["total_active_calls"] == 1
    assert wb_data["active_calls"][0]["call_uuid"] == str(fake_call_uuid)
    assert wb_data["lines"][0]["listening"] is True

    print("\n2. Testing Wallboard API endpoints via FastAPI TestClient...")
    app = create_api(settings=settings, store=store, runtime=runtime, upload_root=Path("platform_data/uploads"))
    client = TestClient(app)

    # Test GET /api/wallboard/status
    res = client.get("/api/wallboard/status")
    assert res.status_code == 200, f"Status failed: {res.status_code} {res.text}"
    api_wb = res.json()
    assert api_wb["system"]["total_active_calls"] == 1
    assert api_wb["active_calls"][0]["call_uuid"] == str(fake_call_uuid)
    print("GET /api/wallboard/status returned valid payload.")

    # Test GET /api/wallboard/live-calls
    calls_res = client.get("/api/wallboard/live-calls")
    assert calls_res.status_code == 200
    assert len(calls_res.json()) == 1
    print("GET /api/wallboard/live-calls returned active calls list.")

    # Test POST /api/wallboard/calls/{uuid}/hangup
    print("\n3. Testing remote supervisor hangup trigger...")
    assert not fake_session.hangup_event.is_set(), "Session should not be hung up yet"
    hangup_res = client.post(f"/api/wallboard/calls/{fake_call_uuid}/hangup")
    assert hangup_res.status_code == 200, f"Hangup failed: {hangup_res.status_code} {hangup_res.text}"
    assert hangup_res.json()["ok"] is True
    assert fake_session.hangup_event.is_set(), "Session should have received hangup event"
    print(f"Hangup trigger successfully signaled session termination for {fake_call_uuid}!")

    print("\nALL WALLBOARD INTEGRATION TESTS PASSED!")

if __name__ == "__main__":
    test_wallboard()
