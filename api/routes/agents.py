from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from api.routes.auth import get_current_username
from api.schemas import DEFAULT_SYSTEM_PROMPT, AgentCreate, AgentUpdate

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)


@router.get("")
async def list_agents(request: Request):
    username = get_current_username(request)
    # Filter by user if logged in; default to himanshu if not specified
    target_owner = username if username else None
    return [a.to_dict() for a in request.app.state.store.list_agents(owner_username=target_owner)]


@router.post("")
async def create_agent(body: AgentCreate, request: Request):
    store = request.app.state.store
    username = get_current_username(request) or "himanshu"
    ext = body.extension
    existing = store.get_agent_by_extension(ext)
    if existing:
        if ext == "2000":
            used = {str(a.extension) for a in store.list_agents()}
            cand = 2000
            while str(cand) in used:
                cand += 1
            ext = str(cand)
        else:
            raise HTTPException(
                400,
                f"Extension {ext} is already in use by '{existing.name}'. Please choose a different extension.",
            )
    data = body.model_dump()
    data["extension"] = ext
    data["owner_username"] = username
    data["system_prompt"] = body.system_prompt or DEFAULT_SYSTEM_PROMPT
    if not data.get("cloned_voice_sample_path"):
        data["cloned_voice_sample_path"] = ""
    agent = store.create_agent(**data)
    return agent.to_dict()


@router.get("/{agent_id}")
async def get_agent(agent_id: str, request: Request):
    agent = request.app.state.store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    username = get_current_username(request)
    if username and agent.owner_username and agent.owner_username != username and username != "himanshu":
        raise HTTPException(403, "Access denied: you do not own this agent")
    return agent.to_dict()


@router.get("/{agent_id}/ab-stats")
async def get_agent_ab_stats(agent_id: str, request: Request):
    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return store.get_ab_stats(agent_id)



@router.patch("/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate, request: Request):
    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    data = body.model_dump(exclude_unset=True)
    if "extension" in data and data["extension"] != agent.extension:
        conflict = store.get_agent_by_extension(data["extension"])
        if conflict and conflict.id != agent_id:
            raise HTTPException(400, f"Extension {data['extension']} already in use")
    updated = store.update_agent(agent_id, **data)
    assert updated is not None
    # Hot-reload live config if currently deployed
    if updated.status == "deployed":
        try:
            await request.app.state.runtime.reload_agent(agent_id)
        except Exception as exc:
            logger.warning("Reload after update failed: %s", exc)
    return updated.to_dict()


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, request: Request):
    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.status == "deployed":
        await request.app.state.runtime.undeploy(agent_id)
    store.delete_agent(agent_id)
    return {"ok": True}


@router.post("/{agent_id}/voice-clone/upload")
async def upload_voice_clone(agent_id: str, file: UploadFile = File(...), request: Request = None):
    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    content = await file.read()
    if len(content) < 1000:
        raise HTTPException(400, "Audio file is too small or invalid")

    try:
        from services.voice_clone_service import voice_clone_service
        profile = voice_clone_service.save_reference_sample(
            agent_id=agent_id,
            audio_bytes=content,
            filename=file.filename or "sample.wav",
        )
        sample_path = profile["sample_path"]
        matched_voice = profile.get("matched_base_voice")
        update_kwargs = {
            "voice_cloning_enabled": True,
            "cloned_voice_sample_path": sample_path,
        }
        if matched_voice:
            update_kwargs["voice_en"] = matched_voice
            logger.info("Voice clone auto-matched base voice %s for agent %s", matched_voice, agent_id)

        updated = store.update_agent(
            agent_id,
            **update_kwargs,
        )
        # Hot-reload live line if deployed
        if updated and updated.status == "deployed":
            try:
                await request.app.state.runtime.reload_agent(agent_id)
            except Exception as e:
                logger.warning("Failed to reload agent after voice clone update: %s", e)

        return {
            "ok": True,
            "profile": profile,
            "agent": updated.to_dict() if updated else None,
        }
    except Exception as exc:
        logger.exception("Failed to process voice clone sample: %s", exc)
        raise HTTPException(500, f"Failed to process audio sample: {exc}")


@router.get("/{agent_id}/voice-clone/sample")
async def get_voice_clone_sample(agent_id: str, request: Request):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from services.voice_clone_service import voice_clone_service

    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    profile = voice_clone_service.get_profile(agent_id)
    if not profile or not Path(profile["sample_path"]).exists():
        raise HTTPException(404, "Voice sample not found")
    return FileResponse(profile["sample_path"], media_type="audio/wav", filename=f"{agent.name}_sample.wav")


@router.api_route("/{agent_id}/voice-clone/preview", methods=["GET", "POST"])
async def preview_voice_clone(agent_id: str, request: Request):
    from pathlib import Path
    from fastapi.responses import Response
    from services.voice_clone_service import voice_clone_service

    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    profile = voice_clone_service.get_profile(agent_id)
    if not profile or not Path(profile["sample_path"]).exists():
        raise HTTPException(400, "No cloned voice sample uploaded yet")

    matched_voice = profile.get("matched_base_voice")
    if matched_voice and agent.voice_en != matched_voice:
        updated_agent = store.update_agent(agent_id, voice_en=matched_voice)
        if updated_agent:
            agent = updated_agent

    preview_text = ""
    if request.method == "POST":
        try:
            body = await request.json() if request.headers.get("content-type") == "application/json" else {}
            preview_text = body.get("text", "")
        except Exception:
            pass
    if not preview_text:
        preview_text = request.query_params.get("text", "")
    if not preview_text:
        preview_text = f"Hello, I am {agent.name}. This is your custom branded cloned voice speaking."

    line = getattr(request.app.state.runtime, "_lines", {}).get(agent_id)
    base_func = None
    temp_tts = None
    if line and getattr(line, "tts", None) is not None:
        base_func = line.tts.synthesize_raw
    else:
        try:
            from callforge.runtime.voices import tts_settings_for_agent, telephony_settings_for_port
            from services.tts_service import TtsService
            settings = request.app.state.settings
            port = agent.port or 9092
            temp_tts = TtsService(
                tts_settings_for_agent(agent, settings.tts),
                telephony_settings_for_port(settings.telephony, port),
                warm_pool_size=1,
            )
            base_func = temp_tts.synthesize_raw
        except Exception as e:
            logger.debug("Failed initializing temporary TTS service for preview: %s", e)

    try:
        wav_bytes = await voice_clone_service.generate_preview(
            agent_id=agent_id,
            preview_text=preview_text,
            base_tts_func=base_func,
        )
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as exc:
        logger.exception("Voice clone preview failed: %s", exc)
        raise HTTPException(500, f"Preview synthesis failed: {exc}")
    finally:
        if temp_tts is not None:
            temp_tts.shutdown()


@router.delete("/{agent_id}/voice-clone")
async def delete_voice_clone(agent_id: str, request: Request):
    from services.voice_clone_service import voice_clone_service

    store = request.app.state.store
    agent = store.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    voice_clone_service.delete_sample(agent_id)
    updated = store.update_agent(
        agent_id,
        voice_cloning_enabled=False,
        cloned_voice_sample_path="",
    )
    if updated and updated.status == "deployed":
        try:
            await request.app.state.runtime.reload_agent(agent_id)
        except Exception as e:
            logger.warning("Failed to reload agent after deleting voice clone: %s", e)
    return {"ok": True, "agent": updated.to_dict() if updated else None}


@router.post("/{agent_id}/deploy")
async def deploy_agent(agent_id: str, request: Request):
    store = request.app.state.store
    if not store.get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    try:
        agent = await request.app.state.runtime.deploy(agent_id)
    except Exception as exc:
        logger.exception("Deploy failed")
        raise HTTPException(500, f"Deploy failed: {exc}") from exc
    return {
        **agent.to_dict(),
        "dial_hint": f"Dial extension {agent.extension} from any SIP phone (guest/anonymous OK)",
        "reload_hint": "Asterisk dialplan auto-reloaded automatically",
    }


@router.post("/{agent_id}/undeploy")
async def undeploy_agent(agent_id: str, request: Request):
    if not request.app.state.store.get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    try:
        agent = await request.app.state.runtime.undeploy(agent_id)
    except Exception as exc:
        raise HTTPException(500, f"Undeploy failed: {exc}") from exc
    return agent.to_dict()
