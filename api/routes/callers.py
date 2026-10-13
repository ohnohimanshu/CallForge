from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from services.caller_memory_service import caller_memory_service

router = APIRouter(prefix="/callers", tags=["callers"])
logger = logging.getLogger(__name__)


@router.get("")
async def list_callers(request: Request, limit: int = 50):
    store = request.app.state.store
    profiles = store.list_caller_profiles(limit=limit)
    return [
        {
            **p.to_dict(),
            "relative_time": caller_memory_service.format_relative_time(p.last_call_at),
            "topic": caller_memory_service.extract_topic_from_summary(p.last_summary),
        }
        for p in profiles
    ]


@router.get("/{phone_number}")
async def get_caller(phone_number: str, request: Request):
    store = request.app.state.store
    clean_phone = caller_memory_service.normalize_phone(phone_number)
    profile = store.get_caller_profile(clean_phone)
    if not profile:
        raise HTTPException(404, f"No profile found for phone number {phone_number}")

    return {
        **profile.to_dict(),
        "relative_time": caller_memory_service.format_relative_time(profile.last_call_at),
        "topic": caller_memory_service.extract_topic_from_summary(profile.last_summary),
    }


@router.delete("/{phone_number}")
async def delete_caller(phone_number: str, request: Request):
    store = request.app.state.store
    clean_phone = caller_memory_service.normalize_phone(phone_number)
    ok = store.delete_caller_profile(clean_phone)
    if not ok:
        raise HTTPException(404, f"No profile found for phone number {phone_number}")
    return {"ok": True, "message": f"Deleted profile for {phone_number}"}
