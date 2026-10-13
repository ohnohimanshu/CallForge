import asyncio
from config import load_settings
from services.llm_service import LlmService, _SENTENCE_BOUNDARY
import re
import time
import services.llm_service
services.llm_service._SENTENCE_BOUNDARY = re.compile(r"(?<=[.,!?])\s+")

async def main():
    settings = load_settings()
    llm = LlmService(settings.llm)
    
    interrupt = asyncio.Event()
    
    print(f"[{time.time()}] Start generation...")
    start = time.time()
    
    try:
        async for sentence in llm.stream_reply(
            history=[],
            user_utterance="Tell me a long story about a king.",
            interrupt_event=interrupt,
            sentence_min_chars=6
        ):
            print(f"[{time.time() - start:.2f}s] Yielded: {sentence}")
    finally:
        await llm.aclose()

asyncio.run(main())
