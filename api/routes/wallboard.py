from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Request

from api.routes.auth import get_current_username

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wallboard", tags=["wallboard"])


@router.get("/status")
async def get_wallboard_status(request: Request):
    """Return real-time wallboard statistics including active calls, capacity, and SIP trunk."""
    runtime = request.app.state.runtime
    if not runtime:
        raise HTTPException(503, "Agent runtime not initialized")
    data = runtime.get_wallboard_data()
    username = get_current_username(request)
    if username and username != "himanshu":
        store = request.app.state.store
        user_agent_ids = {a.id for a in store.list_agents(owner_username=username)}
        data["lines"] = [l for l in data.get("lines", []) if l.get("agent_id") in user_agent_ids]
        data["active_calls"] = [c for c in data.get("active_calls", []) if c.get("agent_id") in user_agent_ids]
        user_active = len(data["active_calls"])
        data["system"]["total_active_calls"] = user_active
        data["system"]["channel_occupancy_pct"] = round(
            (user_active / max(1, data["system"]["concurrent_capacity"])) * 100, 1
        )
    return data


@router.get("/live-calls")
async def get_live_calls(request: Request):
    """List all currently connected AudioSocket callers."""
    runtime = request.app.state.runtime
    if not runtime:
        return []
    calls = runtime.get_live_calls()
    username = get_current_username(request)
    if username and username != "himanshu":
        store = request.app.state.store
        user_agent_ids = {a.id for a in store.list_agents(owner_username=username)}
        calls = [c for c in calls if c.get("agent_id") in user_agent_ids]
    return calls


@router.post("/calls/{call_uuid}/hangup")
async def hangup_call(call_uuid: str, request: Request):
    """Remotely disconnect an active call session from the wallboard."""
    runtime = request.app.state.runtime
    if not runtime:
        raise HTTPException(503, "Agent runtime not initialized")
    
    success = runtime.hangup_call(call_uuid)
    if not success:
        raise HTTPException(404, f"Active call session {call_uuid} not found or already terminated")
    
    return {"ok": True, "message": f"Call {call_uuid} terminated by operator"}
