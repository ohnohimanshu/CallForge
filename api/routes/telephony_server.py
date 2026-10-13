"""Telephony Server API routes — PBX server management, phone extensions, and mobile onboarding."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from callforge.runtime.telephony_server import (
    get_network_ips,
    get_phones_with_presence,
    get_telephony_server_info,
    originate_intercom_call,
    sync_telephony_server,
)
from callforge.store.models import PhoneRecord

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


@router.get("/telephony/server")
async def get_server_status(request: Request) -> dict[str, Any]:
    """Get telephony server health, IP addresses, ports, and configuration overview."""
    store = request.app.state.store
    return await get_telephony_server_info(store)


@router.get("/telephony/phones")
async def list_phones(request: Request) -> list[dict[str, Any]]:
    """List all configured phone extensions with live online/offline presence."""
    store = request.app.state.store
    return await get_phones_with_presence(store)


@router.post("/telephony/phones")
async def create_phone(request: Request, body: PhoneCreateRequest) -> dict[str, Any]:
    """Add a new IP phone or mobile softphone extension to the telephony server."""
    store = request.app.state.store
    clean_ext = body.extension.strip()

    if not clean_ext.isdigit() and not clean_ext.isalnum():
        raise HTTPException(400, "Extension must contain numbers or alphanumeric characters")

    # Check for extension collision
    if store.get_phone_by_extension(clean_ext):
        raise HTTPException(409, f"Extension {clean_ext} already exists")

    # Check if collision with deployed AI agents
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
        owner_username="himanshu",
    )

    # Sync and reload Asterisk
    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)

    return {
        "ok": True,
        "phone": phone.to_dict(),
        "sync": sync_res,
        "message": f"Extension {clean_ext} added and loaded into PBX server successfully",
    }


@router.put("/telephony/phones/{phone_id}")
async def update_phone(request: Request, phone_id: str, body: PhoneUpdateRequest) -> dict[str, Any]:
    """Update phone extension configuration."""
    store = request.app.state.store
    existing = store.get_phone(phone_id)
    if not existing:
        raise HTTPException(404, "Phone extension not found")

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
        "message": f"Extension {updated.extension} updated and reloaded",
    }


@router.delete("/telephony/phones/{phone_id}")
async def delete_phone(request: Request, phone_id: str) -> dict[str, Any]:
    """Remove a phone extension from the telephony server."""
    store = request.app.state.store
    existing = store.get_phone(phone_id)
    if not existing:
        raise HTTPException(404, "Phone extension not found")

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
        "message": f"Extension {ext} deleted from PBX server",
    }


@router.post("/telephony/phones/bulk")
async def bulk_create_phones(request: Request, body: BulkCreateRequest) -> dict[str, Any]:
    """Bulk provision multiple IP phones or mobile extensions at once (e.g. 10 IP phones)."""
    store = request.app.state.store
    phones = store.bulk_create_phones(
        count=body.count,
        start_extension=body.start_extension,
        password_prefix=body.password_prefix,
        device_type=body.device_type,
        owner_username="himanshu",
    )

    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)

    return {
        "ok": True,
        "count": len(phones),
        "phones": [p.to_dict() for p in phones],
        "sync": sync_res,
        "message": f"Successfully provisioned {len(phones)} new phone extensions on PBX server",
    }


@router.post("/telephony/reload")
async def reload_server(request: Request) -> dict[str, Any]:
    """Force synchronization and reload of Asterisk telephony server."""
    store = request.app.state.store
    pjsip_path, dialplan_path = _paths(request)
    sync_res = await sync_telephony_server(store, pjsip_path, dialplan_path)
    return {
        "ok": sync_res.get("reload", {}).get("success", False),
        "sync": sync_res,
    }


@router.get("/telephony/phones/{phone_id}/config")
async def get_phone_config(request: Request, phone_id: str) -> dict[str, Any]:
    """Get ready-to-use SIP credentials and QR code setup string for mobile & hardware IP phones."""
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
            "linphone": {
                "title": "Linphone (Android / iOS / Windows / Mac)",
                "steps": [
                    "Download and launch Linphone from App Store / Google Play",
                    "Choose 'USE SIP ACCOUNT'",
                    f"Username: {phone.extension}",
                    f"SIP Domain: {primary_ip}:{port}",
                    f"Password: {phone.password}",
                    "Transport: UDP",
                    "Tap 'LOGIN' — you will see a green status dot indicating connected!",
                ],
            },
            "zoiper": {
                "title": "Zoiper (Android / iOS / PC)",
                "steps": [
                    "Open Zoiper and click 'Add Account' -> 'SIP'",
                    f"Username: {phone.extension}@{primary_ip}:{port}",
                    f"Password: {phone.password}",
                    "Outbound Proxy: leave blank or set to UDP",
                    "Click 'Next' until UDP test is successful (green checkmark)",
                ],
            },
            "ip_hardware": {
                "title": "Physical IP Phone (Yealink / Grandstream / Cisco / Fanvil)",
                "steps": [
                    "Open the IP Phone's web management interface in your browser",
                    "Navigate to: Account -> Basic / SIP Settings",
                    f"Account / Display Name: {phone.name}",
                    f"SIP Server / Register Address: {primary_ip}",
                    f"Server Port: {port}",
                    f"Register Name / Username: {phone.extension}",
                    f"Password: {phone.password}",
                    "Save & Apply — phone screen will show 'Registered' with extension number!",
                ],
            },
        },
        "dialing_instructions": [
            f"To call any other phone: Simply dial their extension (e.g. 1002, 1003) and press send",
            "To join group Conference Bridge: Dial 8888",
            "To broadcast / Ring All phones: Dial 8000",
            "To test your microphone / echo: Dial *43 or 9999",
            "To speak with your AI Voice Agent: Dial 2000",
        ],
    }


@router.post("/telephony/call")
async def trigger_intercom_call(body: TestCallRequest) -> dict[str, Any]:
    """Trigger an internal test call between two extensions via Asterisk AMI."""
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
