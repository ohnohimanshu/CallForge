"""Asterisk Manager Interface (AMI) & PBX auto-reload controller.

Automatically notifies Asterisk whenever CallForge creates, updates,
or removes agent dialplans, avoiding the need for manual server restarts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_AMI_HOST = os.getenv("ASTERISK_AMI_HOST", "127.0.0.1")
DEFAULT_AMI_PORT = int(os.getenv("ASTERISK_AMI_PORT", "5038"))
DEFAULT_AMI_USER = os.getenv("ASTERISK_AMI_USER", "callforge")
DEFAULT_AMI_SECRET = os.getenv("ASTERISK_AMI_SECRET", "callforge123")


async def _read_ami_response(reader: asyncio.StreamReader, timeout: float = 2.0) -> str:
    """Read an AMI response block ending with empty line (\r\n\r\n)."""
    lines = []
    try:
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            lines.append(decoded)
            if decoded.strip() == "" and len(lines) > 1:
                break
            # Some Command responses end with --END COMMAND--
            if "--END COMMAND--" in decoded:
                break
    except (asyncio.TimeoutError, Exception) as exc:
        logger.debug("AMI read timeout or exception: %s", exc)
    return "".join(lines)


async def reload_asterisk_ami(
    host: str = DEFAULT_AMI_HOST,
    port: int = DEFAULT_AMI_PORT,
    user: str = DEFAULT_AMI_USER,
    secret: str = DEFAULT_AMI_SECRET,
    timeout: float = 2.5,
) -> dict:
    """Connect to Asterisk AMI over TCP and trigger dialplan & core reload."""
    reader, writer = None, None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )

        # Read initial Asterisk greeting banner
        banner = await asyncio.wait_for(reader.readline(), timeout=timeout)
        logger.debug("AMI Banner: %s", banner.decode().strip())

        # Login
        login_msg = f"Action: Login\r\nUsername: {user}\r\nSecret: {secret}\r\n\r\n"
        writer.write(login_msg.encode("utf-8"))
        await writer.drain()

        resp = await _read_ami_response(reader, timeout=timeout)
        if "Response: Success" not in resp:
            logger.warning("AMI Login failed: %s", resp.strip())
            return {"success": False, "method": "ami", "error": f"Login failed: {resp.strip()}"}

        # 1. Reload dialplan (re-reads extensions.conf and extensions_agents.conf)
        writer.write(b"Action: Command\r\nCommand: dialplan reload\r\n\r\n")
        await writer.drain()
        dialplan_resp = await _read_ami_response(reader, timeout=timeout)
        logger.info("Asterisk AMI dialplan reload output:\n%s", dialplan_resp.strip())

        # 2. Core reload (reloads all modules and configs)
        writer.write(b"Action: Command\r\nCommand: core reload\r\n\r\n")
        await writer.drain()
        core_resp = await _read_ami_response(reader, timeout=timeout)

        # Logoff
        writer.write(b"Action: Logoff\r\n\r\n")
        await writer.drain()

        return {
            "success": True,
            "method": "ami",
            "message": "Asterisk dialplan and core reloaded successfully via AMI",
            "dialplan_output": dialplan_resp.strip(),
        }

    except (ConnectionRefusedError, OSError) as exc:
        return {"success": False, "method": "ami", "error": f"AMI connection refused ({exc})"}
    except asyncio.TimeoutError:
        return {"success": False, "method": "ami", "error": "AMI connection timed out"}
    except Exception as exc:
        return {"success": False, "method": "ami", "error": str(exc)}
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def restart_asterisk_ami(
    host: str = DEFAULT_AMI_HOST,
    port: int = DEFAULT_AMI_PORT,
    user: str = DEFAULT_AMI_USER,
    secret: str = DEFAULT_AMI_SECRET,
    timeout: float = 2.5,
) -> dict:
    """Connect to Asterisk AMI over TCP and trigger a core restart."""
    reader, writer = None, None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        await asyncio.wait_for(reader.readline(), timeout=timeout)

        # Login
        login_msg = f"Action: Login\r\nUsername: {user}\r\nSecret: {secret}\r\n\r\n"
        writer.write(login_msg.encode("utf-8"))
        await writer.drain()

        resp = await _read_ami_response(reader, timeout=timeout)
        if "Response: Success" not in resp:
            return {"success": False, "method": "ami", "error": f"Login failed: {resp.strip()}"}

        # Issue restart command
        writer.write(b"Action: Command\r\nCommand: core restart gracefully\r\n\r\n")
        await writer.drain()
        restart_resp = await _read_ami_response(reader, timeout=timeout)

        writer.write(b"Action: Logoff\r\n\r\n")
        await writer.drain()

        return {
            "success": True,
            "method": "ami_restart",
            "message": "Asterisk graceful restart initiated via AMI",
            "output": restart_resp.strip(),
        }
    except Exception as exc:
        return {"success": False, "method": "ami_restart", "error": str(exc)}
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def reload_asterisk_cli() -> dict:
    """Fallback: Attempt to reload Asterisk via docker exec or local CLI."""
    # Try docker exec first
    if shutil.which("docker"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "asterisk-pbx", "asterisk", "-rx", "dialplan reload",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode == 0:
                return {
                    "success": True,
                    "method": "docker_cli",
                    "message": "Asterisk dialplan reloaded via docker exec",
                    "output": stdout.decode().strip(),
                }
        except Exception as exc:
            logger.debug("docker exec reload failed: %s", exc)

    # Try local asterisk CLI
    if shutil.which("asterisk"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "asterisk", "-rx", "dialplan reload",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode == 0:
                return {
                    "success": True,
                    "method": "local_cli",
                    "message": "Asterisk dialplan reloaded via local asterisk CLI",
                    "output": stdout.decode().strip(),
                }
        except Exception as exc:
            logger.debug("local asterisk CLI reload failed: %s", exc)

    # Try pkill -HUP (exact process name 'asterisk')
    if shutil.which("pkill"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "pkill", "-HUP", "-x", "asterisk",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=2.0)
            if proc.returncode == 0:
                return {
                    "success": True,
                    "method": "sighup",
                    "message": "Sent SIGHUP to Asterisk process to reload configuration",
                }
        except Exception as exc:
            logger.debug("pkill -HUP failed: %s", exc)

    return {"success": False, "method": "cli", "error": "No CLI method succeeded"}


async def reload_asterisk() -> dict:
    """Unified helper to reload Asterisk dialplan immediately.
    
    Tries:
    1. AMI over TCP (127.0.0.1:5038) - cleanest, works across host & docker container
    2. Docker exec (if docker available)
    3. Local asterisk CLI / SIGHUP
    """
    # 1. Try AMI
    ami_result = await reload_asterisk_ami()
    if ami_result.get("success"):
        logger.info("Asterisk dialplan auto-reloaded via AMI.")
        return ami_result

    # 2. Try CLI fallbacks
    cli_result = await reload_asterisk_cli()
    if cli_result.get("success"):
        logger.info("Asterisk dialplan auto-reloaded via CLI.")
        return cli_result

    logger.warning(
        "Asterisk reload skipped: Asterisk is currently offline or AMI is unreachable. "
        "The dialplan file was saved to disk and will be loaded when Asterisk starts."
    )
    return {
        "success": False,
        "message": "Dialplan saved to disk. Asterisk is offline or unreachable.",
        "ami_error": ami_result.get("error"),
    }


async def originate_call_ami(
    channel: str,
    exten: str,
    context: str = "from-internal",
    priority: int = 1,
    caller_id: str = "Outbound AI",
    variables: Optional[dict[str, str]] = None,
    timeout_ms: int = 30000,
    host: str = DEFAULT_AMI_HOST,
    port: int = DEFAULT_AMI_PORT,
    user: str = DEFAULT_AMI_USER,
    secret: str = DEFAULT_AMI_SECRET,
    async_originate: bool = False,
) -> dict:
    """Originate an outbound call via Asterisk Manager Interface (AMI)."""
    action_id = f"orig_{uuid.uuid4().hex[:10]}"
    reader, writer = None, None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=4.0
        )
        # Read Asterisk banner
        await asyncio.wait_for(reader.readline(), timeout=3.0)

        # Login
        login_msg = f"Action: Login\r\nUsername: {user}\r\nSecret: {secret}\r\nActionID: log_{action_id}\r\n\r\n"
        writer.write(login_msg.encode("utf-8"))
        await writer.drain()

        # Wait for login confirmation
        login_ok = False
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=3.0)
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if f"ActionID: log_{action_id}" in decoded or "Authentication accepted" in decoded:
                login_ok = True
                while True:
                    hdr = (await asyncio.wait_for(reader.readline(), timeout=2.0)).decode("utf-8", errors="replace").strip()
                    if not hdr:
                        break
                break

        if not login_ok:
            return {"success": False, "error": "AMI login failed"}

        # Build Originate action
        var_lines = ""
        if variables:
            var_parts = [f"{k}={v}" for k, v in variables.items() if v is not None]
            if var_parts:
                var_lines = f"Variable: {','.join(var_parts)}\r\n"

        async_str = "true" if async_originate else "false"
        orig_msg = (
            f"Action: Originate\r\n"
            f"ActionID: {action_id}\r\n"
            f"Channel: {channel}\r\n"
            f"Exten: {exten}\r\n"
            f"Context: {context}\r\n"
            f"Priority: {priority}\r\n"
            f"CallerID: {caller_id}\r\n"
            f"Timeout: {timeout_ms}\r\n"
            f"Async: {async_str}\r\n"
            f"{var_lines}"
            f"\r\n"
        )
        writer.write(orig_msg.encode("utf-8"))
        await writer.drain()

        resp_status = None
        resp_message = ""
        orig_timeout = (timeout_ms / 1000.0) + 6.0

        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=orig_timeout)
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded.startswith("Response:"):
                resp_status = decoded.split(":", 1)[1].strip()
            elif decoded.startswith("Message:"):
                resp_message = decoded.split(":", 1)[1].strip()
            elif decoded == f"ActionID: {action_id}":
                while True:
                    hdr = (await asyncio.wait_for(reader.readline(), timeout=2.0)).decode("utf-8", errors="replace").strip()
                    if not hdr:
                        break
                    if hdr.startswith("Message:"):
                        resp_message = hdr.split(":", 1)[1].strip()
                break

        try:
            writer.write(b"Action: Logoff\r\n\r\n")
            await writer.drain()
        except Exception:
            pass

        if resp_status == "Success":
            logger.info("Asterisk AMI Originate succeeded for channel %s to ext %s", channel, exten)
            return {"success": True, "action_id": action_id, "message": resp_message}
        else:
            logger.warning("Asterisk AMI Originate failed for channel %s: %s", channel, resp_message)
            return {"success": False, "action_id": action_id, "error": resp_message or "Originate failed"}

    except asyncio.TimeoutError:
        logger.warning("Asterisk AMI Originate timed out for channel %s", channel)
        return {"success": False, "error": f"AMI Originate timed out after {timeout_ms}ms"}
    except Exception as exc:
        logger.exception("AMI Originate exception for channel %s: %s", channel, exc)
        return {"success": False, "error": str(exc)}
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

