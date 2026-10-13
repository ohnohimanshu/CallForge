"""
api/routes/auth.py
==================
Authentication routes for CallForge: Login, Signup, and User verification.
Supports multi-tenancy where users build and manage their own agents.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)
    full_name: Optional[str] = ""


def create_simple_token(username: str) -> str:
    """Create a lightweight base64 token with username for session persistence."""
    payload = {"sub": username}
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


def get_current_username(request: Request) -> Optional[str]:
    """
    Extract current username from Authorization header or X-User-Username header.
    Fallback to None if unauthenticated.
    """
    # 1. Check X-User-Username header
    custom_header = request.headers.get("X-User-Username")
    if custom_header:
        return custom_header.strip().lower()

    # 2. Check Authorization Bearer header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            decoded = json.loads(base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8"))
            return decoded.get("sub")
        except Exception:
            return None

    return None


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """Authenticate user with username and password."""
    store = request.app.state.store
    user = store.verify_user(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_simple_token(user.username)
    return {
        "ok": True,
        "token": token,
        "user": user.to_dict(),
    }


@router.post("/signup")
async def signup(body: SignupRequest, request: Request):
    """Register a new user on CallForge."""
    store = request.app.state.store
    try:
        user = store.create_user(
            username=body.username,
            password=body.password,
            full_name=body.full_name or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    token = create_simple_token(user.username)
    return {
        "ok": True,
        "token": token,
        "user": user.to_dict(),
    }


@router.get("/me")
async def get_me(request: Request):
    """Get current authenticated user profile."""
    username = get_current_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    store = request.app.state.store
    user = store.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "ok": True,
        "user": user.to_dict(),
    }
