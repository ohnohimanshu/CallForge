import asyncio
import io
import wave
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from piper import PiperVoice

from api.schemas import DEFAULT_SYSTEM_PROMPT
from callforge.runtime.asterisk_manager import reload_asterisk, restart_asterisk_ami
from callforge.runtime.dialogue import STANDARD_SLOTS_PRESET
from callforge.runtime.voices import resolve_voice_path
from callforge.store.models import (
    AVAILABLE_LANGUAGES,
    AVAILABLE_MODELS,
    AVAILABLE_VOICES_EN,
    AVAILABLE_VOICES_HI,
)

router = APIRouter(tags=["meta"])

_VOICE_SAMPLE_CACHE: dict[str, bytes] = {}


@router.get("/health")
async def health(request: Request):
    runtime = request.app.state.runtime
    return {
        "status": "ok",
        "runtime_ready": runtime.ready,
        "live_lines": runtime.live_status(),
    }


@router.post("/telephony/reload-asterisk")
async def reload_asterisk_endpoint():
    """Manually trigger an Asterisk dialplan & core reload."""
    result = await reload_asterisk()
    return result


@router.post("/telephony/restart-asterisk")
async def restart_asterisk_endpoint():
    """Manually trigger an Asterisk core restart."""
    result = await restart_asterisk_ami()
    return result


from api.routes.auth import get_current_username

@router.get("/stats")
async def stats(request: Request):
    username = get_current_username(request)
    return request.app.state.store.stats(owner_username=username)


@router.get("/options")
async def options(request: Request):
    store = getattr(request.app.state, "store", None)
    next_ext = "2000"
    if store:
        used = {str(a.extension) for a in store.list_agents()}
        cand = 2000
        while str(cand) in used:
            cand += 1
        next_ext = str(cand)
    return {
        "languages": AVAILABLE_LANGUAGES,
        "models": AVAILABLE_MODELS,
        "voices_en": AVAILABLE_VOICES_EN,
        "voices_hi": AVAILABLE_VOICES_HI,
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "dialogue_slots_preset": STANDARD_SLOTS_PRESET,
        "suggested_extension": next_ext,
    }


@router.get("/voice-sample")
async def voice_sample(voice: str = "en_US-lessac-medium", text: str = ""):
    cache_key = f"{voice}_{text}"
    if cache_key in _VOICE_SAMPLE_CACHE:
        return Response(content=_VOICE_SAMPLE_CACHE[cache_key], media_type="audio/wav")

    path = resolve_voice_path(voice)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Voice model '{voice}' not found on server")

    sample_text = text.strip()
    if not sample_text:
        if "hi" in voice.lower():
            sample_text = "नमस्ते! मैं आपकी कॉल में सहायता करने के लिए तैयार हूँ।"
        else:
            sample_text = "Hello! I am your automated AI voice assistant. How can I help you today?"

    try:
        loop = asyncio.get_running_loop()

        def _synth() -> bytes:
            v = PiperVoice.load(str(path), str(path) + ".json")
            raw = b"".join(chunk.audio_int16_bytes for chunk in v.synthesize(sample_text))
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(v.config.sample_rate)
                wf.writeframes(raw)
            return buf.getvalue()

        wav_bytes = await loop.run_in_executor(None, _synth)
        _VOICE_SAMPLE_CACHE[cache_key] = wav_bytes
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to synthesize voice sample: {exc}")


@router.post("/tools/test-webhook")
async def test_webhook_endpoint(request: Request):
    """Test connectivity to a user's Google Apps Script or custom webhook URL."""
    body = await request.json()
    url = body.get("url", "").strip()
    if not url or not url.startswith("http"):
        return {"ok": False, "message": "Invalid URL. Please enter a full http:// or https:// URL."}

    from datetime import datetime, timedelta
    from callforge.runtime.tools import check_sheet_availability
    test_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        res = await check_sheet_availability(url, test_date)
        slots = res[0] if isinstance(res, (tuple, list)) else res
        return {
            "ok": True,
            "message": f"Successfully connected to Google Sheet! Found {len(slots)} available slot(s) for {test_date}.",
            "slots": slots,
        }
    except Exception as exc:
        return {"ok": False, "message": f"Webhook test failed: {exc}"}



