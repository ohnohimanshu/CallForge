"""
CallForge process entry — voice runtime + HTTP control plane in one process.

Shared STT/LLM stay warm; each deployed agent gets its own AudioSocket port.
The UI (web/dist) is served by FastAPI on API_PORT (default 8080).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from api import create_api
from callforge.runtime.agent_runtime import AgentRuntime
from callforge.store.db import PlatformStore
from config import load_settings

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "platform_data"
DB_PATH = DATA_DIR / "callforge.db"
UPLOAD_ROOT = DATA_DIR / "uploads"
DIALPLAN_PATH = ROOT / "asterisk-server" / "extensions_agents.conf"
PHONES_PJSIP_PATH = ROOT / "asterisk-server" / "pjsip_phones.conf"
PHONES_DIALPLAN_PATH = ROOT / "asterisk-server" / "extensions_phones.conf"


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("processing.vad").setLevel(logging.DEBUG)


class Application:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.store = PlatformStore(DB_PATH)
        self.runtime = AgentRuntime(
            settings=self.settings,
            store=self.store,
            dialplan_path=DIALPLAN_PATH,
            ollama_base_url=self.settings.llm.base_url,
        )
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        self.api = create_api(
            self.settings,
            self.store,
            self.runtime,
            UPLOAD_ROOT,
            phones_pjsip_path=PHONES_PJSIP_PATH,
            phones_dialplan_path=PHONES_DIALPLAN_PATH,
        )
        self._shutdown = asyncio.Event()
        self._uvicorn: uvicorn.Server | None = None

    async def start(self) -> None:
        await self.runtime.start()

        # Seed and synchronize telephony server (IP phones & mobile extensions)
        self.store.seed_default_phones()
        try:
            from callforge.runtime.telephony_server import sync_telephony_server
            sync_res = await sync_telephony_server(self.store, PHONES_PJSIP_PATH, PHONES_DIALPLAN_PATH)
            logger.info("Telephony Server active (%d phone extension(s) loaded)", sync_res.get("phones_count", 0))
        except Exception as e:
            logger.warning("Telephony Server auto-sync warning: %s", e)

        # Seed a default agent on first run so dialing 2000 works out of the box
        if not self.store.list_agents():
            agent = self.store.create_agent(
                name="Default Agent",
                description="Starter voice agent — edit or replace from the UI",
                extension="2000",
                language="auto",
                llm_model=self.settings.llm.model,
                system_prompt=self.settings.llm.system_prompt,
                greeting_text=self.settings.llm.greeting_text,
            )
            await self.runtime.deploy(agent.id)
            logger.info("Seeded and deployed default agent on extension 2000")

        api_host = os.getenv("API_HOST", "0.0.0.0")
        api_port = int(os.getenv("API_PORT", "8080"))
        ssl_keyfile = os.getenv("SSL_KEYFILE")
        ssl_certfile = os.getenv("SSL_CERTFILE")

        if ssl_keyfile and not Path(ssl_keyfile).exists():
            logger.warning("SSL keyfile specified (%s) but does not exist, falling back to HTTP", ssl_keyfile)
            ssl_keyfile = None
        if ssl_certfile and not Path(ssl_certfile).exists():
            logger.warning("SSL certfile specified (%s) but does not exist, falling back to HTTP", ssl_certfile)
            ssl_certfile = None

        scheme = "https" if (ssl_keyfile and ssl_certfile) else "http"
        config = uvicorn.Config(
            self.api,
            host=api_host,
            port=api_port,
            log_level=self.settings.log_level.lower(),
            loop="asyncio",
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
        )
        self._uvicorn = uvicorn.Server(config)
        logger.info("CallForge UI/API listening on %s://%s:%d", scheme, api_host, api_port)

    async def run_until_shutdown(self) -> None:
        assert self._uvicorn is not None
        api_task = asyncio.create_task(self._uvicorn.serve(), name="api")
        shutdown_task = asyncio.create_task(self._shutdown.wait(), name="shutdown")
        done, pending = await asyncio.wait(
            {api_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.shutdown()

    def request_shutdown(self) -> None:
        self._shutdown.set()
        if self._uvicorn is not None:
            self._uvicorn.should_exit = True

    async def shutdown(self) -> None:
        logger.info("Shutting down CallForge...")
        await self.runtime.shutdown()
        logger.info("Shutdown complete")


def _install_signals(loop: asyncio.AbstractEventLoop, app: Application) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, app.request_shutdown)
        except NotImplementedError:
            pass


async def _amain() -> None:
    app = Application()
    _configure_logging(app.settings.log_level)
    logger.info(
        "Starting CallForge: STT=%s LLM=%s",
        app.settings.stt.model_size,
        app.settings.llm.model,
    )
    loop = asyncio.get_running_loop()
    _install_signals(loop, app)
    await app.start()
    await app.run_until_shutdown()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
