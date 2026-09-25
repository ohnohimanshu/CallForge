from pathlib import Path
from starlette.testclient import TestClient
from config import Settings
from callforge.store.db import PlatformStore
from callforge.runtime.agent_runtime import AgentRuntime
from api import create_api

def test_voice_samples():
    settings = Settings()
    store = PlatformStore("platform_data/callforge.db")
    upload_root = Path("platform_data/uploads")
    dialplan_path = Path("platform_data/agents.conf")
    runtime = AgentRuntime(settings, store, dialplan_path, settings.llm.base_url)
    app = create_api(settings, store, runtime, upload_root)
    client = TestClient(app)

    # 1. Test English voice sample
    res_en = client.get("/api/voice-sample?voice=en_US-lessac-medium")
    assert res_en.status_code == 200
    assert res_en.headers["content-type"] == "audio/wav"
    assert len(res_en.content) > 1000
    print("✓ English voice sample generated:", len(res_en.content), "bytes")

    # 2. Test Hindi voice sample
    res_hi = client.get("/api/voice-sample?voice=hi_IN-priyamvada-medium")
    assert res_hi.status_code == 200
    assert res_hi.headers["content-type"] == "audio/wav"
    assert len(res_hi.content) > 1000
    print("✓ Hindi voice sample generated:", len(res_hi.content), "bytes")

    # 3. Test caching
    res_cache = client.get("/api/voice-sample?voice=en_US-lessac-medium")
    assert res_cache.status_code == 200
    assert res_cache.content == res_en.content
    print("✓ Voice sample caching verified")

if __name__ == "__main__":
    test_voice_samples()
