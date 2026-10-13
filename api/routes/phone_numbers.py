"""
api/routes/phone_numbers.py
===========================
API endpoints for searching, purchasing, assigning, and managing real mobile/DID
phone numbers for CallForge agents.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas import PhoneNumberAssignRequest
from services.telephony_provider import telephony_provider_service

router = APIRouter(tags=["phone-numbers"])
logger = logging.getLogger(__name__)


@router.get("/phone-numbers/pricing")
async def get_pricing():
    """Returns platform retail pricing and currency for phone numbers."""
    return telephony_provider_service.get_pricing_info()


@router.get("/phone-numbers/search")
async def search_numbers(
    country: str = Query(default="US", description="Two-letter ISO country code (US, GB, IN, CA, etc.)"),
    area_code: Optional[str] = Query(default=None, description="Optional 3-digit area code or prefix"),
    limit: int = Query(default=10, ge=1, le=20),
):
    """Search available real phone numbers that users can purchase for their agents."""
    try:
        numbers = await telephony_provider_service.search_available_numbers(
            country_code=country,
            area_code=area_code,
            limit=limit,
        )
        return [n.to_dict() for n in numbers]
    except Exception as exc:
        logger.exception("Error searching phone numbers: %s", exc)
        raise HTTPException(500, f"Failed to search phone numbers: {exc}")


@router.post("/agents/{agent_id}/phone-number/buy")
async def buy_and_assign_phone_number(
    agent_id: str,
    body: PhoneNumberAssignRequest,
    request: Request,
):
    """
    User-facing paid purchase & assignment:
    1. Purchases the number via Telnyx/Twilio (or sandbox pool).
    2. Binds the number to the agent in the platform DB.
    3. Auto-regenerates Asterisk dialplan so calls to this number route to the agent.
    """
    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    target_number = body.phone_number.strip()
    if not target_number.startswith("+"):
        target_number = f"+{target_number}"

    # Check if number is already assigned to another agent
    existing = store.get_agent_by_phone_number(target_number)
    if existing and existing.id != agent_id:
        raise HTTPException(400, f"Phone number {target_number} is already assigned to agent '{existing.name}'")

    try:
        # Perform carrier order / reservation
        result = await telephony_provider_service.purchase_and_assign_number(
            phone_number=target_number,
            country_code=body.country_code,
        )

        # Update agent record in DB
        updated = store.update_agent(
            agent_id,
            phone_number=target_number,
            phone_number_status="active",
            phone_number_price=result.get("monthly_price", 4.99),
            phone_number_country=body.country_code.upper(),
        )

        # If agent is currently deployed, regenerate Asterisk dialplan immediately
        if updated and updated.status == "deployed":
            try:
                from callforge.runtime.dialplan import write_agents_dialplan
                from pathlib import Path
                output_path = Path("/etc/asterisk/extensions_agents.conf")
                if not output_path.parent.exists():
                    output_path = Path("asterisk-server/extensions_agents.conf")
                write_agents_dialplan(store.list_agents(), output_path)

                # Trigger Asterisk reload
                await request.app.state.runtime.reload_agent(agent_id)
            except Exception as e:
                logger.warning("Dialplan reload after phone number assignment: %s", e)

        return {
            "ok": True,
            "message": f"Successfully purchased and assigned {target_number} to agent '{agent.name}'",
            "phone_number": target_number,
            "agent": updated.to_dict() if updated else None,
            "provider": result.get("provider", "sandbox"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to purchase phone number: %s", exc)
        raise HTTPException(500, f"Failed to complete phone number purchase: {exc}")


@router.delete("/agents/{agent_id}/phone-number")
async def release_phone_number(agent_id: str, request: Request):
    """Releases the assigned phone number from the agent."""
    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    if not agent.phone_number:
        return {"ok": True, "message": "Agent has no phone number assigned"}

    old_number = agent.phone_number
    try:
        await telephony_provider_service.release_number(old_number)
    except Exception as e:
        logger.warning("Upstream carrier release warning: %s", e)

    updated = store.update_agent(
        agent_id,
        phone_number="",
        phone_number_status="none",
    )

    # Regenerate dialplan if deployed
    if updated and updated.status == "deployed":
        try:
            from callforge.runtime.dialplan import write_agents_dialplan
            from pathlib import Path
            output_path = Path("/etc/asterisk/extensions_agents.conf")
            if not output_path.parent.exists():
                output_path = Path("asterisk-server/extensions_agents.conf")
            write_agents_dialplan(store.list_agents(), output_path)
            await request.app.state.runtime.reload_agent(agent_id)
        except Exception as e:
            logger.warning("Dialplan reload after releasing phone number: %s", e)

    return {
        "ok": True,
        "message": f"Released phone number {old_number}",
        "agent": updated.to_dict() if updated else None,
    }
