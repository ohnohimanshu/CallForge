from __future__ import annotations

import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CreateCampaignRequest(BaseModel):
    name: str
    agent_id: str
    concurrency_limit: int = 1
    caller_id: str = "Outbound AI"
    greeting_text: str = ""
    collect_fields: str = ""
    contacts: Optional[list[dict]] = None


class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = None
    agent_id: Optional[str] = None
    concurrency_limit: Optional[int] = None
    caller_id: Optional[str] = None
    greeting_text: Optional[str] = None
    collect_fields: Optional[str] = None


from api.routes.auth import get_current_username

class AddContactsRequest(BaseModel):
    contacts: list[dict]


@router.get("")
async def list_campaigns(request: Request):
    store = request.app.state.store
    username = get_current_username(request)
    agents = {a.id: a.name for a in store.list_agents(owner_username=username)}
    campaigns = store.list_campaigns()
    if username and username != "himanshu":
        campaigns = [c for c in campaigns if c.agent_id in agents]
    results = []
    for c in campaigns:
        d = c.to_dict()
        d["agent_name"] = agents.get(c.agent_id, "Unknown")
        d["stats"] = store.get_campaign_stats(c.id)
        results.append(d)
    return results


@router.post("")
async def create_campaign(req: CreateCampaignRequest, request: Request):
    store = request.app.state.store
    agent = store.get_agent(req.agent_id)
    if not agent:
        raise HTTPException(400, "Selected agent does not exist")

    campaign = store.create_campaign(
        name=req.name,
        agent_id=req.agent_id,
        concurrency_limit=req.concurrency_limit,
        caller_id=req.caller_id,
        greeting_text=req.greeting_text,
        collect_fields=req.collect_fields,
    )
    if req.contacts:
        store.add_campaign_contacts(campaign.id, req.contacts)
        campaign = store.get_campaign(campaign.id)

    assert campaign is not None
    d = campaign.to_dict()
    d["agent_name"] = agent.name
    d["stats"] = store.get_campaign_stats(campaign.id)
    return d


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str, request: Request):
    store = request.app.state.store
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    agent = store.get_agent(campaign.agent_id)
    username = get_current_username(request)
    if username and agent and agent.owner_username and agent.owner_username != username and username != "himanshu":
        raise HTTPException(403, "Access denied: you do not own this campaign")
    d = campaign.to_dict()
    d["agent_name"] = agent.name if agent else "Unknown"
    d["agent_extension"] = agent.extension if agent else ""
    d["stats"] = store.get_campaign_stats(campaign.id)
    return d


@router.patch("/{campaign_id}")
async def update_campaign(campaign_id: str, req: UpdateCampaignRequest, request: Request):
    store = request.app.state.store
    updated = store.update_campaign(campaign_id, **req.dict(exclude_unset=True))
    if not updated:
        raise HTTPException(404, "Campaign not found")
    agent = store.get_agent(updated.agent_id)
    d = updated.to_dict()
    d["agent_name"] = agent.name if agent else "Unknown"
    d["stats"] = store.get_campaign_stats(campaign_id)
    return d


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str, request: Request):
    store = request.app.state.store
    # Pause if running
    engine = getattr(request.app.state, "campaign_engine", None)
    if engine:
        await engine.pause_campaign(campaign_id)
    ok = store.delete_campaign(campaign_id)
    if not ok:
        raise HTTPException(404, "Campaign not found")
    return {"ok": True}


@router.post("/{campaign_id}/contacts")
async def add_contacts(campaign_id: str, req: AddContactsRequest, request: Request):
    store = request.app.state.store
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    count = store.add_campaign_contacts(campaign_id, req.contacts)
    return {"added": count, "stats": store.get_campaign_stats(campaign_id)}


@router.post("/{campaign_id}/contacts/csv")
async def upload_contacts_csv(campaign_id: str, file: UploadFile = File(...), request: Request = None):
    store = request.app.state.store
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    content = await file.read()
    try:
        decoded = content.decode("utf-8-sig")
    except Exception:
        decoded = content.decode("latin-1", errors="replace")

    reader = csv.reader(io.StringIO(decoded))
    rows = list(reader)
    if not rows:
        raise HTTPException(400, "Empty CSV file")

    contacts = []
    # Inspect header
    first_row = [c.strip().lower() for c in rows[0]]
    phone_idx = -1
    name_idx = -1

    for i, col in enumerate(first_row):
        if col in ("phone", "phone_number", "number", "mobile", "tel"):
            phone_idx = i
        elif col in ("name", "full_name", "contact", "caller"):
            name_idx = i

    start_idx = 0
    if phone_idx != -1:
        # Header detected
        start_idx = 1
    else:
        # No header: assume col 0 is phone, col 1 is name
        phone_idx = 0
        name_idx = 1 if len(rows[0]) > 1 else -1

    for row in rows[start_idx:]:
        if not row or len(row) <= phone_idx:
            continue
        phone = row[phone_idx].strip()
        if not phone:
            continue
        name = row[name_idx].strip() if name_idx != -1 and len(row) > name_idx else ""
        contacts.append({"phone": phone, "name": name})

    count = store.add_campaign_contacts(campaign_id, contacts)
    return {"added": count, "stats": store.get_campaign_stats(campaign_id)}


@router.get("/{campaign_id}/contacts")
async def list_contacts(
    campaign_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None),
):
    store = request.app.state.store
    contacts = store.list_campaign_contacts(campaign_id, limit=limit, offset=offset, status=status)
    return [c.to_dict() for c in contacts]


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str, request: Request):
    engine = getattr(request.app.state, "campaign_engine", None)
    if not engine:
        raise HTTPException(503, "Campaign engine not initialized")
    camp = await engine.start_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    store = request.app.state.store
    return {
        "status": camp.status,
        "stats": store.get_campaign_stats(campaign_id),
    }


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, request: Request):
    engine = getattr(request.app.state, "campaign_engine", None)
    if not engine:
        raise HTTPException(503, "Campaign engine not initialized")
    camp = await engine.pause_campaign(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    store = request.app.state.store
    return {
        "status": camp.status,
        "stats": store.get_campaign_stats(campaign_id),
    }


@router.post("/{campaign_id}/reset")
async def reset_campaign(campaign_id: str, request: Request):
    store = request.app.state.store
    store.reset_campaign_contacts(campaign_id)
    return {"ok": True, "stats": store.get_campaign_stats(campaign_id)}


@router.get("/{campaign_id}/export")
async def export_campaign_csv(campaign_id: str, request: Request):
    store = request.app.state.store
    campaign = store.get_campaign(campaign_id)
    contacts = store.list_campaign_contacts(campaign_id, limit=5000)
    
    # Determine custom collected fields
    extra_fields = []
    if campaign and campaign.collect_fields:
        extra_fields = [f.strip() for f in campaign.collect_fields.split(",") if f.strip()]

    output = io.StringIO()
    writer = csv.writer(output)
    header = ["Name", "Phone", "Status", "Disposition", "Duration (s)", "Attempts", "Last Attempt"] + extra_fields
    writer.writerow(header)
    for c in contacts:
        collected = {}
        if getattr(c, "collected_data_json", None):
            try:
                collected = json.loads(c.collected_data_json)
            except Exception:
                collected = {}
        extra_vals = [collected.get(f, "") for f in extra_fields]
        writer.writerow([
            c.name, c.phone, c.status, c.disposition, round(c.duration_s, 1), c.attempts, c.last_attempt_at
        ] + extra_vals)
    
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="campaign_{campaign_id[:8]}_results.csv"'},
    )
