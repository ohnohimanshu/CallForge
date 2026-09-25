"""SQLite-backed store for agents, documents, and call history."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from callforge.store.models import (
    AgentRecord,
    CallRecord,
    CallTurnRecord,
    CallerProfileRecord,
    CampaignContactRecord,
    CampaignRecord,
    DocumentRecord,
    UserRecord,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    extension TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL DEFAULT 'auto',
    llm_model TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    greeting_text TEXT NOT NULL,
    voice_en TEXT NOT NULL,
    voice_hi TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    port INTEGER,
    phone_number TEXT NOT NULL DEFAULT '',
    phone_number_status TEXT NOT NULL DEFAULT 'none',
    phone_number_price REAL NOT NULL DEFAULT 4.99,
    phone_number_country TEXT NOT NULL DEFAULT 'US',
    owner_username TEXT NOT NULL DEFAULT 'himanshu',
    handoff_enabled INTEGER NOT NULL DEFAULT 0,
    handoff_extension TEXT NOT NULL DEFAULT '1001',
    handoff_fallback_threshold INTEGER NOT NULL DEFAULT 2,
    handoff_message TEXT NOT NULL DEFAULT 'I am transferring you to a representative now. Please hold on the line.',
    handoff_message_hi TEXT NOT NULL DEFAULT 'मैं आपको हमारे प्रतिनिधि से कनेक्ट कर रहा हूँ। कृपया लाइन पर बने रहें।',
    ab_testing_enabled INTEGER NOT NULL DEFAULT 0,
    ab_variant_b_prompt TEXT NOT NULL DEFAULT '',
    ab_variant_b_greeting TEXT NOT NULL DEFAULT '',
    ab_variant_b_voice_en TEXT NOT NULL DEFAULT 'en_US-amy-medium',
    ab_variant_b_voice_hi TEXT NOT NULL DEFAULT 'hi_IN-priyamvada-medium',
    ab_variant_b_llm_model TEXT NOT NULL DEFAULT '',
    ab_split_ratio INTEGER NOT NULL DEFAULT 50,
    dialogue_policy_enabled INTEGER NOT NULL DEFAULT 0,
    dialogue_slots_json TEXT NOT NULL DEFAULT '[]',
    multilingual_routing INTEGER NOT NULL DEFAULT 1,
    lang_confidence_threshold REAL NOT NULL DEFAULT 0.65,
    fallback_language TEXT NOT NULL DEFAULT 'en',
    supported_languages TEXT NOT NULL DEFAULT 'en,hi',
    tools_enabled INTEGER NOT NULL DEFAULT 0,
    tools_webhook_url TEXT NOT NULL DEFAULT '',
    voice_cloning_enabled INTEGER NOT NULL DEFAULT 0,
    cloned_voice_sample_path TEXT NOT NULL DEFAULT '',
    speculative_generation_enabled INTEGER NOT NULL DEFAULT 1,
    speculative_branch_count INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    call_uuid TEXT NOT NULL,
    caller_id TEXT NOT NULL DEFAULT 'unknown',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    duration_s REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    transcript_preview TEXT NOT NULL DEFAULT '',
    ab_variant TEXT NOT NULL DEFAULT 'A',
    handoff_to TEXT NOT NULL DEFAULT '',
    slots_json TEXT NOT NULL DEFAULT '{}',
    disposition TEXT NOT NULL DEFAULT 'Completed',
    sentiment TEXT NOT NULL DEFAULT 'neutral'
);

CREATE INDEX IF NOT EXISTS idx_calls_agent ON calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at DESC);

CREATE TABLE IF NOT EXISTS call_turns (
    id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    offset_s REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_call ON call_turns(call_id);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'draft',
    concurrency_limit INTEGER NOT NULL DEFAULT 1,
    caller_id TEXT NOT NULL DEFAULT 'Outbound AI',
    greeting_text TEXT NOT NULL DEFAULT '',
    collect_fields TEXT NOT NULL DEFAULT '',
    total_contacts INTEGER NOT NULL DEFAULT 0,
    completed_contacts INTEGER NOT NULL DEFAULT 0,
    successful_contacts INTEGER NOT NULL DEFAULT 0,
    failed_contacts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_campaigns_agent ON campaigns(agent_id);

CREATE TABLE IF NOT EXISTS campaign_contacts (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    phone TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    custom_variables_json TEXT NOT NULL DEFAULT '{}',
    collected_data_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    call_uuid TEXT NOT NULL DEFAULT '',
    call_id TEXT NOT NULL DEFAULT '',
    disposition TEXT NOT NULL DEFAULT '',
    duration_s REAL NOT NULL DEFAULT 0,
    last_attempt_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contacts_campaign ON campaign_contacts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON campaign_contacts(campaign_id, status);

CREATE TABLE IF NOT EXISTS caller_profiles (
    phone_number TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    call_count INTEGER NOT NULL DEFAULT 1,
    last_call_at TEXT NOT NULL,
    last_disposition TEXT NOT NULL DEFAULT 'Completed',
    last_sentiment TEXT NOT NULL DEFAULT 'neutral',
    sentiment_history_json TEXT NOT NULL DEFAULT '[]',
    past_summaries_json TEXT NOT NULL DEFAULT '[]',
    last_summary TEXT NOT NULL DEFAULT '',
    entities_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_caller_profiles_updated ON caller_profiles(updated_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlatformStore:
    """Thread-safe SQLite store. Cheap, zero-ops, fine for single-host deploy."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(_SCHEMA)
            self._migrate_schema(cur)

    def _migrate_schema(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(agents)")
        agent_cols = {r["name"] for r in cur.fetchall()}
        agent_migrations = [
            ("handoff_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("handoff_extension", "TEXT NOT NULL DEFAULT '1001'"),
            ("handoff_fallback_threshold", "INTEGER NOT NULL DEFAULT 2"),
            ("handoff_message", "TEXT NOT NULL DEFAULT 'I am transferring you to a representative now. Please hold on the line.'"),
            ("handoff_message_hi", "TEXT NOT NULL DEFAULT 'मैं आपको हमारे प्रतिनिधि से कनेक्ट कर रहा हूँ। कृपया लाइन पर बने रहें।'"),
            ("ab_testing_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("ab_variant_b_prompt", "TEXT NOT NULL DEFAULT ''"),
            ("ab_variant_b_greeting", "TEXT NOT NULL DEFAULT ''"),
            ("ab_variant_b_voice_en", "TEXT NOT NULL DEFAULT 'en_US-amy-medium'"),
            ("ab_variant_b_voice_hi", "TEXT NOT NULL DEFAULT 'hi_IN-priyamvada-medium'"),
            ("ab_variant_b_llm_model", "TEXT NOT NULL DEFAULT ''"),
            ("ab_split_ratio", "INTEGER NOT NULL DEFAULT 50"),
            ("dialogue_policy_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("dialogue_slots_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("multilingual_routing", "INTEGER NOT NULL DEFAULT 1"),
            ("lang_confidence_threshold", "REAL NOT NULL DEFAULT 0.65"),
            ("fallback_language", "TEXT NOT NULL DEFAULT 'en'"),
            ("supported_languages", "TEXT NOT NULL DEFAULT 'en,hi'"),
            ("tools_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("tools_webhook_url", "TEXT NOT NULL DEFAULT ''"),
            ("voice_cloning_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("cloned_voice_sample_path", "TEXT NOT NULL DEFAULT ''"),
            ("speculative_generation_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ("speculative_branch_count", "INTEGER NOT NULL DEFAULT 3"),
            ("phone_number", "TEXT NOT NULL DEFAULT ''"),
            ("phone_number_status", "TEXT NOT NULL DEFAULT 'none'"),
            ("phone_number_price", "REAL NOT NULL DEFAULT 4.99"),
            ("phone_number_country", "TEXT NOT NULL DEFAULT 'US'"),
            ("owner_username", "TEXT NOT NULL DEFAULT 'himanshu'"),
        ]
        for col_name, col_type in agent_migrations:
            if col_name not in agent_cols:
                cur.execute(f"ALTER TABLE agents ADD COLUMN {col_name} {col_type}")

        cur.execute("PRAGMA table_info(calls)")
        call_cols = {r["name"] for r in cur.fetchall()}
        call_migrations = [
            ("ab_variant", "TEXT NOT NULL DEFAULT 'A'"),
            ("handoff_to", "TEXT NOT NULL DEFAULT ''"),
            ("slots_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("disposition", "TEXT NOT NULL DEFAULT 'Completed'"),
            ("sentiment", "TEXT NOT NULL DEFAULT 'neutral'"),
        ]
        for col_name, col_type in call_migrations:
            if col_name not in call_cols:
                cur.execute(f"ALTER TABLE calls ADD COLUMN {col_name} {col_type}")

        cur.execute("PRAGMA table_info(call_turns)")
        turn_cols = {r["name"] for r in cur.fetchall()}
        if "offset_s" not in turn_cols:
            cur.execute("ALTER TABLE call_turns ADD COLUMN offset_s REAL NOT NULL DEFAULT 0.0")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS caller_profiles (
                phone_number TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                call_count INTEGER NOT NULL DEFAULT 1,
                last_call_at TEXT NOT NULL,
                last_disposition TEXT NOT NULL DEFAULT 'Completed',
                last_sentiment TEXT NOT NULL DEFAULT 'neutral',
                sentiment_history_json TEXT NOT NULL DEFAULT '[]',
                past_summaries_json TEXT NOT NULL DEFAULT '[]',
                last_summary TEXT NOT NULL DEFAULT '',
                entities_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_caller_profiles_updated ON caller_profiles(updated_at DESC)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

        # Campaign migrations
        cur.execute("PRAGMA table_info(campaigns)")
        camp_cols = {r["name"] for r in cur.fetchall()}
        camp_migrations = [
            ("greeting_text", "TEXT NOT NULL DEFAULT ''"),
            ("collect_fields", "TEXT NOT NULL DEFAULT ''"),
        ]
        for col_name, col_type in camp_migrations:
            if col_name not in camp_cols:
                cur.execute(f"ALTER TABLE campaigns ADD COLUMN {col_name} {col_type}")

        cur.execute("PRAGMA table_info(campaign_contacts)")
        contact_cols = {r["name"] for r in cur.fetchall()}
        if "collected_data_json" not in contact_cols:
            cur.execute("ALTER TABLE campaign_contacts ADD COLUMN collected_data_json TEXT NOT NULL DEFAULT '{}'")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_call_uuid ON campaign_contacts(call_uuid)")

        # Seed default user: himanshu / himanshu@1234
        cur.execute("SELECT id FROM users WHERE username='himanshu'")
        if not cur.fetchone():
            import hashlib
            h = hashlib.sha256(b"himanshu@1234").hexdigest()
            cur.execute(
                "INSERT INTO users (id, username, password_hash, full_name, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "himanshu", h, "Himanshu", _utcnow()),
            )

        # Ensure all existing agents are owned by 'himanshu'
        cur.execute("UPDATE agents SET owner_username='himanshu' WHERE owner_username IS NULL OR owner_username=''")

    # --- Agents -------------------------------------------------------------

    def create_agent(self, **kwargs) -> AgentRecord:
        now = _utcnow()
        agent = AgentRecord(
            id=kwargs.get("id") or str(uuid.uuid4()),
            name=kwargs["name"],
            description=kwargs.get("description", ""),
            extension=str(kwargs.get("extension", "2000")),
            language=kwargs.get("language", "auto"),
            llm_model=kwargs.get("llm_model", "llama3.2:3b-instruct-q4_K_M"),
            system_prompt=kwargs.get("system_prompt", AgentRecord.__dataclass_fields__["system_prompt"].default),
            greeting_text=kwargs.get("greeting_text", AgentRecord.__dataclass_fields__["greeting_text"].default),
            voice_en=kwargs.get("voice_en", "en_US-amy-medium"),
            voice_hi=kwargs.get("voice_hi", "hi_IN-priyamvada-medium"),
            status="draft",
            port=None,
            phone_number=kwargs.get("phone_number") or None,
            phone_number_status=kwargs.get("phone_number_status", "none"),
            phone_number_price=float(kwargs.get("phone_number_price", 4.99)),
            phone_number_country=str(kwargs.get("phone_number_country", "US")),
            owner_username=str(kwargs.get("owner_username") or "himanshu"),
            handoff_enabled=bool(kwargs.get("handoff_enabled", False)),
            handoff_extension=str(kwargs.get("handoff_extension", "1001")),
            handoff_fallback_threshold=int(kwargs.get("handoff_fallback_threshold", 2)),
            handoff_message=kwargs.get("handoff_message", "I am transferring you to a representative now. Please hold on the line."),
            handoff_message_hi=kwargs.get("handoff_message_hi", "मैं आपको हमारे प्रतिनिधि से कनेक्ट कर रहा हूँ। कृपया लाइन पर बने रहें।"),
            ab_testing_enabled=bool(kwargs.get("ab_testing_enabled", False)),
            ab_variant_b_prompt=kwargs.get("ab_variant_b_prompt", ""),
            ab_variant_b_greeting=kwargs.get("ab_variant_b_greeting", ""),
            ab_variant_b_voice_en=kwargs.get("ab_variant_b_voice_en", "en_US-amy-medium"),
            ab_variant_b_voice_hi=kwargs.get("ab_variant_b_voice_hi", "hi_IN-priyamvada-medium"),
            ab_variant_b_llm_model=kwargs.get("ab_variant_b_llm_model", ""),
            ab_split_ratio=int(kwargs.get("ab_split_ratio", 50)),
            dialogue_policy_enabled=bool(kwargs.get("dialogue_policy_enabled", False)),
            dialogue_slots_json=kwargs.get("dialogue_slots_json", "[]"),
            multilingual_routing=bool(kwargs.get("multilingual_routing", True)),
            lang_confidence_threshold=float(kwargs.get("lang_confidence_threshold", 0.65)),
            fallback_language=kwargs.get("fallback_language", "en"),
            supported_languages=kwargs.get("supported_languages", "en,hi"),
            tools_enabled=bool(kwargs.get("tools_enabled", False)),
            tools_webhook_url=str(kwargs.get("tools_webhook_url") or ""),
            voice_cloning_enabled=bool(kwargs.get("voice_cloning_enabled", False)),
            cloned_voice_sample_path=str(kwargs.get("cloned_voice_sample_path") or ""),
            speculative_generation_enabled=bool(kwargs.get("speculative_generation_enabled", True)),
            speculative_branch_count=int(kwargs.get("speculative_branch_count", 3)),
            created_at=now,
            updated_at=now,
        )
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO agents
                   (id, name, description, extension, language, llm_model, system_prompt,
                    greeting_text, voice_en, voice_hi, status, port,
                    phone_number, phone_number_status, phone_number_price, phone_number_country, owner_username,
                    handoff_enabled, handoff_extension, handoff_fallback_threshold, handoff_message, handoff_message_hi,
                    ab_testing_enabled, ab_variant_b_prompt, ab_variant_b_greeting, ab_variant_b_voice_en, ab_variant_b_voice_hi, ab_variant_b_llm_model, ab_split_ratio,
                    dialogue_policy_enabled, dialogue_slots_json, multilingual_routing, lang_confidence_threshold, fallback_language, supported_languages,
                    tools_enabled, tools_webhook_url,
                    voice_cloning_enabled, cloned_voice_sample_path, speculative_generation_enabled, speculative_branch_count,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    agent.id, agent.name, agent.description, agent.extension, agent.language,
                    agent.llm_model, agent.system_prompt, agent.greeting_text, agent.voice_en,
                    agent.voice_hi, agent.status, agent.port,
                    agent.phone_number or "", agent.phone_number_status, agent.phone_number_price, agent.phone_number_country, agent.owner_username,
                    1 if agent.handoff_enabled else 0, agent.handoff_extension, agent.handoff_fallback_threshold, agent.handoff_message, agent.handoff_message_hi,
                    1 if agent.ab_testing_enabled else 0, agent.ab_variant_b_prompt, agent.ab_variant_b_greeting, agent.ab_variant_b_voice_en, agent.ab_variant_b_voice_hi, agent.ab_variant_b_llm_model, agent.ab_split_ratio,
                    1 if agent.dialogue_policy_enabled else 0, agent.dialogue_slots_json, 1 if agent.multilingual_routing else 0, agent.lang_confidence_threshold, agent.fallback_language, agent.supported_languages,
                    1 if agent.tools_enabled else 0, agent.tools_webhook_url,
                    1 if agent.voice_cloning_enabled else 0, agent.cloned_voice_sample_path, 1 if agent.speculative_generation_enabled else 0, agent.speculative_branch_count,
                    agent.created_at, agent.updated_at,
                ),
            )
        return agent

    def list_agents(self, owner_username: Optional[str] = None) -> list[AgentRecord]:
        with self._cursor() as cur:
            if owner_username:
                rows = cur.execute(
                    "SELECT * FROM agents WHERE owner_username=? ORDER BY created_at DESC",
                    (owner_username,),
                ).fetchall()
            else:
                rows = cur.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
        return [self._row_to_agent(r) for r in rows]

    # --- Users & Auth -------------------------------------------------------

    def create_user(self, username: str, password: str, full_name: str = "") -> UserRecord:
        import hashlib
        uname = username.strip().lower()
        if not uname:
            raise ValueError("Username is required")
        if not password:
            raise ValueError("Password is required")

        with self._cursor() as cur:
            existing = cur.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
            if existing:
                raise ValueError(f"Username '{uname}' is already taken")

            user_id = str(uuid.uuid4())
            password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
            now = _utcnow()
            cur.execute(
                "INSERT INTO users (id, username, password_hash, full_name, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, uname, password_hash, full_name.strip(), now),
            )
            return UserRecord(
                id=user_id,
                username=uname,
                password_hash=password_hash,
                full_name=full_name.strip(),
                created_at=now,
            )

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        uname = username.strip().lower()
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
            if not row:
                return None
            return UserRecord(
                id=row["id"],
                username=row["username"],
                password_hash=row["password_hash"],
                full_name=row["full_name"],
                created_at=row["created_at"],
            )

    def verify_user(self, username: str, password: str) -> Optional[UserRecord]:
        import hashlib
        user = self.get_user_by_username(username)
        if not user:
            return None
        candidate_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if user.password_hash == candidate_hash:
            return user
        return None

    def get_agent(self, agent_id: str) -> Optional[AgentRecord]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        return self._row_to_agent(row) if row else None

    def get_agent_by_extension(self, extension: str) -> Optional[AgentRecord]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM agents WHERE extension=?", (extension,)).fetchone()
        return self._row_to_agent(row) if row else None

    def update_agent(self, agent_id: str, **fields) -> Optional[AgentRecord]:
        allowed = {
            "name", "description", "extension", "language", "llm_model", "system_prompt",
            "greeting_text", "voice_en", "voice_hi", "status", "port",
            "handoff_enabled", "handoff_extension", "handoff_fallback_threshold",
            "handoff_message", "handoff_message_hi",
            "ab_testing_enabled", "ab_variant_b_prompt", "ab_variant_b_greeting",
            "ab_variant_b_voice_en", "ab_variant_b_voice_hi", "ab_variant_b_llm_model", "ab_split_ratio",
            "dialogue_policy_enabled", "dialogue_slots_json",
            "multilingual_routing", "lang_confidence_threshold", "fallback_language", "supported_languages",
            "tools_enabled", "tools_webhook_url",
            "voice_cloning_enabled", "cloned_voice_sample_path",
            "speculative_generation_enabled", "speculative_branch_count",
            "phone_number", "phone_number_status", "phone_number_price", "phone_number_country",
            "owner_username",
        }
        updates = {}
        for k, v in fields.items():
            if k in allowed and v is not None:
                if isinstance(v, bool):
                    updates[k] = 1 if v else 0
                else:
                    updates[k] = v
        if not updates:
            return self.get_agent(agent_id)
        updates["updated_at"] = _utcnow()
        cols = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [agent_id]
        with self._cursor() as cur:
            cur.execute(f"UPDATE agents SET {cols} WHERE id=?", vals)
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM agents WHERE id=?", (agent_id,))
            return cur.rowcount > 0

    def list_deployed_agents(self) -> list[AgentRecord]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM agents WHERE status='deployed' AND port IS NOT NULL ORDER BY port"
            ).fetchall()
        return [self._row_to_agent(r) for r in rows]

    def get_agent_by_phone_number(self, phone_number: str) -> Optional[AgentRecord]:
        clean = phone_number.strip().lstrip("+")
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM agents WHERE phone_number=? OR phone_number=? OR phone_number LIKE ?",
                (phone_number, f"+{clean}", f"%{clean}"),
            ).fetchone()
        return self._row_to_agent(row) if row else None

    def allocate_port(self, base_port: int = 9092) -> int:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT port FROM agents WHERE port IS NOT NULL ORDER BY port"
            ).fetchall()
        used = {r["port"] for r in rows}
        port = base_port
        while port in used:
            port += 1
        return port

    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> AgentRecord:
        keys = row.keys()
        return AgentRecord(
            id=row["id"], name=row["name"], description=row["description"],
            extension=row["extension"], language=row["language"], llm_model=row["llm_model"],
            system_prompt=row["system_prompt"], greeting_text=row["greeting_text"],
            voice_en=row["voice_en"], voice_hi=row["voice_hi"], status=row["status"],
            port=row["port"],
            phone_number=row["phone_number"] if ("phone_number" in keys and row["phone_number"]) else None,
            phone_number_status=row["phone_number_status"] if "phone_number_status" in keys else "none",
            phone_number_price=float(row["phone_number_price"]) if "phone_number_price" in keys else 4.99,
            phone_number_country=row["phone_number_country"] if "phone_number_country" in keys else "US",
            handoff_enabled=bool(row["handoff_enabled"]) if "handoff_enabled" in keys else False,
            handoff_extension=row["handoff_extension"] if "handoff_extension" in keys else "1001",
            handoff_fallback_threshold=row["handoff_fallback_threshold"] if "handoff_fallback_threshold" in keys else 2,
            handoff_message=row["handoff_message"] if "handoff_message" in keys else "I am transferring you to a representative now. Please hold on the line.",
            handoff_message_hi=row["handoff_message_hi"] if "handoff_message_hi" in keys else "मैं आपको हमारे प्रतिनिधि से कनेक्ट कर रहा हूँ। कृपया लाइन पर बने रहें।",
            ab_testing_enabled=bool(row["ab_testing_enabled"]) if "ab_testing_enabled" in keys else False,
            ab_variant_b_prompt=row["ab_variant_b_prompt"] if "ab_variant_b_prompt" in keys else "",
            ab_variant_b_greeting=row["ab_variant_b_greeting"] if "ab_variant_b_greeting" in keys else "",
            ab_variant_b_voice_en=row["ab_variant_b_voice_en"] if "ab_variant_b_voice_en" in keys else "en_US-amy-medium",
            ab_variant_b_voice_hi=row["ab_variant_b_voice_hi"] if "ab_variant_b_voice_hi" in keys else "hi_IN-priyamvada-medium",
            ab_variant_b_llm_model=row["ab_variant_b_llm_model"] if "ab_variant_b_llm_model" in keys else "",
            ab_split_ratio=row["ab_split_ratio"] if "ab_split_ratio" in keys else 50,
            dialogue_policy_enabled=bool(row["dialogue_policy_enabled"]) if "dialogue_policy_enabled" in keys else False,
            dialogue_slots_json=row["dialogue_slots_json"] if "dialogue_slots_json" in keys else "[]",
            multilingual_routing=bool(row["multilingual_routing"]) if "multilingual_routing" in keys else True,
            lang_confidence_threshold=row["lang_confidence_threshold"] if "lang_confidence_threshold" in keys else 0.65,
            fallback_language=row["fallback_language"] if "fallback_language" in keys else "en",
            supported_languages=row["supported_languages"] if "supported_languages" in keys else "en,hi",
            tools_enabled=bool(row["tools_enabled"]) if "tools_enabled" in keys else False,
            tools_webhook_url=row["tools_webhook_url"] if "tools_webhook_url" in keys else "",
            voice_cloning_enabled=bool(row["voice_cloning_enabled"]) if "voice_cloning_enabled" in keys else False,
            cloned_voice_sample_path=row["cloned_voice_sample_path"] if "cloned_voice_sample_path" in keys else "",
            speculative_generation_enabled=bool(row["speculative_generation_enabled"]) if "speculative_generation_enabled" in keys else True,
            speculative_branch_count=row["speculative_branch_count"] if "speculative_branch_count" in keys else 3,
            owner_username=row["owner_username"] if "owner_username" in keys else "himanshu",
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    # --- Documents ----------------------------------------------------------

    def add_document(self, agent_id: str, filename: str, stored_path: str) -> DocumentRecord:
        doc = DocumentRecord(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            filename=filename,
            stored_path=stored_path,
            status="pending",
            created_at=_utcnow(),
        )
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO documents
                   (id, agent_id, filename, stored_path, status, chunk_count, error, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (doc.id, doc.agent_id, doc.filename, doc.stored_path, doc.status, 0, "", doc.created_at),
            )
        return doc

    def list_documents(self, agent_id: str) -> list[DocumentRecord]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM documents WHERE agent_id=? ORDER BY created_at DESC", (agent_id,)
            ).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def update_document(self, doc_id: str, **fields) -> Optional[DocumentRecord]:
        allowed = {"status", "chunk_count", "error"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return None
        cols = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [doc_id]
        with self._cursor() as cur:
            cur.execute(f"UPDATE documents SET {cols} WHERE id=?", vals)
            row = cur.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return self._row_to_doc(row) if row else None

    def delete_document(self, doc_id: str) -> Optional[DocumentRecord]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not row:
                return None
            cur.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        return self._row_to_doc(row)

    @staticmethod
    def _row_to_doc(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"], agent_id=row["agent_id"], filename=row["filename"],
            stored_path=row["stored_path"], status=row["status"],
            chunk_count=row["chunk_count"], error=row["error"], created_at=row["created_at"],
        )

    # --- Calls --------------------------------------------------------------

    def start_call(
        self,
        agent_id: str,
        call_uuid: str,
        caller_id: str = "unknown",
        ab_variant: str = "A",
        disposition: str = "Completed",
        sentiment: str = "neutral",
    ) -> CallRecord:
        call = CallRecord(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            call_uuid=call_uuid,
            caller_id=caller_id or "unknown",
            started_at=_utcnow(),
            status="active",
            ab_variant=ab_variant or "A",
            handoff_to="",
            slots_json="{}",
            disposition=disposition or "Completed",
            sentiment=sentiment or "neutral",
        )
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO calls
                   (id, agent_id, call_uuid, caller_id, started_at, ended_at, duration_s, status, transcript_preview, ab_variant, handoff_to, slots_json, disposition, sentiment)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (call.id, call.agent_id, call.call_uuid, call.caller_id, call.started_at, "", 0, "active", "", call.ab_variant, call.handoff_to, call.slots_json, call.disposition, call.sentiment),
            )
        return call

    def end_call(
        self,
        call_id: str,
        status: Optional[str] = "completed",
        disposition: Optional[str] = None,
        sentiment: Optional[str] = None,
    ) -> Optional[CallRecord]:
        ended = _utcnow()
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
            if not row:
                return None
            started = datetime.fromisoformat(row["started_at"])
            duration = (datetime.fromisoformat(ended) - started).total_seconds()
            preview_row = cur.execute(
                "SELECT content FROM call_turns WHERE call_id=? AND role='user' ORDER BY created_at LIMIT 1",
                (call_id,),
            ).fetchone()
            preview = (preview_row["content"][:160] if preview_row else "") or ""
            
            # Preserve transferred status if already set
            keys = row.keys()
            current_status = row["status"]
            final_status = current_status if current_status == "transferred" else (status or "completed")
            final_disp = disposition if disposition is not None else (row["disposition"] if "disposition" in keys else "Completed")
            final_sent = sentiment if sentiment is not None else (row["sentiment"] if "sentiment" in keys else "neutral")

            cur.execute(
                """UPDATE calls
                   SET ended_at=?, duration_s=?, status=?, transcript_preview=?, disposition=?, sentiment=?
                   WHERE id=?""",
                (ended, duration, final_status, preview, final_disp, final_sent, call_id),
            )
            row = cur.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        return self._row_to_call(row) if row else None

    def update_call_slots(self, call_id: str, slots_json: str) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE calls SET slots_json=? WHERE id=?", (slots_json, call_id))

    def update_call_intelligence(self, call_id: str, disposition: str, sentiment: str) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE calls SET disposition=?, sentiment=? WHERE id=?", (disposition, sentiment, call_id))

    def mark_call_handoff(self, call_id: str, handoff_to: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE calls SET status='transferred', handoff_to=?, disposition='Escalated to Human' WHERE id=?",
                (handoff_to, call_id),
            )

    def get_ab_stats(self, agent_id: str) -> dict:
        with self._cursor() as cur:
            rows = cur.execute(
                """SELECT ab_variant, COUNT(*) as count, AVG(duration_s) as avg_duration,
                          SUM(CASE WHEN status='transferred' THEN 1 ELSE 0 END) as handoffs
                   FROM calls WHERE agent_id=? GROUP BY ab_variant""",
                (agent_id,),
            ).fetchall()
        variants = {
            "a": {"count": 0, "avg_duration": 0.0, "handoffs": 0},
            "b": {"count": 0, "avg_duration": 0.0, "handoffs": 0},
        }
        for r in rows:
            v = (r["ab_variant"] or "a").lower()
            variants[v] = {
                "count": r["count"],
                "avg_duration": round(r["avg_duration"] or 0.0, 1),
                "handoffs": r["handoffs"] or 0,
            }
        return variants

    def add_turn(
        self,
        call_id: str,
        role: str,
        content: str,
        language: str = "",
        offset_s: Optional[float] = None,
    ) -> CallTurnRecord:
        now = _utcnow()
        if offset_s is None:
            # Auto-calculate offset from call start
            with self._cursor() as cur:
                row = cur.execute("SELECT started_at FROM calls WHERE id=?", (call_id,)).fetchone()
                if row and row["started_at"]:
                    try:
                        start_dt = datetime.fromisoformat(row["started_at"])
                        now_dt = datetime.fromisoformat(now)
                        offset_s = max(0.0, round((now_dt - start_dt).total_seconds(), 2))
                    except Exception:
                        offset_s = 0.0
                else:
                    offset_s = 0.0

        turn = CallTurnRecord(
            id=str(uuid.uuid4()),
            call_id=call_id,
            role=role,
            content=content,
            language=language,
            offset_s=offset_s or 0.0,
            created_at=now,
        )
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO call_turns (id, call_id, role, content, language, offset_s, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (turn.id, turn.call_id, turn.role, turn.content, turn.language, turn.offset_s, turn.created_at),
            )
        return turn

    def list_calls(
        self,
        agent_id: Optional[str] = None,
        limit: int = 50,
        owner_username: Optional[str] = None,
    ) -> list[CallRecord]:
        with self._cursor() as cur:
            if agent_id:
                if owner_username:
                    rows = cur.execute(
                        """SELECT c.* FROM calls c
                           JOIN agents a ON c.agent_id = a.id
                           WHERE c.agent_id=? AND a.owner_username=?
                           ORDER BY c.started_at DESC LIMIT ?""",
                        (agent_id, owner_username, limit),
                    ).fetchall()
                else:
                    rows = cur.execute(
                        "SELECT * FROM calls WHERE agent_id=? ORDER BY started_at DESC LIMIT ?",
                        (agent_id, limit),
                    ).fetchall()
            elif owner_username:
                rows = cur.execute(
                    """SELECT c.* FROM calls c
                       JOIN agents a ON c.agent_id = a.id
                       WHERE a.owner_username=?
                       ORDER BY c.started_at DESC LIMIT ?""",
                    (owner_username, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM calls ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_call(r) for r in rows]

    def get_call(self, call_id: str) -> Optional[CallRecord]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        return self._row_to_call(row) if row else None

    def get_call_by_uuid(self, call_uuid: str) -> Optional[CallRecord]:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM calls WHERE call_uuid=? ORDER BY started_at DESC LIMIT 1", (call_uuid,)
            ).fetchone()
        return self._row_to_call(row) if row else None

    def list_turns(self, call_id: str) -> list[CallTurnRecord]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM call_turns WHERE call_id=? ORDER BY created_at ASC", (call_id,)
            ).fetchall()
        result = []
        for r in rows:
            keys = r.keys()
            result.append(
                CallTurnRecord(
                    id=r["id"],
                    call_id=r["call_id"],
                    role=r["role"],
                    content=r["content"],
                    language=r["language"],
                    offset_s=float(r["offset_s"]) if "offset_s" in keys and r["offset_s"] is not None else 0.0,
                    created_at=r["created_at"],
                )
            )
        return result

    def stats(self, owner_username: Optional[str] = None) -> dict:
        with self._cursor() as cur:
            if owner_username:
                agents = cur.execute(
                    "SELECT COUNT(*) AS c FROM agents WHERE owner_username=?",
                    (owner_username,),
                ).fetchone()["c"]
                deployed = cur.execute(
                    "SELECT COUNT(*) AS c FROM agents WHERE status='deployed' AND owner_username=?",
                    (owner_username,),
                ).fetchone()["c"]
                calls = cur.execute(
                    """SELECT COUNT(*) AS c FROM calls c
                       JOIN agents a ON c.agent_id = a.id
                       WHERE a.owner_username=?""",
                    (owner_username,),
                ).fetchone()["c"]
                active = cur.execute(
                    """SELECT COUNT(*) AS c FROM calls c
                       JOIN agents a ON c.agent_id = a.id
                       WHERE c.status='active' AND a.owner_username=?""",
                    (owner_username,),
                ).fetchone()["c"]
            else:
                agents = cur.execute("SELECT COUNT(*) AS c FROM agents").fetchone()["c"]
                deployed = cur.execute(
                    "SELECT COUNT(*) AS c FROM agents WHERE status='deployed'"
                ).fetchone()["c"]
                calls = cur.execute("SELECT COUNT(*) AS c FROM calls").fetchone()["c"]
                active = cur.execute(
                    "SELECT COUNT(*) AS c FROM calls WHERE status='active'"
                ).fetchone()["c"]
        return {
            "agents": agents,
            "deployed": deployed,
            "calls": calls,
            "active_calls": active,
        }

    @staticmethod
    def _row_to_call(row: sqlite3.Row) -> CallRecord:
        keys = row.keys()
        return CallRecord(
            id=row["id"], agent_id=row["agent_id"], call_uuid=row["call_uuid"],
            caller_id=row["caller_id"], started_at=row["started_at"],
            ended_at=row["ended_at"], duration_s=row["duration_s"],
            status=row["status"], transcript_preview=row["transcript_preview"],
            ab_variant=row["ab_variant"] if "ab_variant" in keys else "A",
            handoff_to=row["handoff_to"] if "handoff_to" in keys else "",
            slots_json=row["slots_json"] if "slots_json" in keys else "{}",
            disposition=row["disposition"] if "disposition" in keys and row["disposition"] else "Completed",
            sentiment=row["sentiment"] if "sentiment" in keys and row["sentiment"] else "neutral",
        )

    @staticmethod
    def _row_to_campaign(row: sqlite3.Row) -> CampaignRecord:
        keys = row.keys()
        return CampaignRecord(
            id=row["id"],
            name=row["name"],
            agent_id=row["agent_id"],
            status=row["status"],
            concurrency_limit=row["concurrency_limit"] if "concurrency_limit" in keys else 1,
            caller_id=row["caller_id"] if "caller_id" in keys else "Outbound AI",
            greeting_text=row["greeting_text"] if "greeting_text" in keys else "",
            collect_fields=row["collect_fields"] if "collect_fields" in keys else "",
            total_contacts=row["total_contacts"] if "total_contacts" in keys else 0,
            completed_contacts=row["completed_contacts"] if "completed_contacts" in keys else 0,
            successful_contacts=row["successful_contacts"] if "successful_contacts" in keys else 0,
            failed_contacts=row["failed_contacts"] if "failed_contacts" in keys else 0,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_contact(row: sqlite3.Row) -> CampaignContactRecord:
        keys = row.keys()
        return CampaignContactRecord(
            id=row["id"],
            campaign_id=row["campaign_id"],
            phone=row["phone"],
            name=row["name"] if "name" in keys else "",
            custom_variables_json=row["custom_variables_json"] if "custom_variables_json" in keys else "{}",
            collected_data_json=row["collected_data_json"] if "collected_data_json" in keys else "{}",
            status=row["status"],
            attempts=row["attempts"] if "attempts" in keys else 0,
            call_uuid=row["call_uuid"] if "call_uuid" in keys else "",
            call_id=row["call_id"] if "call_id" in keys else "",
            disposition=row["disposition"] if "disposition" in keys else "",
            duration_s=row["duration_s"] if "duration_s" in keys else 0.0,
            last_attempt_at=row["last_attempt_at"] if "last_attempt_at" in keys else "",
            created_at=row["created_at"],
        )

    # --- Campaigns ----------------------------------------------------------

    def create_campaign(
        self,
        name: str,
        agent_id: str,
        concurrency_limit: int = 1,
        caller_id: str = "Outbound AI",
        greeting_text: str = "",
        collect_fields: str = "",
    ) -> CampaignRecord:
        now = _utcnow()
        campaign = CampaignRecord(
            id=str(uuid.uuid4()),
            name=name,
            agent_id=agent_id,
            status="draft",
            concurrency_limit=max(1, min(10, concurrency_limit)),
            caller_id=caller_id or "Outbound AI",
            greeting_text=greeting_text or "",
            collect_fields=collect_fields or "",
            created_at=now,
            updated_at=now,
        )
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO campaigns
                   (id, name, agent_id, status, concurrency_limit, caller_id,
                    greeting_text, collect_fields,
                    total_contacts, completed_contacts, successful_contacts, failed_contacts,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    campaign.id, campaign.name, campaign.agent_id, campaign.status,
                    campaign.concurrency_limit, campaign.caller_id,
                    campaign.greeting_text, campaign.collect_fields,
                    0, 0, 0, 0, campaign.created_at, campaign.updated_at,
                ),
            )
        return campaign

    def get_campaign(self, campaign_id: str) -> Optional[CampaignRecord]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return self._row_to_campaign(row) if row else None

    def list_campaigns(self) -> list[CampaignRecord]:
        with self._cursor() as cur:
            rows = cur.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
        return [self._row_to_campaign(r) for r in rows]

    def update_campaign(self, campaign_id: str, **kwargs) -> Optional[CampaignRecord]:
        now = _utcnow()
        allowed = {
            "name", "agent_id", "status", "concurrency_limit", "caller_id",
            "greeting_text", "collect_fields",
            "total_contacts", "completed_contacts", "successful_contacts", "failed_contacts"
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return self.get_campaign(campaign_id)
        updates["updated_at"] = now
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [campaign_id]
        with self._cursor() as cur:
            cur.execute(f"UPDATE campaigns SET {set_clause} WHERE id=?", values)
            row = cur.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return self._row_to_campaign(row) if row else None

    def delete_campaign(self, campaign_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
            return cur.rowcount > 0

    def add_campaign_contacts(self, campaign_id: str, contacts: list[dict]) -> int:
        now = _utcnow()
        rows_to_insert = []
        for c in contacts:
            phone = str(c.get("phone", "")).strip()
            if not phone:
                continue
            rows_to_insert.append((
                str(uuid.uuid4()),
                campaign_id,
                phone,
                c.get("name", "").strip(),
                c.get("custom_variables_json", "{}"),
                "pending",
                0,
                "",
                "",
                "",
                0.0,
                "",
                now,
            ))
        if not rows_to_insert:
            return 0
        with self._cursor() as cur:
            cur.executemany(
                """INSERT INTO campaign_contacts
                   (id, campaign_id, phone, name, custom_variables_json, status, attempts,
                    call_uuid, call_id, disposition, duration_s, last_attempt_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows_to_insert,
            )
            # Update total_contacts on campaign
            cur.execute(
                """UPDATE campaigns
                   SET total_contacts = (SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=?),
                       updated_at = ?
                   WHERE id = ?""",
                (campaign_id, now, campaign_id),
            )
        return len(rows_to_insert)

    def list_campaign_contacts(
        self, campaign_id: str, limit: int = 100, offset: int = 0, status: Optional[str] = None
    ) -> list[CampaignContactRecord]:
        with self._cursor() as cur:
            if status:
                rows = cur.execute(
                    """SELECT * FROM campaign_contacts
                       WHERE campaign_id=? AND status=?
                       ORDER BY created_at ASC LIMIT ? OFFSET ?""",
                    (campaign_id, status, limit, offset),
                ).fetchall()
            else:
                rows = cur.execute(
                    """SELECT * FROM campaign_contacts
                       WHERE campaign_id=?
                       ORDER BY created_at ASC LIMIT ? OFFSET ?""",
                    (campaign_id, limit, offset),
                ).fetchall()
        return [self._row_to_contact(r) for r in rows]

    def get_pending_contacts(self, campaign_id: str, limit: int = 5) -> list[CampaignContactRecord]:
        with self._cursor() as cur:
            rows = cur.execute(
                """SELECT * FROM campaign_contacts
                   WHERE campaign_id=? AND status='pending'
                   ORDER BY created_at ASC LIMIT ?""",
                (campaign_id, limit),
            ).fetchall()
        return [self._row_to_contact(r) for r in rows]

    def get_campaign_contact_by_call_uuid(self, call_uuid: str) -> Optional[CampaignContactRecord]:
        if not call_uuid:
            return None
        with self._cursor() as cur:
            row = cur.execute(
                """SELECT * FROM campaign_contacts
                   WHERE call_uuid=?
                   ORDER BY created_at DESC LIMIT 1""",
                (call_uuid,),
            ).fetchone()
        return self._row_to_contact(row) if row else None

    def get_campaign_contact(self, contact_id: str) -> Optional[CampaignContactRecord]:
        if not contact_id:
            return None
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM campaign_contacts WHERE id=?", (contact_id,)).fetchone()
        return self._row_to_contact(row) if row else None

    def update_contact_status(
        self,
        contact_id: str,
        status: str,
        call_uuid: str = "",
        call_id: str = "",
        disposition: str = "",
        duration_s: float = 0.0,
        collected_data_json: str = "",
    ) -> None:
        now = _utcnow()
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM campaign_contacts WHERE id=?", (contact_id,)).fetchone()
            if not row:
                return
            attempts = (row["attempts"] or 0) + (1 if status == "dialing" else 0)
            cur.execute(
                """UPDATE campaign_contacts
                   SET status=?, call_uuid=coalesce(nullif(?,''), call_uuid),
                       call_id=coalesce(nullif(?,''), call_id),
                       disposition=coalesce(nullif(?,''), disposition),
                       duration_s=case when ? > 0 then ? else duration_s end,
                       collected_data_json=case when ? != '' then ? else collected_data_json end,
                       attempts=?, last_attempt_at=?, created_at=created_at
                   WHERE id=?""",
                (status, call_uuid, call_id, disposition, duration_s, duration_s, collected_data_json, collected_data_json, attempts, now, contact_id),
            )
            cid = row["campaign_id"]
            # Recalculate campaign progress stats
            cur.execute(
                """UPDATE campaigns
                   SET completed_contacts = (SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND status='completed'),
                       successful_contacts = (SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND status='completed' AND disposition IN ('Lead Captured', 'Information Provided')),
                       failed_contacts = (SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id=? AND status='failed'),
                       updated_at = ?
                   WHERE id = ?""",
                (cid, cid, cid, now, cid),
            )

    def reset_campaign_contacts(self, campaign_id: str) -> None:
        now = _utcnow()
        with self._cursor() as cur:
            cur.execute(
                """UPDATE campaign_contacts
                   SET status='pending', attempts=0, call_uuid='', call_id='', disposition='', duration_s=0.0, collected_data_json='{}'
                   WHERE campaign_id=?""",
                (campaign_id,),
            )
            cur.execute(
                """UPDATE campaigns
                   SET status='draft', completed_contacts=0, successful_contacts=0, failed_contacts=0, updated_at=?
                   WHERE id=?""",
                (now, campaign_id),
            )

    def get_campaign_stats(self, campaign_id: str) -> dict:
        with self._cursor() as cur:
            camp = cur.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not camp:
                return {}
            rows = cur.execute(
                """SELECT status, disposition, COUNT(*) as cnt
                   FROM campaign_contacts WHERE campaign_id=? GROUP BY status, disposition""",
                (campaign_id,),
            ).fetchall()
        status_counts: dict[str, int] = {}
        for r in rows:
            st = r["status"]
            status_counts[st] = status_counts.get(st, 0) + r["cnt"]

        total = camp["total_contacts"]
        completed = camp["completed_contacts"]
        successful = camp["successful_contacts"]
        return {
            "total": total,
            "completed": completed,
            "successful": successful,
            "failed": camp["failed_contacts"],
            "pending": status_counts.get("pending", 0),
            "dialing": status_counts.get("dialing", 0),
            "conversion_rate_pct": round((successful / max(1, completed)) * 100, 1) if completed > 0 else 0.0,
            "progress_pct": round((completed / max(1, total)) * 100, 1) if total > 0 else 0.0,
        }

    # --- Caller Profiles & Cross-Call Memory --------------------------------

    @staticmethod
    def _row_to_caller_profile(row: sqlite3.Row) -> CallerProfileRecord:
        return CallerProfileRecord(
            phone_number=row["phone_number"],
            name=row["name"],
            call_count=row["call_count"],
            last_call_at=row["last_call_at"],
            last_disposition=row["last_disposition"],
            last_sentiment=row["last_sentiment"],
            sentiment_history_json=row["sentiment_history_json"],
            past_summaries_json=row["past_summaries_json"],
            last_summary=row["last_summary"],
            entities_json=row["entities_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_caller_profile(self, phone_number: str) -> Optional[CallerProfileRecord]:
        clean_phone = phone_number.strip()
        if not clean_phone or clean_phone.lower() == "unknown":
            return None
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM caller_profiles WHERE phone_number=?", (clean_phone,)).fetchone()
            if row:
                return self._row_to_caller_profile(row)
        return None

    def upsert_caller_profile(
        self,
        phone_number: str,
        name: Optional[str] = None,
        disposition: Optional[str] = None,
        sentiment: Optional[str] = None,
        summary: Optional[str] = None,
        entities: Optional[dict[str, Any]] = None,
    ) -> Optional[CallerProfileRecord]:
        clean_phone = phone_number.strip()
        if not clean_phone or clean_phone.lower() == "unknown":
            return None

        now = _utcnow()
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM caller_profiles WHERE phone_number=?", (clean_phone,)).fetchone()
            if row:
                existing = self._row_to_caller_profile(row)
                new_call_count = existing.call_count + 1
                new_name = name.strip() if name and name.strip() else existing.name
                new_disp = disposition if disposition is not None else existing.last_disposition
                new_sent = sentiment if sentiment is not None else existing.last_sentiment

                # Append sentiment history
                try:
                    sent_hist = json.loads(existing.sentiment_history_json or "[]")
                except Exception:
                    sent_hist = []
                if sentiment:
                    sent_hist.append(sentiment)
                    if len(sent_hist) > 20:
                        sent_hist = sent_hist[-20:]

                # Append past summaries
                try:
                    summaries = json.loads(existing.past_summaries_json or "[]")
                except Exception:
                    summaries = []
                if summary and summary.strip():
                    summaries.append(summary.strip())
                    if len(summaries) > 15:
                        summaries = summaries[-15:]
                new_summary = summary.strip() if summary and summary.strip() else existing.last_summary

                # Merge entities
                try:
                    existing_entities = json.loads(existing.entities_json or "{}")
                except Exception:
                    existing_entities = {}
                if entities:
                    existing_entities.update(entities)

                cur.execute(
                    """UPDATE caller_profiles
                       SET name=?, call_count=?, last_call_at=?, last_disposition=?, last_sentiment=?,
                           sentiment_history_json=?, past_summaries_json=?, last_summary=?, entities_json=?, updated_at=?
                       WHERE phone_number=?""",
                    (
                        new_name,
                        new_call_count,
                        now,
                        new_disp,
                        new_sent,
                        json.dumps(sent_hist),
                        json.dumps(summaries),
                        new_summary,
                        json.dumps(existing_entities),
                        now,
                        clean_phone,
                    ),
                )
            else:
                new_name = name.strip() if name and name.strip() else ""
                sent_hist = [sentiment] if sentiment else ["neutral"]
                summaries = [summary.strip()] if summary and summary.strip() else []
                new_summary = summary.strip() if summary and summary.strip() else ""
                new_entities = entities or {}

                cur.execute(
                    """INSERT INTO caller_profiles
                       (phone_number, name, call_count, last_call_at, last_disposition, last_sentiment,
                        sentiment_history_json, past_summaries_json, last_summary, entities_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        clean_phone,
                        new_name,
                        1,
                        now,
                        disposition or "Completed",
                        sentiment or "neutral",
                        json.dumps(sent_hist),
                        json.dumps(summaries),
                        new_summary,
                        json.dumps(new_entities),
                        now,
                        now,
                    ),
                )

            updated_row = cur.execute("SELECT * FROM caller_profiles WHERE phone_number=?", (clean_phone,)).fetchone()
            return self._row_to_caller_profile(updated_row) if updated_row else None

    def list_caller_profiles(self, limit: int = 50) -> list[CallerProfileRecord]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM caller_profiles ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_caller_profile(r) for r in rows]

    def delete_caller_profile(self, phone_number: str) -> bool:
        clean_phone = phone_number.strip()
        with self._cursor() as cur:
            cur.execute("DELETE FROM caller_profiles WHERE phone_number=?", (clean_phone,))
            return cur.rowcount > 0
