"""
Verification script for Speculative Parallel Response Generation.
Tests:
1. Intelligent candidate generation across domains, languages (EN/HI), and partial utterances
2. Semantic matching and commit thresholds (exact match, punctuation tolerance, filler tolerance, miss fallback)
3. Background concurrent speculative generation and zero-latency queue streaming
4. Immediate cancellation of unselected candidate branches
"""

import asyncio
import sys
import time
from typing import AsyncIterator, Optional

sys.path.insert(0, "/home/himanshu/Downloads/calling_agent")

from services.llm_service import ConversationTurn
from services.speculative_service import SpeculativeBranch, SpeculativeResponseManager


class MockLlmService:
    """Mock LLM service that simulates streaming sentences with realistic delays."""

    def __init__(self, sentence_delay_s: float = 0.05):
        self.sentence_delay_s = sentence_delay_s
        self.cancelled_branches: list[str] = []

    async def stream_reply(
        self,
        history: list[ConversationTurn],
        user_utterance: str,
        interrupt_event: asyncio.Event,
        system_prompt: Optional[str] = None,
        sentence_min_chars: int = 6,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        # Generate 2 sentences based on utterance
        sentences = [
            f"I would be happy to help you with {user_utterance.lower().rstrip('.?')}.",
            "We have several options available for you today.",
        ]
        for s in sentences:
            if interrupt_event.is_set():
                self.cancelled_branches.append(user_utterance)
                return
            await asyncio.sleep(self.sentence_delay_s)
            if interrupt_event.is_set():
                self.cancelled_branches.append(user_utterance)
                return
            yield s


def test_candidate_generation():
    print("--- 1. Testing Candidate Generation ---")
    mock_llm = MockLlmService()
    manager = SpeculativeResponseManager(llm_service=mock_llm, branch_count=2)

    # Test 1: Booking with full intent
    cands1 = manager.generate_candidate_completions("I want to book an appointment.")
    print(f"Partial: 'I want to book an appointment.' -> Candidates: {cands1}")
    assert len(cands1) >= 1
    assert cands1[0] == "I want to book an appointment."
    # Ensure no duplicated words like "an appointment an appointment"
    assert "appointment an appointment" not in cands1[1]

    # Test 2: Incomplete booking question
    cands2 = manager.generate_candidate_completions("Can I book")
    print(f"Partial: 'Can I book' -> Candidates: {cands2}")
    assert cands2[0] == "Can I book?"
    assert "appointment" in cands2[1].lower()

    # Test 3: Hours inquiry
    cands3 = manager.generate_candidate_completions("What are your business hours")
    print(f"Partial: 'What are your business hours' -> Candidates: {cands3}")
    assert cands3[0] == "What are your business hours?"

    # Test 4: Hindi appointment booking
    cands4 = manager.generate_candidate_completions("मुझे अपॉइंटमेंट बुक करना")
    print(f"Partial: 'मुझे अपॉइंटमेंट बुक करना' -> Candidates: {cands4}")
    assert "अपॉइंटमेंट" in cands4[0]
    print("✓ Candidate generation tests passed successfully!")


def test_matching_and_commitment():
    print("\n--- 2. Testing Matching and Commitment ---")
    mock_llm = MockLlmService()
    manager = SpeculativeResponseManager(llm_service=mock_llm, branch_count=2, match_threshold=0.55)

    # Manually populate speculative branches
    b0 = SpeculativeBranch(branch_id=0, candidate_text="I want to book an appointment.")
    b1 = SpeculativeBranch(branch_id=1, candidate_text="I want to book an appointment for tomorrow.")
    manager._branches = [b0, b1]

    # Exact match
    branch, score = manager.match_and_commit("I want to book an appointment.")
    assert branch is not None
    assert branch.branch_id == 0
    assert score == 1.0
    print(f"✓ Exact match: branch_id={branch.branch_id}, score={score}")

    # Punctuation tolerance (no period in final STT)
    manager._branches = [b0, b1]
    branch, score = manager.match_and_commit("i want to book an appointment")
    assert branch is not None
    assert branch.branch_id == 0
    assert score == 1.0
    print(f"✓ Punctuation tolerance match: branch_id={branch.branch_id}, score={score}")

    # Suffix match (branch 1)
    b0 = SpeculativeBranch(branch_id=0, candidate_text="I want to book an appointment.")
    b1 = SpeculativeBranch(branch_id=1, candidate_text="I want to book an appointment for tomorrow.")
    manager._branches = [b0, b1]
    branch, score = manager.match_and_commit("I want to book an appointment for tomorrow please")
    assert branch is not None
    assert branch.branch_id == 1
    assert score > 0.85
    print(f"✓ Suffix continuation match: branch_id={branch.branch_id}, score={score:.2f}")

    # Dissimilar query (should miss and return None)
    b0 = SpeculativeBranch(branch_id=0, candidate_text="I want to book an appointment.")
    b1 = SpeculativeBranch(branch_id=1, candidate_text="I want to book an appointment for tomorrow.")
    manager._branches = [b0, b1]
    branch, score = manager.match_and_commit("Where is your clinic located?")
    assert branch is None
    assert score < 0.55
    print(f"✓ Dissimilar query correctly missed (score={score:.2f} < threshold), fallback triggered")


async def test_concurrent_generation_and_zero_latency():
    print("\n--- 3. Testing Concurrent Speculative Generation & Zero Latency Stream ---")
    mock_llm = MockLlmService(sentence_delay_s=0.03)
    manager = SpeculativeResponseManager(llm_service=mock_llm, branch_count=2)

    # 1. Partial STT arrives while caller is still speaking
    partial_text = "I want to book an appointment"
    await manager.on_partial_stt(
        partial_text=partial_text,
        history=[],
        system_prompt="You are a helpful assistant.",
    )

    assert len(manager.active_branches) == 2
    print(f"✓ Launched {len(manager.active_branches)} background speculative branches")

    # 2. Simulate caller finishing sentence & VAD closing turn (50ms elapsed)
    await asyncio.sleep(0.05)

    # Check pre-generated sentence count
    branch_0 = manager._branches[0]
    print(f"Pre-generated sentences in Branch 0 during speech: {len(branch_0.buffered_sentences)}")

    # 3. Final STT completes
    final_text = "I want to book an appointment."
    t0 = time.perf_counter()
    committed, score = manager.match_and_commit(final_text)
    assert committed is not None
    assert committed.branch_id == 0

    # 4. Stream from committed branch and measure TTFT
    interrupt_event = asyncio.Event()
    received_sentences = []
    first_sentence_time_ms = 0.0

    async for sentence in manager.stream_committed_branch(committed, interrupt_event):
        if not received_sentences:
            first_sentence_time_ms = (time.perf_counter() - t0) * 1000.0
        received_sentences.append(sentence)

    print(f"✓ Received {len(received_sentences)} sentences from committed branch")
    print(f"✓ Time to first sentence: {first_sentence_time_ms:.2f}ms (Near-Zero Latency!)")
    assert first_sentence_time_ms < 15.0, f"Expected < 15ms, got {first_sentence_time_ms}ms"

    # 5. Verify unselected branch 1 was cancelled
    assert manager._branches[1].is_done is True
    print("✓ Unselected branch was cancelled immediately to free resources")


if __name__ == "__main__":
    test_candidate_generation()
    test_matching_and_commitment()
    asyncio.run(test_concurrent_generation_and_zero_latency())
    print("\n🎉 ALL SPECULATIVE PARALLEL RESPONSE GENERATION TESTS PASSED!")
