"""
callforge/runtime/campaign_engine.py
====================================
Outbound calling campaign scheduler, Asterisk call-file generator, and batch dialer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import uuid
from pathlib import Path
from typing import Optional

from callforge.runtime.asterisk_manager import originate_call_ami
from callforge.store.db import PlatformStore
from callforge.store.models import AgentRecord, CampaignContactRecord, CampaignRecord

logger = logging.getLogger(__name__)


class CampaignEngine:
    """Manages outbound dialing loops, Asterisk call files, and pacing."""

    def __init__(self, store: PlatformStore, spool_dir: Optional[Path] = None) -> None:
        self._store = store
        env_spool = os.getenv("ASTERISK_SPOOL_DIR")
        if spool_dir:
            self._spool_dir = spool_dir
        elif env_spool:
            self._spool_dir = Path(env_spool)
        elif Path("/var/spool/asterisk/outgoing").exists():
            self._spool_dir = Path("/var/spool/asterisk/outgoing")
        else:
            self._spool_dir = Path("platform_data/outgoing")
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def start_campaign(self, campaign_id: str) -> Optional[CampaignRecord]:
        """Activate a campaign and start the background dispatch task."""
        campaign = self._store.get_campaign(campaign_id)
        if not campaign:
            return None

        campaign = self._store.update_campaign(campaign_id, status="running")
        assert campaign is not None

        async with self._lock:
            if campaign_id not in self._active_tasks or self._active_tasks[campaign_id].done():
                task = asyncio.create_task(
                    self._campaign_loop(campaign_id), name=f"campaign-{campaign_id[:8]}"
                )
                self._active_tasks[campaign_id] = task

        logger.info("Campaign '%s' started with concurrency %d", campaign.name, campaign.concurrency_limit)
        return campaign

    async def pause_campaign(self, campaign_id: str) -> Optional[CampaignRecord]:
        """Pause dialing on a running campaign."""
        campaign = self._store.update_campaign(campaign_id, status="paused")
        async with self._lock:
            task = self._active_tasks.pop(campaign_id, None)
            if task and not task.done():
                task.cancel()
        logger.info("Campaign %s paused", campaign_id)
        return campaign

    def generate_call_file(
        self,
        contact: CampaignContactRecord,
        agent: AgentRecord,
        caller_id: str = "Outbound AI",
        greeting_text: str = "",
        collect_fields: str = "",
    ) -> Path:
        """
        Generate a standard Asterisk .call file.
        When answered, Asterisk connects the called channel to agent.extension in context 'internal'.
        """
        staging_dir = Path("platform_data/outgoing_staging")
        staging_dir.mkdir(parents=True, exist_ok=True)
        call_file = staging_dir / f"{contact.id}.call"

        # Determine dial string (PJSIP extension or trunk)
        phone = contact.phone.strip()
        channel = f"PJSIP/{phone}" if phone.isalnum() and len(phone) <= 5 else f"PJSIP/{phone}@guest"

        content = (
            f"Channel: {channel}\n"
            f"CallerID: \"{agent.name}\" <{caller_id}>\n"
            f"MaxRetries: 1\n"
            f"RetryTime: 60\n"
            f"WaitTime: 30\n"
            f"Context: internal\n"
            f"Extension: {agent.extension}\n"
            f"Priority: 1\n"
            f"Set: CAMPAIGN_ID={contact.campaign_id}\n"
            f"Set: CONTACT_ID={contact.id}\n"
            f"Set: CONTACT_NAME={contact.name}\n"
            f"Set: CAMPAIGN_GREETING={greeting_text}\n"
            f"Set: COLLECT_FIELDS={collect_fields}\n"
        )
        call_file.write_text(content, encoding="utf-8")

        # If system Asterisk spool directory is accessible, write atomically via temporary file
        try:
            if self._spool_dir.exists() and self._spool_dir.is_dir():
                tmp_target = self._spool_dir / f".{contact.id}.call.tmp"
                tmp_target.write_text(content, encoding="utf-8")
                target = self._spool_dir / f"{contact.id}.call"
                tmp_target.rename(target)
                logger.info("Dispatched call file to Asterisk spool: %s", target)
        except Exception as exc:
            logger.debug("Writing to Asterisk spool %s: %s", self._spool_dir, exc)

        return call_file

    async def _campaign_loop(self, campaign_id: str) -> None:
        """Background loop that paces outbound calls according to concurrency limits."""
        logger.info("Entered dispatch loop for campaign %s", campaign_id)
        try:
            while True:
                campaign = self._store.get_campaign(campaign_id)
                if not campaign or campaign.status != "running":
                    break

                agent = self._store.get_agent(campaign.agent_id)
                if not agent:
                    logger.error("Campaign %s: agent %s not found, stopping", campaign_id, campaign.agent_id)
                    self._store.update_campaign(campaign_id, status="paused")
                    break

                # Query pending contacts
                stats = self._store.get_campaign_stats(campaign_id)
                active_count = stats.get("dialing", 0) + stats.get("connected", 0)
                available_slots = max(0, campaign.concurrency_limit - active_count)

                if available_slots > 0:
                    pending = self._store.get_pending_contacts(campaign_id, limit=available_slots)
                    if not pending and active_count == 0:
                        logger.info("Campaign %s: all contacts completed!", campaign_id)
                        self._store.update_campaign(campaign_id, status="completed")
                        break

                    for contact in pending:
                        call_uuid = str(uuid.uuid4())
                        self._store.update_contact_status(
                            contact.id,
                            status="dialing",
                            call_uuid=call_uuid,
                        )
                        # Generate standard Asterisk call file with campaign-specific greeting & fields
                        self.generate_call_file(
                            contact,
                            agent,
                            caller_id=campaign.caller_id,
                            greeting_text=campaign.greeting_text,
                            collect_fields=campaign.collect_fields,
                        )

                        # Launch REAL outbound call via Asterisk AMI
                        asyncio.create_task(
                            self._dial_single_contact(contact, campaign, agent, call_uuid),
                            name=f"campaign-call-{contact.id[:8]}",
                        )

                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            logger.info("Campaign loop %s cancelled", campaign_id)
        except Exception:
            logger.exception("Error in campaign loop %s", campaign_id)

    async def _dial_single_contact(
        self, contact: CampaignContactRecord, campaign: CampaignRecord, agent: AgentRecord, call_uuid: str
    ) -> None:
        """Dial a real outbound contact via Asterisk AMI Originate and manage call lifecycle."""
        phone = contact.phone.strip()
        channel = f"PJSIP/{phone}" if phone.isalnum() and len(phone) <= 5 else f"PJSIP/{phone}@guest"
        caller_id = f'"{agent.name}" <{campaign.caller_id or agent.extension}>'

        logger.info(
            "Initiating campaign call for contact %s (%s) -> channel %s via agent ext %s (call_uuid=%s)",
            contact.id, phone, channel, agent.extension, call_uuid
        )

        # Pre-populate metadata so incoming AudioSocket can immediately associate call_uuid
        calls_dir = Path("asterisk-server/calls")
        calls_dir.mkdir(parents=True, exist_ok=True)
        tmp_calls_dir = Path("/tmp/callforge_calls")
        tmp_calls_dir.mkdir(parents=True, exist_ok=True)

        cid_file = calls_dir / f"{call_uuid}.callerid"
        try:
            cid_file.write_text(phone, encoding="utf-8")
        except Exception as e:
            logger.debug("Writing callerid file failed: %s", e)

        meta_file = calls_dir / f"{call_uuid}.campaign"
        meta_file_tmp = tmp_calls_dir / f"{call_uuid}.campaign"
        meta_data = {
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "contact_id": contact.id,
            "contact_name": contact.name,
            "phone": phone,
            "greeting_text": campaign.greeting_text,
            "collect_fields": campaign.collect_fields,
        }
        meta_json = json.dumps(meta_data)
        try:
            meta_file.write_text(meta_json, encoding="utf-8")
            meta_file_tmp.write_text(meta_json, encoding="utf-8")
        except Exception as e:
            logger.debug("Writing campaign meta file failed: %s", e)

        # Originate call via Asterisk AMI
        res = await originate_call_ami(
            channel=channel,
            exten=agent.extension,
            context="from-internal",
            priority=1,
            caller_id=caller_id,
            variables={
                "CALL_UUID": call_uuid,
                "CAMPAIGN_ID": campaign.id,
                "CONTACT_ID": contact.id,
            },
            timeout_ms=30000,
            async_originate=False,
        )

        if not res.get("success"):
            # Call failed to connect (busy, no answer, rejected, or error)
            err = res.get("error", "Call not answered")
            logger.info("Campaign call for %s failed to connect: %s", phone, err)
            self._store.update_contact_status(
                contact.id,
                status="failed",
                call_uuid=call_uuid,
                disposition="No Answer / Busy",
                duration_s=0.0,
            )
            try:
                cid_file.unlink(missing_ok=True)
                meta_file.unlink(missing_ok=True)
                meta_file_tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return

        # Call was answered and bridged to AudioSocket!
        logger.info("Campaign call for %s answered and connected! Waiting for call completion...", phone)

        # Wait until the active call finishes in AudioSocket / VoicePipeline
        start_wait = asyncio.get_running_loop().time()
        max_duration_s = 600.0  # 10 minutes maximum duration limit
        while True:
            await asyncio.sleep(1.5)
            cur_contact = self._store.get_campaign_contact(contact.id)
            if not cur_contact or cur_contact.status in ("completed", "failed"):
                break
            if asyncio.get_running_loop().time() - start_wait > max_duration_s:
                logger.warning("Campaign call for %s reached max duration timeout", phone)
                break

        try:
            cid_file.unlink(missing_ok=True)
            meta_file.unlink(missing_ok=True)
            meta_file_tmp.unlink(missing_ok=True)
        except Exception:
            pass
