"""Verification test for P5 Outbound Calling Campaigns API, Store, and Campaign Engine."""

import io
import time
from pathlib import Path
from starlette.testclient import TestClient

from config import Settings
from callforge.store.db import PlatformStore
from callforge.runtime.agent_runtime import AgentRuntime
from callforge.runtime.campaign_engine import CampaignEngine
from api import create_api

def test_campaigns():
    db_path = "platform_data/callforge.db"
    store = PlatformStore(db_path)
    settings = Settings()

    print("1. Verifying Campaign Database Store operations...")
    agents = store.list_agents()
    if not agents:
        agent = store.create_agent(
            name="Test Outbound Agent",
            prompt="You are an outbound sales representative calling customers.",
            first_sentence="Hello, this is CallForge calling regarding your inquiry.",
            voice_id="en_US-lessac-medium",
            extension=1099,
        )
    else:
        agent = agents[0]

    # Create campaign
    camp = store.create_campaign(
        name="Q3 Outbound Outreach Test",
        agent_id=agent.id,
        concurrency_limit=2,
        caller_id="+15550009999",
    )
    assert camp is not None
    assert camp.name == "Q3 Outbound Outreach Test"
    assert camp.status == "draft"
    print(f"Created campaign: {camp.id} ({camp.name})")

    # Add contacts
    test_contacts = [
        {"phone": "+15551234001", "name": "Alice Johnson", "custom_fields": {"company": "Acme Inc"}},
        {"phone": "+15551234002", "name": "Bob Smith", "custom_fields": {"priority": "High"}},
        {"phone": "+15551234003", "name": "Charlie Brown", "custom_fields": {}},
    ]
    added = store.add_campaign_contacts(camp.id, test_contacts)
    assert added == 3
    print(f"Added {added} contacts to campaign.")

    # List contacts
    contacts = store.list_campaign_contacts(camp.id)
    assert len(contacts) == 3
    assert contacts[0].status == "pending"

    # Verify stats
    stats = store.get_campaign_stats(camp.id)
    assert stats["total"] == 3
    assert stats["pending"] == 3
    assert stats["completed"] == 0
    print(f"Initial campaign stats: {stats}")

    print("\n2. Testing CampaignEngine Call File generation...")
    engine = CampaignEngine(store=store)
    call_file_path = engine.generate_call_file(contacts[0], agent, caller_id=camp.caller_id)
    call_file_content = call_file_path.read_text(encoding="utf-8")
    print("Generated Asterisk .call file:\n---\n" + call_file_content + "\n---")
    assert f"Channel: PJSIP/{contacts[0].phone}" in call_file_content
    assert f"Extension: {agent.extension}" in call_file_content
    assert f"Set: CONTACT_ID={contacts[0].id}" in call_file_content
    assert f"Set: CAMPAIGN_ID={camp.id}" in call_file_content

    print("\n3. Testing Campaign API Endpoints via FastAPI TestClient...")
    dialplan_path = Path("platform_data/extensions_test.conf")
    runtime = AgentRuntime(
        settings=settings,
        store=store,
        dialplan_path=dialplan_path,
        ollama_base_url="http://localhost:11434",
    )
    app = create_api(settings=settings, store=store, runtime=runtime, upload_root=Path("platform_data/uploads"))
    client = TestClient(app)

    # GET /api/campaigns
    res = client.get("/api/campaigns")
    assert res.status_code == 200
    campaigns = res.json()
    assert any(c["id"] == camp.id for c in campaigns)
    print(f"GET /api/campaigns successfully returned {len(campaigns)} campaigns.")

    # GET /api/campaigns/{id}
    res = client.get(f"/api/campaigns/{camp.id}")
    assert res.status_code == 200
    camp_detail = res.json()
    assert camp_detail["id"] == camp.id
    assert camp_detail["stats"]["total"] == 3
    print(f"GET /api/campaigns/{camp.id} returned stats: {camp_detail['stats']}")

    # POST /api/campaigns/{id}/contacts/csv
    csv_data = "phone,name,company\n+15559990001,David Miller,TechCorp\n+15559990002,Emma Davis,Initech\n"
    files = {"file": ("contacts.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    res = client.post(f"/api/campaigns/{camp.id}/contacts/csv", files=files)
    assert res.status_code == 200, f"CSV upload failed: {res.text}"
    upload_res = res.json()
    assert upload_res["added"] == 2
    print(f"CSV upload successfully imported {upload_res['added']} contacts.")

    # Verify updated stats
    res = client.get(f"/api/campaigns/{camp.id}")
    assert res.json()["stats"]["total"] == 5

    # Start campaign
    print("\n4. Testing Start, Execution & State Transitions...")
    res = client.post(f"/api/campaigns/{camp.id}/start")
    assert res.status_code == 200
    assert res.json()["status"] == "running"
    print("Campaign started successfully.")

    # Wait briefly for simulation worker to process
    time.sleep(2.5)

    # Check status
    res = client.get(f"/api/campaigns/{camp.id}")
    cur_stats = res.json()["stats"]
    print(f"Pacing/simulation stats after 2.5s: {cur_stats}")
    assert cur_stats["dialing"] > 0 or cur_stats["completed"] > 0 or cur_stats["failed"] > 0

    # Pause campaign
    res = client.post(f"/api/campaigns/{camp.id}/pause")
    assert res.status_code == 200
    assert res.json()["status"] == "paused"
    print("Campaign paused successfully.")

    # Export CSV
    print("\n5. Testing Campaign Export CSV...")
    res = client.get(f"/api/campaigns/{camp.id}/export")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    csv_exported = res.text
    print(f"Exported CSV preview (first 3 lines):\n" + "\n".join(csv_exported.splitlines()[:3]))
    assert "Name,Phone,Status,Disposition" in csv_exported

    # Reset campaign
    print("\n6. Testing Campaign Reset...")
    res = client.post(f"/api/campaigns/{camp.id}/reset")
    assert res.status_code == 200
    res = client.get(f"/api/campaigns/{camp.id}")
    reset_stats = res.json()["stats"]
    print(f"Stats after reset: {reset_stats}")
    assert reset_stats["pending"] == 5
    assert reset_stats["completed"] == 0

    print("\nALL CAMPAIGN INTEGRATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_campaigns()
