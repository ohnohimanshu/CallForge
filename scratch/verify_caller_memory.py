"""
Verification script for Cross-Call Memory & Caller Recognition.
Tests:
1. PlatformStore database methods (upsert, get, list, delete)
2. CallerMemoryService formatting, topic extraction, context building, and greeting generation
3. Full lifecycle simulation: Call 1 (first-time caller) -> Hangup & Profile Creation -> Call 2 (returning caller recognition)
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# Ensure project root is in sys.path
sys.path.insert(0, "/home/himanshu/Downloads/calling_agent")

from callforge.store.db import PlatformStore
from callforge.store.models import AgentRecord, CallerProfileRecord
from services.caller_memory_service import caller_memory_service


def test_caller_memory_service_unit():
    print("--- 1. Testing CallerMemoryService Unit Functions ---")

    # Phone normalization
    norm = caller_memory_service.normalize_phone("+1 (555) 019-2831")
    assert norm == "+15550192831", f"Unexpected norm: {norm}"
    print(f"✓ Phone normalization: {norm}")

    # Relative time
    now_utc = datetime.now(timezone.utc)
    just_now = caller_memory_service.format_relative_time(now_utc.isoformat())
    assert "moment" in just_now or "min" in just_now, f"Unexpected relative time: {just_now}"
    print(f"✓ Relative time (now): {just_now}")

    three_days_ago = (now_utc - timedelta(days=3)).isoformat()
    rel_3d = caller_memory_service.format_relative_time(three_days_ago)
    assert "3 days ago" in rel_3d, f"Unexpected relative time: {rel_3d}"
    print(f"✓ Relative time (3 days ago): {rel_3d}")

    # Topic extraction
    topic1 = caller_memory_service.extract_topic_from_summary("Caller requested to book a dental cleaning appointment for next Tuesday.")
    assert "appointment" in topic1.lower(), f"Unexpected topic: {topic1}"
    print(f"✓ Topic extraction: '{topic1}'")

    # Context building
    profile = CallerProfileRecord(
        phone_number="+15551234567",
        name="Sarah Connor",
        call_count=2,
        last_call_at=three_days_ago,
        last_disposition="appointment_booked",
        last_sentiment="frustrated",
        last_summary="Caller called about rescheduling an appointment and was frustrated about wait times.",
    )
    context = caller_memory_service.build_caller_context(profile)
    assert "RETURNING CALLER RECOGNITION" in context
    assert "Sarah Connor" in context
    assert "frustrated" in context
    assert "3 days ago" in context
    print("✓ Caller context generated:")
    for line in context.splitlines():
        print(f"  | {line}")

    # Greeting generation (English)
    greeting_en = caller_memory_service.generate_returning_greeting(profile, agent_name="Rias", language="en")
    print(f"✓ English returning greeting: '{greeting_en}'")
    assert "Sarah" in greeting_en
    assert "appointment" in greeting_en.lower()

    # Greeting generation (Hindi)
    greeting_hi = caller_memory_service.generate_returning_greeting(profile, agent_name="Rias", language="hi")
    print(f"✓ Hindi returning greeting: '{greeting_hi}'")
    assert "Sarah" in greeting_hi


def test_store_database_integration():
    print("\n--- 2. Testing PlatformStore Database Methods ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_callforge.db")
        store = PlatformStore(db_path)

        phone = "+15559876543"

        # Initially non-existent
        assert store.get_caller_profile(phone) is None
        print(f"✓ Profile for {phone} correctly None initially")

        # Call 1: upsert profile
        p1 = store.upsert_caller_profile(
            phone_number=phone,
            name="Alice Walker",
            summary="Alice inquired about product pricing and requested a callback.",
            disposition="callback_requested",
            sentiment="neutral",
        )
        assert p1.phone_number == phone
        assert p1.name == "Alice Walker"
        assert p1.call_count == 1
        assert p1.last_disposition == "callback_requested"
        assert p1.last_sentiment == "neutral"
        assert "pricing" in p1.last_summary
        print(f"✓ Call 1 profile stored: {p1.name}, call_count={p1.call_count}")

        # Fetch from DB to verify persistence
        fetched1 = store.get_caller_profile(phone)
        assert fetched1 is not None
        assert fetched1.call_count == 1
        assert fetched1.name == "Alice Walker"

        # Call 2: upsert profile again
        p2 = store.upsert_caller_profile(
            phone_number=phone,
            name="",  # didn't re-specify name, should preserve Alice Walker
            summary="Alice called back to complete the purchase.",
            disposition="sale_completed",
            sentiment="positive",
        )
        assert p2.call_count == 2
        assert p2.name == "Alice Walker"
        assert p2.last_disposition == "sale_completed"
        assert p2.last_sentiment == "positive"
        assert len(p2.past_summaries) == 2
        assert len(p2.sentiment_history) == 2
        print(f"✓ Call 2 profile updated: {p2.name}, call_count={p2.call_count}, past_summaries={len(p2.past_summaries)}")

        # List profiles
        profiles = store.list_caller_profiles()
        assert len(profiles) == 1
        assert profiles[0].phone_number == phone
        print(f"✓ list_caller_profiles returned {len(profiles)} record(s)")

        # Delete profile
        deleted = store.delete_caller_profile(phone)
        assert deleted is True
        assert store.get_caller_profile(phone) is None
        print("✓ delete_caller_profile successfully removed profile")


async def test_full_call_lifecycle_simulation():
    print("\n--- 3. Testing Full Call Lifecycle (Call 1 -> Hangup -> Call 2 Recognition) ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_callforge.db")
        store = PlatformStore(db_path)

        test_phone = "+15554321098"

        # --- CALL 1: First time caller ---
        print("\n--- Simulating Call 1 (New Caller: +15554321098) ---")
        profile_call1 = store.get_caller_profile(test_phone)
        assert profile_call1 is None, "Expected no profile before Call 1"
        print("✓ Call 1: Caller is unknown, no returning memory injected.")

        # Simulate conversation transcript during Call 1
        transcript_call1 = [
            {"role": "assistant", "content": "Hello! How can I help you today?"},
            {"role": "user", "content": "Hi, my name is Robert. I would like to book an appointment for dental cleaning next Tuesday."},
            {"role": "assistant", "content": "I would be happy to book that dental cleaning for you on Tuesday. Let me check the schedule."},
            {"role": "user", "content": "Great, thank you!"},
        ]

        # Summarize Call 1
        summary_call1 = await caller_memory_service.summarize_call(
            user_turns=["Hi, my name is Robert. I would like to book an appointment for dental cleaning next Tuesday."],
            assistant_turns=["I would be happy to book that dental cleaning for you on Tuesday. Let me check the schedule."],
            disposition="Lead Captured",
            sentiment="positive",
        )
        print(f"✓ Call 1 Summary generated: '{summary_call1}'")

        # Save profile at end of Call 1
        store.upsert_caller_profile(
            phone_number=test_phone,
            name="Robert",
            summary=summary_call1,
            disposition="appointment_booked",
            sentiment="positive",
        )
        print("✓ Call 1 saved to database and ended.")

        # --- CALL 2: Returning caller ---
        print("\n--- Simulating Call 2 (Returning Caller: +15554321098) ---")
        profile_call2 = store.get_caller_profile(test_phone)
        assert profile_call2 is not None, "Expected profile to exist for Call 2"
        assert profile_call2.name == "Robert"
        assert profile_call2.call_count == 1
        print(f"✓ Call 2: Recognized returning caller {profile_call2.name}! Past calls: {profile_call2.call_count}")

        # Generate returning context
        caller_context = caller_memory_service.build_caller_context(profile_call2)
        assert "Robert" in caller_context
        assert "appointment" in caller_context.lower()
        print(f"✓ Returning context generated:\n{caller_context}\n")

        # Generate personalized returning greeting
        greeting = caller_memory_service.generate_returning_greeting(profile_call2, agent_name="Rias", language="en")
        print(f"✓ Personalized recognition greeting spoken to caller:\n  '{greeting}'")
        assert "Robert" in greeting
        assert "appointment" in greeting.lower() or "following up" in greeting.lower()
        print("✓ Verified: Persona opened with exact recognition of caller and past appointment!")


if __name__ == "__main__":
    test_caller_memory_service_unit()
    test_store_database_integration()
    asyncio.run(test_full_call_lifecycle_simulation())
    print("\n🎉 ALL CROSS-CALL MEMORY & CALLER RECOGNITION TESTS PASSED!")
