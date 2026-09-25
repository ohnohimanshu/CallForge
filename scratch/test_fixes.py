import asyncio
import os
import sqlite3
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from callforge.runtime.tools import BookingToolManager, book_sheet_appointment, check_sheet_availability
from callforge.store.db import PlatformStore, AgentRecord
from config import Settings
from pipeline import CallPipeline, AgentPersona
from telephony.server import VoiceSession


class MockSttService:
    async def transcribe_stream(self, *args, **kwargs):
        pass
    async def transcribe_pcm16(self, *args, **kwargs):
        pass
    async def transcribe_partial_pcm16(self, *args, **kwargs):
        pass


class MockLlmService:
    async def stream_reply(self, *args, **kwargs):
        yield "Hello there! Your appointment is being scheduled."


class MockTtsService:
    async def synthesize_streaming(self, text, interrupt_event, **kwargs):
        # Yield 5 frames of 16-bit 8kHz PCM
        for _ in range(5):
            if interrupt_event.is_set():
                break
            yield b"\x00\x10" * 160  # 20ms frame


class MockRagService:
    def retrieve_context(self, query):
        return ""


async def test_tools_booking_fallback():
    print("\n=== Testing Booking Fallback ===")
    manager = BookingToolManager("https://mock-sheet-webhook.com/exec")
    manager.available_slots = ["11:00 AM", "12:00 PM"]
    manager.target_date = "2026-09-21"
    manager.raw_slots_map = {"11:00 AM": "11:00 AM"}
    manager.raw_dates_map = {"11:00 AM": "2026-09-20T18:30:00.000Z"}
    manager.chosen_slot = "11:00 AM"
    manager.state = "awaiting_details"

    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 200
    mock_resp_fail.json.return_value = {"status": "error", "message": "Slot unavailable or not found"}

    mock_resp_succ = MagicMock()
    mock_resp_succ.status_code = 200
    mock_resp_succ.json.return_value = {
        "status": "success",
        "message": "Appointment confirmed",
        "date": "2026-09-20T18:30:00.000Z",
        "slot": "11:00 AM",
    }

    with patch("callforge.runtime.tools._get_tools_http_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=[mock_resp_fail, mock_resp_succ])
        mock_client_factory.return_value = mock_client

        reply, _, event = await manager.evaluate_turn("My name is Imansu and my number is 9457139175")
        print("Reply:", reply)
        print("Event:", event)
        assert manager.state == "booked", f"Expected state 'booked', got '{manager.state}'"
        assert event is not None and event["status"] == "confirmed"
        assert "11:00 AM" not in manager.available_slots
        assert "Thank you Imansu!" in reply
        print("Booking Fallback Test PASSED!")


async def test_pipeline_cancellation_and_recording_save():
    print("\n=== Testing Pipeline Hard Cancellation & Recording Save ===")
    store = PlatformStore("platform_data/callforge.db")
    # Ensure a test agent exists
    agents = store.list_agents()
    agent = agents[0] if agents else store.create_agent(AgentRecord(id=str(uuid.uuid4()), name="TestAgent"))

    call_uuid = uuid.uuid4()
    session = VoiceSession(call_id=call_uuid, caller_id="+19998887777")
    settings = Settings()
    persona = AgentPersona(
        name="TestRias",
        system_prompt="You are a helpful booking agent.",
        greeting_text="Hello, how can I help you today?",
        initial_silence_timeout_s=5.0,
        agent_id=agent.id,
    )
    events = []
    pipeline = CallPipeline(
        session=session,
        settings=settings,
        stt=MockSttService(),
        llm=MockLlmService(),
        tts=MockTtsService(),
        persona=persona,
        rag=MockRagService(),
        store=store,
        on_event=lambda ev: events.append(ev),
    )

    pipeline_task = asyncio.create_task(pipeline.run(), name="test-pipeline")
    await asyncio.sleep(0.1)

    # Inject utterance so TTS generates audio into pipeline._recorded_audio_pcm
    print("Injecting user utterance...")
    await pipeline.inject_user_utterance("Hello I want to book an appointment")
    await asyncio.sleep(0.2)

    # Abruptly cancel the pipeline_task (simulating caller hangup or browser disconnect)
    print("Hard-cancelling pipeline_task...")
    pipeline_task.cancel()
    try:
        await pipeline_task
    except asyncio.CancelledError:
        pass

    # Verify recording file exists and is valid WAV
    wav_path = Path("platform_data/recordings") / f"{call_uuid}.wav"
    assert wav_path.exists(), f"Recording {wav_path} does not exist!"
    file_size = wav_path.stat().st_size
    assert file_size > 44, f"Recording file is empty or missing WAV header (size={file_size})"
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 8000
    print(f"Recording verified successfully! ({file_size} bytes, 8kHz WAV)")

    # Verify DB status
    call_rec = store.get_call_by_uuid(str(call_uuid))
    assert call_rec is not None, "Call record not found in DB!"
    print(f"Call record: status={call_rec.status}, duration={call_rec.duration_s}s, ended_at={call_rec.ended_at}")
    assert call_rec.status == "completed", f"Expected 'completed', got '{call_rec.status}'"
    assert call_rec.ended_at != "", "ended_at was not populated!"
    assert call_rec.duration_s >= 0.0, f"duration_s invalid: {call_rec.duration_s}"
    print("Pipeline Cancellation & Recording Save Test PASSED!")


if __name__ == "__main__":
    asyncio.run(test_tools_booking_fallback())
    asyncio.run(test_pipeline_cancellation_and_recording_save())
