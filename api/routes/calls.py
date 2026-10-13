from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from api.routes.auth import get_current_username

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("")
async def list_calls(
    request: Request,
    agent_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    username = get_current_username(request)
    store = request.app.state.store
    calls = store.list_calls(agent_id=agent_id, limit=limit, owner_username=username)
    # Enrich with agent name for the UI (scoped to user's agents)
    agents = {a.id: a.name for a in store.list_agents(owner_username=username)}
    result = []
    for c in calls:
        d = c.to_dict()
        d["agent_name"] = agents.get(c.agent_id, "unknown")
        result.append(d)
    return result


@router.get("/{call_id}")
async def get_call(call_id: str, request: Request):
    store = request.app.state.store
    call = store.get_call(call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    agent = store.get_agent(call.agent_id)
    username = get_current_username(request)
    if username and agent and agent.owner_username and agent.owner_username != username and username != "himanshu":
        raise HTTPException(403, "Access denied: you do not own the agent for this call")
    return {
        **call.to_dict(),
        "agent_name": agent.name if agent else "unknown",
        "turns": [t.to_dict() for t in store.list_turns(call_id)],
    }


@router.api_route("/{call_id}/audio", methods=["GET", "HEAD"])
async def get_call_audio(call_id: str, request: Request):
    from pathlib import Path
    from fastapi.responses import FileResponse

    store = request.app.state.store
    call = store.get_call(call_id)
    if not call:
        raise HTTPException(404, "Call not found")

    agent = store.get_agent(call.agent_id)
    username = get_current_username(request)
    if username and agent and agent.owner_username and agent.owner_username != username and username != "himanshu":
        raise HTTPException(403, "Access denied: you do not own the agent for this call")

    rec_dir = Path("platform_data/recordings")
    candidates = [
        rec_dir / f"{call_id}.wav",
        rec_dir / f"{call.call_uuid}.wav",
        rec_dir / f"call_{call_id}.wav",
        rec_dir / f"call_{call.call_uuid}.wav",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return FileResponse(
                str(p),
                media_type="audio/wav",
                headers={"Accept-Ranges": "bytes", "Content-Disposition": f'inline; filename="{call_id}.wav"'},
            )

    # Glob fallback if filename contains the uuid or id
    if rec_dir.exists():
        for matched in rec_dir.glob(f"*{call_id}*.wav"):
            if matched.is_file():
                return FileResponse(
                    str(matched),
                    media_type="audio/wav",
                    headers={"Accept-Ranges": "bytes", "Content-Disposition": f'inline; filename="{call_id}.wav"'},
                )
        for matched in rec_dir.glob(f"*{call.call_uuid}*.wav"):
            if matched.is_file():
                return FileResponse(
                    str(matched),
                    media_type="audio/wav",
                    headers={"Accept-Ranges": "bytes", "Content-Disposition": f'inline; filename="{call_id}.wav"'},
                )

    raise HTTPException(404, "Recording not available for this call")
