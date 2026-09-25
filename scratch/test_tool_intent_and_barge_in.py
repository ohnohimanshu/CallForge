"""
scratch/test_tool_intent_and_barge_in.py
=========================================
Verify the fixes for:
1. BookingToolManager false-positive intent detection & topic switching
2. extract_name_phone false name extraction
3. Speculative multi-branch candidate filtering
"""

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from callforge.runtime.tools import (
    _BOOKING_INTENT_RE,
    _CANCEL_INTENT_RE,
    BookingToolManager,
    extract_name_phone,
)
from services.speculative_service import SpeculativeResponseManager
from services.llm_service import LlmService
from config import LlmSettings


def test_booking_intent_regex():
    print("\n--- Test 1: Booking Intent Regex Accuracy ---")
    false_positives = [
        "How can I improve my sleep cycle?",
        "How can I stop what we're thinking?",
        "What I asked earlier.",
        "I overthink a lot.",
        "Welcome to my state phone.",
        "What do you mean by that?",
        "Which technique is better?",
        "Feel free to share your thoughts.",
        "I don't have much free time.",
    ]
    for text in false_positives:
        matched = bool(_BOOKING_INTENT_RE.search(text))
        print(f"'{text}' -> matched={matched}")
        assert not matched, f"False positive match on: '{text}'"

    true_positives = [
        "I want to book an appointment",
        "Can I schedule a consultation tomorrow?",
        "What are the available slots for Monday?",
        "Any slots available today?",
        "Check availability for tomorrow",
        "मुझे अपॉइंटमेंट बुक करना है",
    ]
    for text in true_positives:
        matched = bool(_BOOKING_INTENT_RE.search(text))
        print(f"'{text}' -> matched={matched}")
        assert matched, f"Expected match on: '{text}'"

    print("Booking intent regex test PASSED!\n")


def test_name_extraction():
    print("--- Test 2: Name Extraction Guardrails ---")
    bad_texts = [
        "I overthink a lot",
        "Welcome to my state phone",
        "How can I stop",
        "What I asked earlier",
        "Not right now",
    ]
    for t in bad_texts:
        name, phone, _ = extract_name_phone(t, allow_standalone=False)
        print(f"'{t}' (allow_standalone=False) -> name='{name}', phone='{phone}'")
        assert not name, f"Extracted false name '{name}' from '{t}'"

    good_texts = [
        ("My name is Himanshu", "Himanshu"),
        ("I am Rahul Sharma", "Rahul Sharma"),
        ("This is Alice", "Alice"),
    ]
    for t, expected in good_texts:
        name, _, _ = extract_name_phone(t, allow_standalone=False)
        print(f"'{t}' -> name='{name}'")
        assert name.lower() == expected.lower(), f"Expected '{expected}', got '{name}'"

    # Standalone name when explicitly prompted
    name, _, _ = extract_name_phone("Himanshu", allow_standalone=True)
    assert name == "Himanshu", f"Expected 'Himanshu', got '{name}'"
    print("Name extraction test PASSED!\n")


async def test_booking_manager_topic_switching():
    print("--- Test 3: BookingToolManager Topic Switching & Non-Interference ---")
    mgr = BookingToolManager(webhook_url="")

    # 1. Non-booking question should return None, None, None
    reply, directive, event = await mgr.evaluate_turn("How can I stop what we're thinking?")
    print(f"Non-booking turn: reply={reply}")
    assert reply is None, "Should not produce direct reply for non-booking query"
    assert mgr.state == "idle"

    # 2. Explicit booking request offers slots
    reply, directive, event = await mgr.evaluate_turn("I want to book an appointment for tomorrow")
    print(f"Booking turn: reply={reply}, state={mgr.state}")
    assert mgr.state == "slots_offered"
    assert reply is not None

    # 3. Caller changes topic instead of picking a slot
    reply, directive, event = await mgr.evaluate_turn("Actually, how can I stop my overthinking?")
    print(f"Topic change turn: reply={reply}, state={mgr.state}")
    assert reply is None, "Should yield back to LLM when caller changes topic"
    assert mgr.state == "idle", "State should reset to idle when caller changes topic"

    # 4. Caller says cancel
    mgr.state = "slots_offered"
    reply, directive, event = await mgr.evaluate_turn("No, cancel that")
    print(f"Cancel turn: state={mgr.state}")
    assert mgr.state == "idle"
    print("Booking manager topic switching test PASSED!\n")


def test_speculative_candidate_filtering():
    print("--- Test 4: Speculative Candidate Filtering ---")
    llm = LlmService(LlmSettings())
    spec = SpeculativeResponseManager(llm_service=llm, branch_count=2)

    # Garbage / too-short partials should yield no candidates
    short_partials = [
        "Oh, okay, name.",
        "Oh",
        "Hello",
        "Um yeah",
    ]
    for p in short_partials:
        cands = spec.generate_candidate_completions(p)
        print(f"Partial '{p}' -> candidates={cands}")
        assert len(cands) == 0, f"Expected 0 candidates for '{p}', got {cands}"

    # Real partial should yield candidate
    real_partial = "How can I improve my sleep"
    cands = spec.generate_candidate_completions(real_partial)
    print(f"Partial '{real_partial}' -> candidates={cands}")
    assert len(cands) >= 1
    print("Speculative candidate filtering test PASSED!\n")


async def main():
    test_booking_intent_regex()
    test_name_extraction()
    await test_booking_manager_topic_switching()
    test_speculative_candidate_filtering()
    print("==================================================")
    print("ALL FIX VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(main())
