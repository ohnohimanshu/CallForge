"""Telephony API — FreePBX Method 1 (Direct AudioSocket) + optional legacy phones."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from api.routes.auth import get_current_username
from callforge.runtime.call_session_registry import SESSION_REGISTRY
from callforge.runtime.freepbx_dialplan import (
    render_freepbx_bundle,
    setup_instructions,
    write_freepbx_dialplan,
)
from callforge.runtime.telephony_server import (
    get_network_ips,
    get_phones_with_presence,
    get_telephony_server_info,
    originate_intercom_call,
    sync_telephony_server,
)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["telephony"])


def _paths(request: Request) -> tuple[Path, Path]:
    root = Path(__file__).resolve().parent.parent.parent
    pjsip = getattr(
        request.app.state,
        "phones_pjsip_path",
        root / "asterisk-server" / "pjsip_phones.conf",
    )
    dialplan = getattr(
        request.app.state,
        "phones_dialplan_path",
        root / "asterisk-server" / "extensions_phones.conf",
    )
    return pjsip, dialplan


def _public_host(request: Request) -> str:
    import os

    explicit = (
        os.getenv("FREEPBX_AUDIOSOCKET_HOST")
        or os.getenv("AUDIOSOCKET_HOST")
        or ""
    ).strip()
    if explicit and explicit not in ("voice-agent", "0.0.0.0", "localhost"):
        return explicit
    ips = get_network_ips()
    return ips[0] if ips else "127.0.0.1"


def _api_base(request: Request, host: str) -> str:
    import os

    explicit = (os.getenv("FREEPBX_API_BASE") or os.getenv("CALLFORGE_PUBLIC_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    # Prefer Host header when FreePBX CURL hits us
    forwarded = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if forwarded and "localhost" not in forwarded and "127.0.0.1" not in forwarded:
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        return f"{scheme}://{forwarded}".rstrip("/")
    return f"http://{host}:8080"


# ---------------------------------------------------------------------------
# FreePBX Method 1 — primary integration
# ---------------------------------------------------------------------------


class SessionRegisterRequest(BaseModel):
    call_uuid: str = Field(..., description="UUID FreePBX will pass to AudioSocket()")
    caller_id: str = Field("unknown", description="CALLERID(num) from FreePBX")
    agent_id: str = Field("", description="Optional CallForge agent id")


@router.get("/telephony/freepbx")
async def freepbx_integration_status(request: Request) -> dict[str, Any]:
    """FreePBX Method 1 status, ports, and copy-paste dialplan for all agents."""
    store = request.app.state.store
    runtime = request.app.state.runtime
    host = _public_host(request)
    api_base = _api_base(request, host)
    live = {row["agent_id"]: row for row in runtime.live_status()}
    agents = [a for a in store.list_agents() if a.status == "deployed" and a.port]
    agent_guides = [setup_instructions(a, host=host, api_base=api_base) for a in agents]
    dialplan = render_freepbx_bundle(agents, host=host, api_base=api_base)

    freepbx_path = Path("platform_data/freepbx/extensions_custom_callforge.conf")
    try:
        write_freepbx_dialplan(agents, freepbx_path, host=host, api_base=api_base)
    except Exception as exc:
        logger.debug("Could not refresh FreePBX dialplan file: %s", exc)

    return {
        "method": "1_direct_audiosocket",
        "recommended": True,
        "status": "ready" if live else "waiting_for_agents",
        "message": (
            "FreePBX should connect directly to CallForge AudioSocket. "
            "Do not use a SIP trunk between FreePBX and CallForge."
        ),
        "audiosocket_host": host,
        "api_base": api_base,
        "ports": {
            "api": 8080,
            "audiosocket_range": "9092-9101",
            "sip_not_required": True,
        },
        "firewall": [
            f"Allow FreePBX → {host}:8080/tcp (session + handoff API)",
            f"Allow FreePBX → {host}:9092-9101/tcp (AudioSocket PCM)",
        ],
        "live_lines": list(live.values()),
        "agents": agent_guides,
        "dialplan_file": str(freepbx_path),
        "dialplan": dialplan,
        "comparison": {
            "latency_ms": {"audiosocket": "<5", "sip_trunk": "50-120"},
            "barge_in": {"audiosocket": "instant", "sip_trunk": "0.5-1.5s buffered"},
            "architecture": {
                "audiosocket": "FreePBX → CallForge (single hop)",
                "sip_trunk": "FreePBX → SIP → CallForge Asterisk → AI (double hop)",
            },
            "firewall": {
                "audiosocket": "1 TCP port per agent",
                "sip_trunk": "5060 UDP + RTP range 10000-20000",
            },
        },
        "steps": [
            "Deploy one or more agents in CallForge (each opens an AudioSocket TCP port).",
            "Copy the dialplan below into FreePBX /etc/asterisk/extensions_custom.conf",
            "Apply Config in FreePBX (or: asterisk -rx \"dialplan reload\").",
            "Create a Custom Destination → callforge-agent-<ext>,s,1",
            "Point Inbound Routes / IVR options at that Custom Destination.",
            "Test a call — FreePBX streams raw 8kHz PCM straight into CallForge.",
        ],
    }


@router.get("/telephony/freepbx/dialplan", response_class=PlainTextResponse)
async def freepbx_dialplan_text(request: Request) -> str:
    """Plain-text FreePBX extensions_custom.conf fragment."""
    store = request.app.state.store
    host = _public_host(request)
    api_base = _api_base(request, host)
    agents = [a for a in store.list_agents() if a.status == "deployed" and a.port]
    return render_freepbx_bundle(agents, host=host, api_base=api_base)


@router.get("/telephony/freepbx/agents/{agent_id}")
async def freepbx_agent_guide(request: Request, agent_id: str) -> dict[str, Any]:
    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.status != "deployed" or not agent.port:
        raise HTTPException(400, "Agent must be deployed before FreePBX can connect")
    host = _public_host(request)
    api_base = _api_base(request, host)
    return setup_instructions(agent, host=host, api_base=api_base)


@router.get("/telephony/session")
async def register_call_session_get(
    call_uuid: str = Query(..., description="UUID FreePBX will pass to AudioSocket()"),
    caller_id: str = Query("unknown"),
    agent_id: str = Query(""),
) -> dict[str, Any]:
    """Register caller ID before AudioSocket — FreePBX ${CURL(...)} uses GET."""
    meta = SESSION_REGISTRY.register(call_uuid.strip(), caller_id=caller_id or "unknown", agent_id=agent_id or "")
    return {"ok": True, "call_uuid": meta.call_uuid, "caller_id": meta.caller_id, "agent_id": meta.agent_id}


@router.post("/telephony/session")
async def register_call_session_post(body: SessionRegisterRequest) -> dict[str, Any]:
    """Register caller ID before AudioSocket (JSON POST)."""
    meta = SESSION_REGISTRY.register(
        body.call_uuid.strip(),
        caller_id=body.caller_id or "unknown",
        agent_id=body.agent_id or "",
    )
    return {"ok": True, "call_uuid": meta.call_uuid, "caller_id": meta.caller_id, "agent_id": meta.agent_id}


@router.get("/telephony/handoff/{call_uuid}", response_class=PlainTextResponse)
async def get_handoff_target(call_uuid: str) -> str:
    """FreePBX dialplan polls this after AudioSocket() returns.

    Returns plain extension text (or empty) so Asterisk CURL can Set(TARGET=...).
    """
    return SESSION_REGISTRY.pop_handoff(call_uuid)


@router.get("/telephony/server")
async def get_server_status(request: Request) -> dict[str, Any]:
    """Telephony overview — FreePBX Method 1 first, legacy phone PBX second."""
    store = request.app.state.store
    runtime = request.app.state.runtime
    host = _public_host(request)
    api_base = _api_base(request, host)
    live = runtime.live_status()
    agents = [a for a in store.list_agents() if a.status == "deployed" and a.port]

    legacy = await get_telephony_server_info(store)
    return {
        "integration": "freepbx_audiosocket",
        "method": "1_direct_audiosocket",
        "recommended": True,
        "status": "online" if live else "waiting_for_agents",
        "audiosocket_host": host,
        "api_base": api_base,
        "audiosocket_ports": [row["port"] for row in live],
        "live_lines": live,
        "deployed_agents": len(agents),
        "sip_not_required": True,
        "message": "Connect FreePBX via Direct AudioSocket (Method 1). Phone/SIP PBX features below are optional/legacy.",
        "legacy_pbx": legacy,
        # Keep flat fields used by older UI code for gradual migration
        "sip_listening": False,
        "sip_port": 0,
        "sip_protocol": "N/A — FreePBX Method 1 uses AudioSocket TCP",
        "rtp_port_range": "N/A",
        "local_ip": host,
        "network_ips": get_network_ips(),
        "sip_domain": f"{host} (AudioSocket)",
        "total_phones": legacy.get("total_phones", 0),
        "online_phones": legacy.get("online_phones", 0),
        "in_call_phones": legacy.get("in_call_phones", 0),
        "special_extensions": {
            "ai_agent": agents[0].extension if agents else "2000",
            "custom_destination": (
                f"callforge-agent-{agents[0].extension},s,1" if agents else "callforge-agent-2000,s,1"
            ),
            "conference_bridge": "managed_by_freepbx",
            "intercom_broadcast": "managed_by_freepbx",
            "audio_echo_test": "managed_by_freepbx",
        },
        "supported_codecs": ["slin (8kHz PCM via AudioSocket)"],
        "compatible_clients": [
            {"name": "FreePBX 16/17 (Asterisk 18+)", "platforms": ["Linux"], "type": "PBX — Method 1 AudioSocket"},
            {"name": "Asterisk 16.14+ with res_audiosocket", "platforms": ["Linux"], "type": "PBX"},
        ],
    }


# ---------------------------------------------------------------------------
# Legacy optional phone management (local Asterisk profile only)
# ---------------------------------------------------------------------------


class PhoneCreateRequest(BaseModel):
    extension: str = Field(..., description="Extension number, e.g. 1005")
    name: str = Field(..., description="Display name, e.g. Himanshu Mobile")
    password: Optional[str] = Field(None, description="SIP password; auto-generated if omitted")
    device_type: str = Field("mobile", description="mobile | ip_phone | softphone | desk_phone")
    caller_id: Optional[str] = Field(None, description="Caller ID string, e.g. 'Himanshu' <1005>")
    notes: Optional[str] = Field("", description="Optional notes or location")


class PhoneUpdateRequest(BaseModel):
    extension: Optional[str] = None
    name: Optional[str] = None
    password: Optional[str] = None
    device_type: Optional[str] = None
    caller_id: Optional[str] = None
    notes: Optional[str] = None


class BulkCreateRequest(BaseModel):
    count: int = Field(10, ge=1, le=100, description="Number of phones to create (e.g. 10)")
    start_extension: int = Field(1001, ge=100, le=99999, description="Starting extension number")
    password_prefix: str = Field("phonepass", description="Password prefix")
    device_type: str = Field("ip_phone", description="Default device type: ip_phone | mobile")


class TestCallRequest(BaseModel):
    from_extension: str = Field(..., description="Source extension, e.g. 1001")
    to_extension: str = Field(..., description="Target extension, e.g. 1002 or 8888")


@router.get("/telephony/phones")
async def list_phones(request: Request) -> list[dict[str, Any]]:
    """List phone extensions scoped to current authenticated user."""
    store = request.app.state.store
    username = get_current_username(request)
    return await get_phones_with_presence(store, owner_username=username)


@router.post("/telephony/phones")
async def create_phone(request: Request, body: PhoneCreateRequest) -> dict[str, Any]:
    store = request.app.state.store
    clean_ext = body.extension.strip()
    username = get_current_username(request) or "himanshu"

    if not clean_ext.isdigit() and not clean_ext.isalnum():
        raise HTTPException(400, "Extension must contain numbers or alphanumeric characters")

    if store.get_phone_by_extension(clean_ext):
        raise HTTPException(409, f"Extension {clean_ext} already exists")

    for agent in store.list_agents():
        if agent.extension == clean_ext:
            raise HTTPException(409, f"Extension {clean_ext} is already assigned to AI Agent '{agent.name}'")

    password = body.password.strip() if body.password else secrets.token_hex(4) + "Pass!"
    phone = store.create_phone(
        extension=clean_ext,
        name=body.name.strip(),
        password=password,
        device_type=body.device_type,
        caller_id=body.caller_id or "",
        notes=body.notes or "",
        owner_username=username,
    )

    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)

    return {
        "ok": True,
        "phone": phone.to_dict(),
        "sync": sync_res,
        "message": (
            f"Extension {clean_ext} saved. Prefer FreePBX Method 1 for production — "
            "local phone PBX requires the optional legacy-asterisk Docker profile."
        ),
    }


@router.put("/telephony/phones/{phone_id}")
async def update_phone(request: Request, phone_id: str, body: PhoneUpdateRequest) -> dict[str, Any]:
    store = request.app.state.store
    existing = store.get_phone(phone_id)
    if not existing:
        raise HTTPException(404, "Phone extension not found")

    username = get_current_username(request)
    if username and existing.owner_username and existing.owner_username != username and username != "himanshu":
        raise HTTPException(403, "You do not have permission to modify this phone extension")

    if body.extension and body.extension.strip() != existing.extension:
        clean_ext = body.extension.strip()
        collision = store.get_phone_by_extension(clean_ext)
        if collision and collision.id != phone_id:
            raise HTTPException(409, f"Extension {clean_ext} is already in use")

    updated = store.update_phone(
        phone_id,
        extension=body.extension,
        name=body.name,
        password=body.password,
        device_type=body.device_type,
        caller_id=body.caller_id,
        notes=body.notes,
    )
    if not updated:
        raise HTTPException(500, "Failed to update phone record")

    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)

    return {
        "ok": True,
        "phone": updated.to_dict(),
        "sync": sync_res,
        "message": f"Extension {updated.extension} updated",
    }


@router.delete("/telephony/phones/{phone_id}")
async def delete_phone(request: Request, phone_id: str) -> dict[str, Any]:
    store = request.app.state.store
    existing = store.get_phone(phone_id)
    if not existing:
        raise HTTPException(404, "Phone extension not found")

    username = get_current_username(request)
    if username and existing.owner_username and existing.owner_username != username and username != "himanshu":
        raise HTTPException(403, "You do not have permission to delete this phone extension")

    ext = existing.extension
    deleted = store.delete_phone(phone_id)
    if not deleted:
        raise HTTPException(500, "Failed to delete phone record")

    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)

    return {
        "ok": True,
        "id": phone_id,
        "extension": ext,
        "sync": sync_res,
        "message": f"Extension {ext} deleted",
    }


@router.post("/telephony/phones/bulk")
async def bulk_create_phones(request: Request, body: BulkCreateRequest) -> dict[str, Any]:
    store = request.app.state.store
    username = get_current_username(request) or "himanshu"
    phones = store.bulk_create_phones(
        count=body.count,
        start_extension=body.start_extension,
        password_prefix=body.password_prefix,
        device_type=body.device_type,
        owner_username=username,
    )

    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)

    return {
        "ok": True,
        "count": len(phones),
        "phones": [p.to_dict() for p in phones],
        "sync": sync_res,
        "message": f"Provisioned {len(phones)} legacy phone extensions (optional Asterisk profile)",
    }


@router.post("/telephony/reload")
async def reload_server(request: Request) -> dict[str, Any]:
    store = request.app.state.store
    runtime = request.app.state.runtime
    host = _public_host(request)
    api_base = _api_base(request, host)
    agents = [a for a in store.list_agents() if a.status == "deployed" and a.port]
    freepbx_path = Path("platform_data/freepbx/extensions_custom_callforge.conf")
    write_freepbx_dialplan(agents, freepbx_path, host=host, api_base=api_base)

    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)
    return {
        "ok": True,
        "freepbx_dialplan": str(freepbx_path),
        "live_lines": runtime.live_status(),
        "sync": sync_res,
        "message": "FreePBX dialplan refreshed. Paste platform_data/freepbx/extensions_custom_callforge.conf into FreePBX.",
    }


@router.get("/telephony/phones/{phone_id}/config")
async def get_phone_config(request: Request, phone_id: str) -> dict[str, Any]:
    store = request.app.state.store
    phone = store.get_phone(phone_id)
    if not phone:
        raise HTTPException(404, "Phone extension not found")

    net_ips = get_network_ips()
    primary_ip = net_ips[0] if net_ips else "127.0.0.1"
    port = 5060

    sip_uri = f"sip:{phone.extension}@{primary_ip}:{port}"
    qr_data = f"SIP:{phone.extension}:{phone.password}@{primary_ip}:{port}"

    return {
        "phone": phone.to_dict(),
        "credentials": {
            "sip_server": primary_ip,
            "sip_port": port,
            "sip_domain": f"{primary_ip}:{port}",
            "username": phone.extension,
            "auth_user": phone.extension,
            "password": phone.password,
            "display_name": phone.name,
            "transport": "UDP",
            "codecs": ["ulaw", "alaw", "g722", "opus"],
            "stun_server": "",
            "sip_uri": sip_uri,
            "qr_data": qr_data,
        },
        "setup_guides": {
            "note": "Prefer FreePBX for phones. This config is only for the optional legacy-asterisk Docker profile.",
        },
        "dialing_instructions": [
            "Production: manage phones inside FreePBX and route AI calls via Method 1 AudioSocket.",
            "Legacy local Asterisk: dial AI agent extension (e.g. 2000) only if legacy-asterisk profile is running.",
        ],
    }


@router.post("/telephony/call")
async def trigger_intercom_call(body: TestCallRequest) -> dict[str, Any]:
    from_ext = body.from_extension.strip()
    to_ext = body.to_extension.strip()

    try:
        res = await originate_intercom_call(from_ext, to_ext)
        return {
            "ok": res.get("success", False),
            "result": res,
            "message": f"Calling extension {to_ext} from {from_ext}...",
        }
    except Exception as exc:
        logger.exception("Error originating test call: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/telephony/freepbx/gui-status")
async def freepbx_gui_status(request: Request) -> dict[str, Any]:
    """Check FreePBX GUI status and return access instructions."""
    import os
    import httpx

    env_url = (os.getenv("FREEPBX_GUI_URL") or "").strip()
    candidates = [env_url] if env_url else ["http://127.0.0.1:8088/admin", "http://127.0.0.1:80/admin"]
    online = False
    chosen_url = candidates[0]
    status_detail = "Offline"

    for candidate in candidates:
        if not candidate:
            continue
        try:
            async with httpx.AsyncClient(timeout=1.0, verify=False) as client:
                resp = await client.get(candidate)
                if resp.status_code in (200, 301, 302, 401, 403):
                    online = True
                    chosen_url = candidate
                    status_detail = f"Online (HTTP {resp.status_code})"
                    break
        except Exception as exc:
            err_msg = str(exc)
            status_detail = f"Offline ({err_msg.split(':')[-1].strip() or 'connection refused'})"

    username = get_current_username(request)

    return {
        "ok": True,
        "online": online,
        "status_detail": status_detail,
        "gui_url": chosen_url,
        "access_mode": "authenticated_app_only",
        "user_authenticated": bool(username),
        "username": username or "guest",
        "message": (
            "Calling server and extensions are managed centrally via FreePBX GUI. "
            "Direct external IP access is restricted for security; launch only through the CallForge console."
        ),
    }
