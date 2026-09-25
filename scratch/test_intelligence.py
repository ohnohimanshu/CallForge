"""Test script to verify Conversation Intelligence & Audio Recording features."""

import json
import wave
from pathlib import Path
from starlette.testclient import TestClient

from callforge.store.db import PlatformStore
from config import Settings

def test_intelligence():
    db_path = "platform_data/callforge.db"
    store = PlatformStore(db_path)
    
    agents = store.list_agents()
    if not agents:
        agent = store.create_agent(name="Test Agent", extension="9999")
    else:
        agent = agents[0]

    print("1. Testing Call Record intelligence in SQLite store...")
    call = store.start_call(
        agent_id=agent.id,
        call_uuid="test-uuid-12345",
        caller_id="+15551234567",
        ab_variant="B",
    )
    print("Call started:", call.id, "Disposition:", call.disposition, "Sentiment:", call.sentiment)

    # Add turns
    turn1 = store.add_turn(call.id, role="assistant", content="Hello, thanks for calling!", language="en")
    turn2 = store.add_turn(call.id, role="user", content="Thank you so much, this is great.", language="en")
    print(f"Turns added: turn1 offset={turn1.offset_s}s, turn2 offset={turn2.offset_s}s")

    # Update slots
    sample_slots = {"name": "Alice Smith", "phone": "555-0199", "intent": "Account inquiry"}
    store.update_call_slots(call.id, json.dumps(sample_slots))

    # End call with lead captured & positive sentiment
    ended_call = store.end_call(call.id, status="completed", disposition="Lead Captured", sentiment="positive")
    print(f"Ended call: status={ended_call.status}, disposition={ended_call.disposition}, sentiment={ended_call.sentiment}")
    assert ended_call.disposition == "Lead Captured"
    assert ended_call.sentiment == "positive"

    # Test audio file saving
    rec_dir = Path("platform_data/recordings")
    rec_dir.mkdir(parents=True, exist_ok=True)
    wav_file = rec_dir / f"{call.id}.wav"
    
    with wave.open(str(wav_file), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 8000)  # 1 second of silence
    print(f"Saved test recording to {wav_file} ({wav_file.stat().st_size} bytes)")

    print("\n2. Testing API endpoint GET /api/calls/{id} and /api/calls/{id}/audio...")
    from api import create_api
    from unittest.mock import MagicMock
    settings = Settings()
    dummy_runtime = MagicMock()
    app = create_api(settings=settings, store=store, runtime=dummy_runtime, upload_root=Path("platform_data/uploads"))
    client = TestClient(app)

    res = client.get(f"/api/calls/{call.id}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    call_data = res.json()
    print("Call detail API:", {
        "id": call_data["id"],
        "disposition": call_data["disposition"],
        "sentiment": call_data["sentiment"],
        "slots": call_data["slots_json"],
        "turn_count": len(call_data["turns"]),
    })
    assert call_data["disposition"] == "Lead Captured"
    assert call_data["sentiment"] == "positive"
    assert len(call_data["turns"]) == 2

    # Audio endpoint
    audio_res = client.get(f"/api/calls/{call.id}/audio")
    assert audio_res.status_code == 200, f"Expected 200, got {audio_res.status_code}: {audio_res.text}"
    assert audio_res.headers["content-type"] == "audio/wav"
    assert len(audio_res.content) == wav_file.stat().st_size
    print(f"GET /api/calls/{call.id}/audio returned {len(audio_res.content)} bytes of audio/wav successfully!")

    print("\nALL CONVERSATION INTELLIGENCE TESTS PASSED!")

if __name__ == "__main__":
    test_intelligence()
