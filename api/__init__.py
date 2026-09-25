"""CallForge FastAPI application — agent builder, deploy, docs, call history."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import agents, auth, callers, calls, campaigns, documents, meta, phone_numbers, simulator, wallboard
from callforge.runtime.agent_runtime import AgentRuntime
from callforge.runtime.campaign_engine import CampaignEngine
from callforge.store.db import PlatformStore
from config import Settings

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"


def create_api(
    settings: Settings,
    store: PlatformStore,
    runtime: AgentRuntime,
    upload_root: Path,
) -> FastAPI:
    app = FastAPI(
        title="CallForge",
        description="Build, deploy, and operate AI calling agents",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = settings
    app.state.store = store
    app.state.runtime = runtime
    app.state.upload_root = upload_root
    app.state.ollama_base_url = settings.llm.base_url
    app.state.campaign_engine = CampaignEngine(store=store)

    app.include_router(auth.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    app.include_router(phone_numbers.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(calls.router, prefix="/api")
    app.include_router(callers.router, prefix="/api")
    app.include_router(simulator.router, prefix="/api")
    app.include_router(wallboard.router, prefix="/api")
    app.include_router(campaigns.router, prefix="/api")

    if WEB_DIST.is_dir():
        assets = WEB_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        index = WEB_DIST / "index.html"

        @app.get("/")
        async def spa_index():
            return FileResponse(index)

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith(("api/", "docs", "openapi.json", "redoc")):
                raise HTTPException(404, "Not Found")
            candidate = WEB_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index)

    return app
