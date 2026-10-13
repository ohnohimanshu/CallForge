import asyncio
import os
import json
import sqlite3
from callforge.store.models import AgentRecord, CallRecord
from callforge.store.db import PlatformStore
from callforge.runtime.dialplan import render_agent_extension
from callforge.runtime.dialogue import DialogueStateTracker, SlotDefinition, STANDARD_SLOTS_PRESET
from processing.vad import BargeInDetector, compute_frame_rms
from config import VadSettings

def test_db_migration_and_queries():
    store = PlatformStore("platform_data/callforge.db")
    # Verify tables have new columns
    with store._connect() as conn:
        agent_cols = [r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]
        assert "handoff_enabled" in agent_cols
        assert "handoff_extension" in agent_cols
        assert "handoff_fallback_threshold" in agent_cols
        assert "handoff_message" in agent_cols
        assert "ab_testing_enabled" in agent_cols
        assert "ab_split_ratio" in agent_cols
        assert "dialogue_policy_enabled" in agent_cols
        assert "dialogue_slots_json" in agent_cols
        assert "multilingual_routing" in agent_cols

        call_cols = [r[1] for r in conn.execute("PRAGMA table_info(calls)").fetchall()]
        assert "ab_variant" in call_cols
        assert "handoff_to" in call_cols
        assert "slots_json" in call_cols
    print("✓ DB Schema migration verified successfully")

    # Test AB stats
    agents = store.list_agents()
    if agents:
        stats = store.get_ab_stats(agents[0].id)
        assert "a" in stats and "b" in stats
        print(f"✓ AB stats query verified: {stats}")

def test_barge_in():
    from processing.vad import VadEngine
    vad_settings = VadSettings(barge_in_speech_threshold=0.68, barge_in_min_speech_ms=160, barge_in_min_rms=220.0)
    vad_engine = VadEngine(vad_settings, source_sample_rate_hz=8000, frame_bytes=320)
    detector = BargeInDetector(
        vad_engine=vad_engine,
        speech_threshold=vad_settings.barge_in_speech_threshold,
        min_speech_ms=vad_settings.barge_in_min_speech_ms,
        min_rms=vad_settings.barge_in_min_rms,
    )

    # Frame of quiet silence
    quiet_frame = b"\x00\x00" * 160  # 160 samples (20ms at 8kHz)
    is_barge, prob, rms = detector.check_frame(quiet_frame)
    assert is_barge is False
    assert rms < 10.0
    print("✓ Barge-in noise immunity verified")

def test_dialogue_tracker():
    tracker = DialogueStateTracker.from_json(json.dumps(STANDARD_SLOTS_PRESET))
    assert len(tracker.slots_schema) == 3
    
    # Caller gives their name
    tracker.extract_from_utterance("Hi, my name is John Doe and I need help with my bill.")
    assert tracker.filled_slots.get("name") == "John Doe"

    # Caller gives phone number
    tracker.extract_from_utterance("My phone number is 415-555-2671.")
    assert tracker.filled_slots.get("phone") == "4155552671"

    # Check prompt directive
    directive = tracker.build_prompt_directive()
    assert "John Doe" in directive
    assert "4155552671" in directive
    print("✓ Dialogue slot filling and prompt directive verified")

def test_dialplan_handoff():
    agent = AgentRecord(
        id="test-agent-1",
        name="Test",
        extension="2000",
        port=9001
    )
    rendered = render_agent_extension(agent)
    assert "AudioSocket" in rendered
    assert "Goto(internal,${TARGET},1)" in rendered
    assert "handoff/${CALL_UUID}.target" in rendered
    print("✓ Asterisk dialplan forwarding verified")

if __name__ == "__main__":
    test_db_migration_and_queries()
    test_barge_in()
    test_dialogue_tracker()
    test_dialplan_handoff()
    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
