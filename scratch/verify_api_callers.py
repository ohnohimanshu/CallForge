import sys
from pathlib import Path
import tempfile

sys.path.insert(0, "/home/himanshu/Downloads/calling_agent")

from starlette.testclient import TestClient
from api import create_api
from callforge.store.db import PlatformStore
from config import load_settings

def test_callers_api():
    print("--- Testing /api/callers API Endpoints ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        upload_root = Path(tmpdir) / "uploads"
        upload_root.mkdir()

        settings = load_settings()
        store = PlatformStore(db_path)
        app = create_api(settings, store, None, upload_root)
        client = TestClient(app)

        test_phone = "+15557778899"

        # Seed a caller
        store.upsert_caller_profile(
            phone_number=test_phone,
            name="Diana Prince",
            summary="Diana asked about membership pricing and hours.",
            disposition="Information Provided",
            sentiment="positive",
        )

        # 1. GET /api/callers
        res = client.get("/api/callers")
        assert res.status_code == 200, f"Status {res.status_code}: {res.text}"
        callers = res.json()
        assert isinstance(callers, list)
        matching = [c for c in callers if c["phone_number"] == test_phone]
        assert len(matching) == 1
        assert matching[0]["name"] == "Diana Prince"
        assert "relative_time" in matching[0]
        assert "topic" in matching[0]
        print(f"✓ GET /api/callers returned {len(callers)} caller(s), found Diana Prince")

        # 2. GET /api/callers/{phone}
        res_single = client.get(f"/api/callers/{test_phone}")
        assert res_single.status_code == 200
        single = res_single.json()
        assert single["name"] == "Diana Prince"
        assert single["last_sentiment"] == "positive"
        print(f"✓ GET /api/callers/{test_phone} returned Diana Prince successfully")

        # 3. DELETE /api/callers/{phone}
        res_del = client.delete(f"/api/callers/{test_phone}")
        assert res_del.status_code == 200
        assert res_del.json()["ok"] is True
        print(f"✓ DELETE /api/callers/{test_phone} succeeded")

        # Verify 404 after delete
        res_404 = client.get(f"/api/callers/{test_phone}")
        assert res_404.status_code == 404
        print(f"✓ GET /api/callers/{test_phone} correctly returned 404 after deletion")

        print("\n🎉 ALL CALLERS API ENDPOINT TESTS PASSED!")

if __name__ == "__main__":
    test_callers_api()
