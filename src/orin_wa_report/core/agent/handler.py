"""
handler.py

Conversation handler, session manager and sqlite session DB for WhatsApp bot.

Drop this file into: ./src/orin_wa_report/core/agent/handler.py

What it provides
- chat_response(msg, client, history): async function that handles incoming conversation messages
  (creates/updates session, stores message, generates a placeholder reply based on history, sends the reply
   and stores the bot reply in DB).
- register_conv_handler(bot): convenience function to register the r"^conv" handler on your ChatBotHandler
- handler_verify_wa(...) : a small placeholder kept to preserve existing import from main.py. Replace with your
  real verification logic if you have one.

DB location (auto-created): ./src/orin_wa_report/core/database/chat_sessions.db

Design notes
- sessions table: one row per session (session = conversation between bot and single phone) -- scalable. 
- messages table: one row per chat bubble (user or bot), linked to sessions by session_id.
- Session lifecycle: session starts on first user message, inactivity end after 15 minutes (with 5-min warning at 10m),
  forced end after 2 hours (with 5-min warning at 1h55m). Both warnings are sent to the user. 

This file tries to avoid external dependencies (uses builtin sqlite3). It serializes DB operations using a small
asyncio.Lock + run_in_executor to avoid blocking the event loop.

If you want a production setup: migrate to Postgres+async driver or a dedicated session service; for contextual
responses integrate a small LLM or vector DB using the messages history.

"""

import json
import asyncio
import os
import sqlite3
import time
import uuid
import json
import re
import httpx
import copy
import random
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from openai import OpenAI
            
from src.orin_wa_report.core.openwa import WAError
            
from src.orin_wa_report.core.agent.llm import (
    get_question_class,
    chat_filter,
    split_messages,
)
from src.orin_wa_report.core.agent.config import question_class_details

from src.orin_wa_report.core.utils import get_db_query_endpoint
from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__, service="Agent")

from dotenv import load_dotenv
load_dotenv(override=True)


db_api_key = os.getenv("ORIN_DB_API_KEY")
APP_STAGE = os.getenv("APP_STAGE", "development")
BOT_PHONE_NUMBER = os.getenv("BOT_PHONE_NUMBER", "")

ORINAI_CHAT_ENDPOINT = os.getenv("ORINAI_CHAT_ENDPOINT")



db_query_url = get_db_query_endpoint(name=APP_STAGE)

# -----------------------------
# Development Configuration
# -----------------------------
    
USE_SENDER_PHONE_MAPPING = True
USE_RECEIVER_PHONE_MAPPING = False

## Key is the actual sender of message, value is the agent will assume
## the sender is the value phone number
SENDER_PHONE_MAPPING = {
    # "12816215965755@lid": "6281333370000@c.us"
    # "6285850434383@c.us": "6281333370000@c.us"   # Pak Ali
    "6285850434383@c.us": "628175006300@c.us"   # PT Bumimas Cargo Express
}

## Key is the message receiver from the bot, value is where the message ended up
## being sent to, key '*' to map all receiver

## Pina as receiver
# RECEIVER_PHONE_MAPPING = {
#     "log": True,
#     "*": "229037905572043@lid",
# }

## Jemmy as receiver
RECEIVER_PHONE_MAPPING = {
    "log": False,
    "*": {
        "phone": "6285850434383@c.us",
        "lid": "12816215965755@lid"
    },
}

# if APP_STAGE == "production":
#     USE_SENDER_PHONE_MAPPING = False
#     USE_RECEIVER_PHONE_MAPPING = False

# -----------------------------
# Configuration / constants
# -----------------------------
CORE_DIR = Path(__file__).resolve().parents[1]  # core/
DB_DIR = CORE_DIR / "database"
DB_PATH = DB_DIR / "chat_sessions.db"
INACTIVITY_WARNING_SECONDS = 10 * 60  # 10 minutes
INACTIVITY_END_SECONDS = 15 * 60  # 15 minutes
FORCED_SESSION_SECONDS = 1 * 60 * 60  # 1 hour
FORCED_WARNING_BEFORE = 5 * 60  # 5 minutes

USE_END_SESSION_MESSAGE = False
INACTIVITY_END_SESSION_MESSAGE = "Terima kasih telah menghubungi ORIN AI Chat. Jika Anda butuh bantuan di lain waktu, silakan chat kembali."
FORCED_END_SESSION_MESSAGE = "Terima kasih telah menghubungi ORIN AI Chat. Jika Anda butuh bantuan di lain waktu, silakan chat kembali."
END_SESSION_MESSAGE = "Terima kasih telah menghubungi ORIN AI Chat. Jika Anda butuh bantuan di lain waktu, silakan chat kembali."

USE_WARNING_SESSION_MESSAGE = False
INACTIVITY_WARNING_SESSION_MESSAGE = "Sesi chat akan diakhiri dalam 5 menit karena ketidakaktifan. Balas pesan untuk melanjutkan sesi ini."
FORCED_WARNING_SESSION_MESSAGE = "Sesi chat akan diakhiri dalam 5 menit karena akan melalui batas wajar sesi."

USE_WAITING_MESSAGE = False
WAITING_MESSAGE = "Tunggu sebentar, ORIN AI sedang memproses balasan kamu"

USE_ERROR_MESSAGE = False
ERROR_MESSAGE = "Mohon maaf kami belum dapat menjawab pertanyaan Anda."

IS_SINGLE_OUTPUT = True  # The chat output is either report only or reply only

# -----------------------------
# Lightweight sqlite wrapper
# -----------------------------

class ChatDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_done = False
        self.valid_config_keys = {"disable_agent"}
        # small in-process sqlite is protected by an asyncio lock and run_in_executor for blocking ops
        self._lock = asyncio.Lock()

    async def initialize(self):
        async with self._lock:
            if self._init_done:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # connect
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            
            # Register adapters/converters for boolean values (0/1)
            # This is important for consistency when inserting/retrieving
            # Although sqlite stores BOOL as INTEGER, registering converter/adapter is good practice.
            sqlite3.register_adapter(bool, int)
            # Add a converter for INTEGER to BOOL type, which we'll use in _get_config_row
            def convert_bool(v):
                return bool(int(v))
            
            # safer WAL mode for concurrent readers/writers
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
            await asyncio.get_running_loop().run_in_executor(None, self._create_tables)
            self._init_done = True
            logger.info(f"ChatDB initialized at {self.db_path}")

    def _create_tables(self):
        c = self._conn.cursor()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                phone TEXT NOT NULL,
                user_name TEXT,
                started_at INTEGER NOT NULL,
                last_activity INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                ended_at INTEGER,
                metadata TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone);
            CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity);

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                body TEXT,
                timestamp INTEGER NOT NULL,
                metadata TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON messages(session_id, timestamp);
            
            CREATE TABLE IF NOT EXISTS config (
                id TEXT PRIMARY KEY,
                phone TEXT UNIQUE NOT NULL,
                disable_agent BOOL NOT NULL
            )
            """
        )
        self._conn.commit()
        
    def _create_default_config_row(self, phone: str):
        """Internal helper to create a default config row for a new phone."""
        cur = self._conn.cursor()
        
        # Build the SQL command dynamically based on self.valid_config_keys
        # All valid bool configs are defaulted to False (0)
        columns = ["id", "phone"] + list(self.valid_config_keys)
        placeholders = ["?"] * len(columns)
        
        sql = f"INSERT OR IGNORE INTO config ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        
        default_values = [False] * len(self.valid_config_keys)
        
        # Values: uuid, phone, followed by False (0) for each config key
        values = [uuid.uuid4().hex, phone] + default_values
        
        cur.execute(sql, values)
        # No commit here, as it will be part of a larger transaction or committed by the caller.

    async def _run(self, fn, *args, **kwargs):
        """Run a blocking DB call in executor with lock."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # --- session operations ---
    async def create_session(self, phone: str, user_name: str, started_at: Optional[int] = None) -> str:
        if started_at is None:
            started_at = int(time.time())
        session_id = uuid.uuid4().hex
        def _create():
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO sessions (id, phone, user_name, started_at, last_activity, status) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, phone, user_name, started_at, started_at, 'active')
            )
            
            self._create_default_config_row(phone)
            
            self._conn.commit()
            return session_id
        return await self._run(_create)

    async def update_session_activity(self, session_id: str, last_activity: Optional[int] = None):
        if last_activity is None:
            last_activity = int(time.time())
        def _update():
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE sessions SET last_activity = ? WHERE id = ?",
                (last_activity, session_id)
            )
            self._conn.commit()
        await self._run(_update)

    async def end_session(self, session_id: str, ended_at: Optional[int] = None, status: str = "ended"):
        if ended_at is None:
            ended_at = int(time.time())
        def _end():
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE sessions SET status = ?, ended_at = ? WHERE id = ?",
                (status, ended_at, session_id)
            )
            self._conn.commit()
        await self._run(_end)
        
    async def get_session_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        def _get():
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, phone, user_name, started_at, last_activity, status, ended_at FROM sessions WHERE phone = ? ORDER BY started_at DESC LIMIT 1",
                (phone,)
            )
            row = cur.fetchone()
            if not row:
                return None
            keys = ["id","phone","user_name","started_at","last_activity","status","ended_at"]
            return dict(zip(keys, row))
        return await self._run(_get)

    async def get_sessions_by_phone(self, phone: str, limit: int = None) -> List[Dict[str, Any]]:
        """Get all sessions for a phone number, ordered by started_at ascending"""
        def _get():
            cur = self._conn.cursor()
            cur.execute(
                """
SELECT *
FROM (
  SELECT id, phone, user_name, started_at, last_activity, status, ended_at
  FROM sessions
  WHERE phone = ?
  ORDER BY started_at DESC
  LIMIT ?
) AS latest
ORDER BY started_at ASC;
""",
                (phone, limit)
            )
            rows = cur.fetchall()
            if not rows:
                return []
            keys = ["id","phone","user_name","started_at","last_activity","status","ended_at"]
            return [dict(zip(keys, row)) for row in rows]
        return await self._run(_get)

    async def get_latest_session_by_phone_force(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the ABSOLUTE latest session for a phone number,
        regardless of its status (active, ended, etc.).
        This is a clear implementation of the requested 'force' behavior.
        """
        def _get():
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, phone, user_name, started_at, last_activity, status, ended_at FROM sessions WHERE phone = ? ORDER BY started_at DESC LIMIT 1",
                (phone,)
            )
            row = cur.fetchone()
            if not row:
                return None
            keys = ["id","phone","user_name","started_at","last_activity","status","ended_at"]
            return dict(zip(keys, row))
        return await self._run(_get)

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        def _get():
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, phone, user_name, started_at, last_activity, status, ended_at FROM sessions WHERE id = ?",
                (session_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            keys = ["id","phone","user_name","started_at","last_activity","status","ended_at"]
            return dict(zip(keys, row))
        return await self._run(_get)

    # --- messages ---
    async def add_message(self, session_id: str, sender: str, body: str, timestamp: Optional[int] = None, metadata: Optional[dict] = None) -> str:
        if timestamp is None:
            timestamp = int(time.time())
        if metadata is None:
            metadata = {}
        message_id = uuid.uuid4().hex
        def _add():
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO messages (id, session_id, sender, body, timestamp, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, session_id, sender, body, timestamp, json.dumps(metadata))
            )
            self._conn.commit()
            return message_id
        return await self._run(_add)

    async def add_chat_to_latest_session(self, phone_number: str, sender: str, message: str):
        """
        Adds a message to the latest session associated with the given phone number.
        If no active session is found, it will do nothing (or could optionally raise an error).
        """
        # 1. Get the latest session for the phone number
        session = await self.get_session_by_phone(phone_number)

        if not session:
            # No session found for this phone number, log or handle as needed
            logger.warning(f"Attempted to add chat for phone {phone_number} but no session found.")
            return

        session_id = session["id"]

        # 2. Add the message to the found session
        await self.add_message(
            session_id=session_id,
            sender=sender,
            body=message
        )

        # 3. Update the session's last activity
        await self.update_session_activity(session_id)

    async def get_messages_for_session(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        def _get():
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, sender, body, timestamp, metadata FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit)
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                out.append({
                    "id": r[0],
                    "sender": r[1],
                    "body": r[2],
                    "timestamp": r[3],
                    "metadata": json.loads(r[4]) if r[4] else None
                })
            return out
        return await self._run(_get)
    
    async def get_config(
        self,
        phone: str,
        key: str,
        create_if_not_exists: bool = False
    ) -> Optional[bool]:
        """
        Retrieves a boolean configuration value for a specific phone number.
        Returns None if the phone or key is not found, or if the value is not a boolean.
        """
        # The 'config' table currently only has 'disable_agent' as a config key.
        # We must ensure the 'key' is a valid column name to prevent SQL injection.
        # For this example, we'll hardcode the valid key check.
        # In a real system, you might use a more robust validation or a predefined dict of keys.
        if key not in self.valid_config_keys:
            logger.error("(get_config) The key you requested is not in the table")
            return None

        def _get():
            cur = self._conn.cursor()
            # Note: Using an f-string for the column name 'key' is safe here 
            # because we strictly validated 'key' against 'valid_keys' above.
            cur.execute(
                f"SELECT {key} FROM config WHERE phone = ?",
                (phone,)
            )
            row = cur.fetchone()
            if row:
                # Value found, return it as a boolean
                return bool(row[0])
            elif create_if_not_exists:
                # Value not found, but we need to create it
                self._create_default_config_row(phone)
                self._conn.commit()
                # Since we just created a default row, the value for 'key' is False (0)
                return False
            else:
                return None
        
        return await self._run(_get)
    
    async def update_config(
        self,
        phone: str,
        values: Dict[str, Any],
        create_if_not_exists: bool = False
    ):
        """
        Updates one or more configuration values for a phone number.
        If the phone does not exist and create_if_not_exists is True, it creates a new
        row with the provided values (and False for any missing valid keys).
        The 'values' dict keys must be in self.valid_config_keys.
        """
        
        # 1. Filter out invalid keys from the update dictionary
        update_keys = [k for k in values if k in self.valid_config_keys]
        if not update_keys:
            return # Nothing to update

        def _update():
            cur = self._conn.cursor()
            
            # Check if the phone already has a config row
            cur.execute("SELECT id FROM config WHERE phone = ?", (phone,))
            row_exists = cur.fetchone()

            if not row_exists and create_if_not_exists:
                # 2. Case: Row does not exist, but we should create it
                self._create_default_config_row(phone) # Creates a default row
                # We need to commit here to ensure the subsequent UPDATE finds the row
                self._conn.commit() 
            elif not row_exists:
                # 3. Case: Row does not exist and we are not creating it
                return
            
            # 4. Case: Row exists (or was just created), now perform the update
            # Build the SET part of the SQL query: "key1 = ?, key2 = ?"
            set_clauses = [f"{key} = ?" for key in update_keys]
            sql = f"UPDATE config SET {', '.join(set_clauses)} WHERE phone = ?"
            
            # Extract values in the same order as the keys for the SET clause
            update_values = [values[key] for key in update_keys]
            
            # Append the phone number for the WHERE clause
            params = update_values + [phone]
            
            cur.execute(sql, params)
            self._conn.commit()
        
        await self._run(_update)

    async def close(self):
        """Closes the connection, forcing an immediate checkpoint."""
        async with self._lock:
            if self._conn:
                # Force a checkpoint to merge WAL data into the main DB file
                self._conn.execute("PRAGMA wal_checkpoint(FULL);")
                self._conn.close()
                self._conn = None
                logger.info("SettingsDB connection closed and checkpointed.")

# -----------------------------
# Session manager in memory
# -----------------------------

class SessionEntry:
    def __init__(self, session_id: str, phone: str, jid: str, user_name: str, started_at: int, last_activity: int):
        self.session_id = session_id
        self.phone = phone
        self.jid = jid  # full whatsapp jid '6281...@s.whatsapp.net'
        self.user_name = user_name
        self.started_at = started_at
        self.last_activity = last_activity
        self.inactivity_task: Optional[asyncio.Task] = None
        self.forced_task: Optional[asyncio.Task] = None
        self.processing_lock = asyncio.Lock()


class SessionManager:
    def __init__(self, db: ChatDB):
        self.db = db
        self._sessions: Dict[str, SessionEntry] = {}  # key by phone
        self._lock = asyncio.Lock()

    async def ensure_session(self, phone: str, jid: str, user_name: str, client) -> SessionEntry:
        """Get existing active session for phone or create a new one."""
        now = int(time.time())
        async with self._lock:
            entry = self._sessions.get(phone)
            if entry:
                # verify it's still active in DB
                sess = await self.db.get_session(entry.session_id)
                if sess and sess.get("status") == "active":
                    # update last_activity in db + in-memory
                    await self.db.update_session_activity(entry.session_id, now)
                    entry.last_activity = now
                    # reset inactivity watcher
                    if entry.inactivity_task:
                        entry.inactivity_task.cancel()
                    entry.inactivity_task = asyncio.create_task(self._inactivity_watcher(entry, client))
                    return entry
                else:
                    # stale entry in memory
                    await self._cancel_tasks(entry)
                    self._sessions.pop(phone, None)

            # look in DB for most recent session for this phone
            dbsess = await self.db.get_session_by_phone(phone)
            if dbsess and dbsess.get("status") == "active":
                # check started_at + FORCED_SESSION_SECONDS
                if int(time.time()) - int(dbsess.get("started_at")) < FORCED_SESSION_SECONDS:
                    # reuse
                    entry = SessionEntry(
                        session_id=dbsess["id"],
                        phone=phone,
                        jid=jid,
                        user_name=dbsess.get("user_name") or user_name,
                        started_at=int(dbsess.get("started_at")),
                        last_activity=int(dbsess.get("last_activity"))
                    )
                    # schedule watchers
                    entry.inactivity_task = asyncio.create_task(self._inactivity_watcher(entry, client))
                    entry.forced_task = asyncio.create_task(self._forced_watcher(entry, client))
                    self._sessions[phone] = entry
                    await self.db.update_session_activity(entry.session_id, now)
                    entry.last_activity = now
                    return entry
                else:
                    # session too old - end it in DB and create new
                    try:
                        await self.db.end_session(dbsess["id"], ended_at=int(time.time()), status="ended")
                    except Exception:
                        logger.exception("Failed to mark old session ended")

            # create new session
            session_id = await self.db.create_session(phone, user_name, started_at=now)
            entry = SessionEntry(session_id=session_id, phone=phone, jid=jid, user_name=user_name, started_at=now, last_activity=now)
            entry.inactivity_task = asyncio.create_task(self._inactivity_watcher(entry, client))
            entry.forced_task = asyncio.create_task(self._forced_watcher(entry, client))
            self._sessions[phone] = entry
            logger.info(f"Created new session {session_id} for {phone}")
            return entry

    async def touch_session(self, phone: str, client):
        """Update session last_activity and restart inactivity watcher."""
        async with self._lock:
            entry = self._sessions.get(phone)
            if not entry:
                return None
            now = int(time.time())
            entry.last_activity = now
            try:
                await self.db.update_session_activity(entry.session_id, now)
            except Exception:
                logger.exception("Failed to update session activity")
            if entry.inactivity_task:
                entry.inactivity_task.cancel()
            entry.inactivity_task = asyncio.create_task(self._inactivity_watcher(entry, client))
            return entry

    async def _cancel_tasks(self, entry: SessionEntry):
        if entry.inactivity_task:
            try:
                entry.inactivity_task.cancel()
            except Exception:
                pass
        if entry.forced_task:
            try:
                entry.forced_task.cancel()
            except Exception:
                pass

    async def _inactivity_watcher(self, entry: SessionEntry, client):
        """Sends a 5-min warning at 10 minutes of inactivity then ends the session at 15 minutes if no reply."""
        try:
            # sleep until warning
            await asyncio.sleep(INACTIVITY_WARNING_SECONDS)
            # check actual last_activity
            sess = await self.db.get_session(entry.session_id)
            if not sess or sess.get("status") != "active":
                return
            last_activity = int(sess.get("last_activity"))
            now = int(time.time())
            if now - last_activity < INACTIVITY_WARNING_SECONDS:
                # activity happened - watcher will be restarted by touch_session
                return
            # send warning
            if USE_WARNING_SESSION_MESSAGE:
                warn_text = INACTIVITY_WARNING_SESSION_MESSAGE
                try:
                    client.sendText(entry.jid, warn_text)
                except Exception:
                    logger.exception("Failed to send inactivity warning")
            # wait final 5 minutes
            await asyncio.sleep(INACTIVITY_END_SECONDS - INACTIVITY_WARNING_SECONDS)
            # final check
            sess = await self.db.get_session(entry.session_id)
            if not sess or sess.get("status") != "active":
                return
            last_activity = int(sess.get("last_activity"))
            now = int(time.time())
            if now - last_activity < INACTIVITY_END_SECONDS:
                # user replied in the meantime
                return
            # end session
            logger.info(f"Ending session {entry.session_id} for {entry.phone} due to inactivity")
            if USE_END_SESSION_MESSAGE:
                try:
                    client.sendText(entry.jid, INACTIVITY_END_SESSION_MESSAGE)
                except Exception:
                    logger.exception("Failed to send inactivity final message")
            await self.db.end_session(entry.session_id, ended_at=int(time.time()), status="ended")
            # cleanup
            async with self._lock:
                await self._cancel_tasks(entry)
                self._sessions.pop(entry.phone, None)
        except asyncio.CancelledError:
            # watcher cancelled because of new activity / session end
            return
        except Exception:
            logger.exception("Error in inactivity watcher for session %s", entry.session_id)

    async def _forced_watcher(self, entry: SessionEntry, client):
        """Force-end long sessions after FORCED_SESSION_SECONDS. Send a 5-minute warning beforehand."""
        try:
            total = FORCED_SESSION_SECONDS
            warn_at = total - FORCED_WARNING_BEFORE
            await asyncio.sleep(warn_at)
            # double-check session still active
            sess = await self.db.get_session(entry.session_id)
            if not sess or sess.get("status") != "active":
                return
            if USE_WARNING_SESSION_MESSAGE:
                try:
                    client.sendText(entry.jid, FORCED_WARNING_SESSION_MESSAGE)
                except Exception:
                    logger.exception("Failed to send forced-end warning")
            await asyncio.sleep(FORCED_WARNING_BEFORE)
            # final end
            sess = await self.db.get_session(entry.session_id)
            if not sess or sess.get("status") != "active":
                return
            logger.info(f"Force ending session {entry.session_id} for {entry.phone} due to time limit")
            if USE_END_SESSION_MESSAGE:
                try:
                    client.sendText(entry.jid, FORCED_END_SESSION_MESSAGE)
                except Exception:
                    logger.exception("Failed to send forced final message")
            await self.db.end_session(entry.session_id, ended_at=int(time.time()), status="ended")
            async with self._lock:
                await self._cancel_tasks(entry)
                self._sessions.pop(entry.phone, None)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in forced watcher for session %s", entry.session_id)
            
    async def end_session(self, phone: str, client, reason: str = "ended"):
        """Manually end a user session."""
        async with self._lock:
            entry = self._sessions.get(phone)
            if not entry:
                return False
            try:
                await self.db.end_session(entry.session_id, ended_at=int(time.time()), status=reason)
            except Exception:
                logger.exception("Failed to end session in DB")
                return False
            if USE_END_SESSION_MESSAGE:
                try:
                    client.sendText(entry.jid, END_SESSION_MESSAGE)
                except Exception:
                    logger.exception("Failed to send session end message")
            await self._cancel_tasks(entry)
            self._sessions.pop(phone, None)
            logger.info(f"Session {entry.session_id} for {phone} ended manually with reason: {reason}")
            return True

# -----------------------------
# Module-level singletons
# -----------------------------
_DB: Optional[ChatDB] = None
_SESSION_MANAGER: Optional[SessionManager] = None
_db_init_lock = asyncio.Lock()

async def _ensure_db_and_manager():
    global _DB, _SESSION_MANAGER
    async with _db_init_lock:
        if _DB is None:
            _DB = ChatDB(DB_PATH)
            await _DB.initialize()
            _SESSION_MANAGER = SessionManager(_DB)

# -----------------------------
# Chat response logic
# -----------------------------

GREETINGS = re.compile(r"\b(hi|hello|hai|halo|hey)\b", re.I)
GOODBYES = re.compile(r"\b(bye|goodbye|terima kasih|thanks|thx)\b", re.I)

def markdown_to_whatsapp(text: str) -> str:
    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.*?)\*\*", r"*\1*", text)

    # Italic: _text_ or *text* → _text_
    # (Markdown often uses *italic* as well)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?<!\*)", r"_\1_", text)
    text = re.sub(r"_(.*?)_", r"_\1_", text)

    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.*?)~~", r"~\1~", text)

    # Inline code: `text` → ```text```
    text = re.sub(r"`(.*?)`", r"```\1```", text)

    # Remove Markdown headers (#, ##, ### etc.)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

    return text

async def get_agent_id():
    async with httpx.AsyncClient(timeout=5.0) as httpx_client:
        response = await httpx_client.get(
            f"{ORINAI_CHAT_ENDPOINT}/whatsapp/number"
        )
    response.raise_for_status()
    
    response_json: List[Dict] = response.json()
    
    bot_details = [val for val in response_json if val.get("phone_number") == BOT_PHONE_NUMBER]
    bot_agent_id = bot_details[0].get("agent_id")
    
    logger.info(f"Use Agent ID: {bot_agent_id}")
    
    return bot_agent_id


async def fetch_ai_reply(
    client: httpx.AsyncClient,
    api_token: str,
    llm_messages,
    bot_agent_id: str,
) -> str | None:
    try:
        response = await client.post(
            f"{ORINAI_CHAT_ENDPOINT}/chat_api",
            json={
                "messages": llm_messages,
                "agent_id": bot_agent_id,
                "include_suggested_questions": False,
            },
            headers={
                "Authorization": f"Bearer {api_token}"
            }
        )
        response.raise_for_status()

        logger.info(f"[chat_api] Raw status code: {response.status_code}")
        logger.info(f"[chat_api] Raw response text: {response.text}")

        response_json: Dict = response.json()
        logger.info(f"[chat_api] Parsed JSON: {response_json}")

        response_data = response_json.get("data", {})
        if not response_data or not response_data.get("success"):
            return None

        reply = response_data.get("response")
        if not reply:
            logger.warning(f"[chat_api] Unexpected API response: {response_json}")
            return None

        logger.info(f"[chat_api] ORIN AI Chat Reply: {reply}")
        return reply

    except Exception as exc:
        logger.exception(f"[chat_api] Request failed for token {api_token}: {exc}")
        return None
    
async def fetch_ai_report(
    client: httpx.AsyncClient,
    api_token: str,
    llm_messages,
):
    try:
        response = await client.post(
            f"{ORINAI_CHAT_ENDPOINT}/report_agent",
            json={
                "messages": llm_messages,
            },
            headers={
                "Authorization": f"Bearer {api_token}"
            }
        )
        response.raise_for_status()

        logger.info(f"[report_agent] Raw status code: {response.status_code}")

        response_json: Dict = response.json()

        response_data = response_json.get("data", "")
        if not response_data:
            return None

        return response_data

    except Exception as exc:
        logger.exception(f"[report_agent] Request failed for token {api_token}: {exc}")
        return None
    
async def full_fetch_ai(
    httpx_client: httpx.AsyncClient,
    token: str,
    llm_messages,
    bot_agent_id: int,
    chat_filter_is_report: bool,
    is_single_output: bool = False
):
    """
    Handles AI tasks with optimized execution. 
    Always returns a tuple: (reply_result, report_result)
    """

    # --- SCENARIO 1: Single Output Mode ---
    if is_single_output:
        if chat_filter_is_report:
            # Only run report; skip reply to save resources
            report = await fetch_ai_report(httpx_client, token, llm_messages)
            return None, report
        else:
            # Only run reply; skip report
            reply = await fetch_ai_reply(httpx_client, token, llm_messages, bot_agent_id)
            return reply, None

    # --- SCENARIO 2: Standard/Dual Output Mode ---
    if chat_filter_is_report:
        # Run both concurrently for efficiency
        reply_task = fetch_ai_reply(httpx_client, token, llm_messages, bot_agent_id)
        report_task = fetch_ai_report(httpx_client, token, llm_messages)
        
        # gather returns a list, so we convert or unpack to ensure a tuple
        reply, report = await asyncio.gather(reply_task, report_task)
        return reply, report
    
    # Standard mode but no report requested
    reply = await fetch_ai_reply(httpx_client, token, llm_messages, bot_agent_id)
    return reply, None
    
async def send_text_wrapper(
    client,
    raw_phone_number: str,
    raw_lid_number: str,
    text: str,
):
    if USE_RECEIVER_PHONE_MAPPING:
        default_receiver = RECEIVER_PHONE_MAPPING.get("*")
        mapped_receiver = RECEIVER_PHONE_MAPPING.get(raw_phone_number, default_receiver)
        phone_receiver = mapped_receiver.get("phone")
        lid_receiver = mapped_receiver.get("lid")
        try:
            client.sendText(phone_receiver, text)
        except WAError:
            client.sendText(lid_receiver, text)
    else:
        try:
            client.sendText(raw_phone_number, text)
        except WAError:
            client.sendText(raw_lid_number, text)
            
async def send_file_wrapper(
    client,
    raw_phone_number: str,
    raw_lid_number: str,
    file: str,
    filename: str = "file",
    caption: str = "",
):
    if USE_RECEIVER_PHONE_MAPPING:
        default_receiver = RECEIVER_PHONE_MAPPING.get("*")
        mapped_receiver = RECEIVER_PHONE_MAPPING.get(raw_phone_number, default_receiver)
        phone_receiver = mapped_receiver.get("phone")
        lid_receiver = mapped_receiver.get("lid")
        try:
            client.sendFile(
                phone_receiver, 
                file, 
                filename, 
                caption
            )
        except WAError:
            client.sendFile(
                lid_receiver, 
                file, 
                filename, 
                caption
            )
    else:
        try:
            client.sendFile(
                raw_phone_number, 
                file, 
                filename, 
                caption
            )
        except WAError:
            client.sendFile(
                raw_lid_number, 
                file, 
                filename, 
                caption
            )
            
async def reset_agent_after_delay(phone, delay_seconds: int):
    """Wait for the delay, then set disable_agent back to False."""
    await asyncio.sleep(delay_seconds)
    try:
        await _DB.update_config(
            phone=phone,
            values={"disable_agent": False}
        )
        logger.info(f"Successfully re-enabled agent for {phone} after delay.")
    except Exception:
        logger.exception(f"Failed to reset disable_agent for {phone}")

async def chat_response(
    msg: Dict[str, Any],
    client,
    api_tokens: List[str],
    openai_client: OpenAI,
    history=None
) -> str:
    """
    Main entrypoint to handle a conversational message. This function:
      - ensures DB and session manager exist
      - finds/creates a session for the caller
      - saves the incoming user message to messages table
      - builds a simple reply using session history (placeholder logic)
      - sends the reply via client.sendText and stores the bot reply

    Parameters:
        msg: the incoming message object from wa-automate (same structure as in main.py)
        client: the wa-automate SocketClient instance (used to send replies)
        history: optional, unused (kept for compatibility)

    Returns:
        The reply text that was sent.
    """
    try:
        await _ensure_db_and_manager()
        assert _DB is not None and _SESSION_MANAGER is not None

        # ignore group messages
        if msg.get("data", {}).get("isGroupMsg"):
            return ""

        # Use ['data']['from'] to universally identified number
        phone_jid = msg["data"].get("from")  # This is now a LID
        raw_phone_number = msg["data"]["sender"].get("phoneNumber")
        raw_lid_number = msg["data"]["sender"].get("lid")
        
        
        # phone_jid = msg["data"]["sender"].get("id")
        phone = phone_jid.split("@")[0]
        sender = msg["data"].get("sender", {}) or {}
        user_name = sender.get("pushname", "")
        text = (msg["data"].get("body") or "").strip()
        
        all_replies = []
        reply_error = False
        
        # ensure agent is enabled to reply to this user
        disable_agent = await _DB.get_config(
            phone=phone,
            key="disable_agent",
            create_if_not_exists=True
        )
        logger.info(f"(chat_response) disable_agent config for {phone} is {disable_agent}")
        if disable_agent:
            logger.warning(f"(chat_response) disable_agent is set to True for phone {phone}, agent won't reply")
            return None
    
        # ensure session exists
        entry = await _SESSION_MANAGER.ensure_session(
            phone=phone,
            jid=phone_jid,
            user_name=user_name,
            client=client
        )
        
        # Intro message
        # intro_message = "Kami akan bantu proses ya kak, mohon ditunggu sebentar"
        # client.sendText(phone_jid, intro_message)
        # await _DB.add_message(entry.session_id, sender="bot", body=intro_message)
        
        # Seen/Read the Message
        client.sendSeen(phone_jid)

        # store user message
        try:
            await _DB.add_message(entry.session_id, sender="user", body=text)
        except Exception:
            logger.exception("Failed to store incoming message")
    
        # Check if session is already processing a message
        if entry.processing_lock.locked():
            # Send immediate response without processing
            if USE_WAITING_MESSAGE:
                reply = WAITING_MESSAGE
                try:
                    client.sendText(phone_jid, reply)
                except Exception:
                    logger.exception("Failed to send wait reply to %s", phone_jid)
    
            try:
                await _DB.add_message(entry.session_id, sender="bot", body=reply)
            except Exception:
                logger.exception("Failed to store wait bot message")
    
            # Update session activity
            await _SESSION_MANAGER.touch_session(phone, client)
            return reply
        
        
        # Build a simple context from last user messages
        messages = await _DB.get_messages_for_session(entry.session_id, limit=20)
        
        last_messages = messages[:10]  # Only get 10 last messages for context
        
        last_message = messages[0]
        logger.info(f"Get last message: {last_message}")
        
        # Build LLm messages, reversed because 'messages' is most recent first
        llm_messages = [
            {
                "role": "assistant" if m["sender"] == "bot" else "user",
                "content": m["body"]
            }
            for m in reversed(last_messages)
        ]
        
        # logger.info(f"Get LLM message: {llm_messages[0]}")
        
        
        # Whether Chat is filtered or not (ORIN AI will able to answer or not)
        ## Chat Filter
        chat_filter_dict: Dict = await chat_filter(
            openai_client=openai_client,
            messages=llm_messages
        )
        
        chat_filter_is_processed = chat_filter_dict.get("is_processed")
        chat_filter_is_report = chat_filter_dict.get("is_report")
        chat_filter_is_handover = chat_filter_dict.get("is_handover")
        chat_filter_confidence = chat_filter_dict.get("confidence")
            
        logger.info(f"Chat: {last_message} from {phone_jid} is_processed: {chat_filter_is_processed}, is_report: {chat_filter_is_report}, is_handover: {chat_filter_is_handover} with confidence: {chat_filter_confidence}")
        
        if chat_filter_is_handover:  # Want to talk to human agent
            logger.debug(f"Due to handover, disable_agent for {phone_jid} set to True for the next 1 hour.")
            await _DB.update_config(
                phone=phone,
                values={"disable_agent": True},
                create_if_not_exists=True,
            )
            # Fire and forget: this runs in the background for 1 hour
            asyncio.create_task(reset_agent_after_delay(phone, 3600))
            await send_text_wrapper(
                client=client,
                raw_phone_number=raw_phone_number,
                raw_lid_number=raw_lid_number,
                text=f"Tunggu sebentar, tim CS dari ORIN akan segera membalas pesan Anda.",
            )
            return None
        
        if not chat_filter_is_processed:
            logger.warning(f"Chat: {last_message} is filtered from {phone_jid}, confidence: {chat_filter_confidence}")
            return
        
        # TODO: SEND CONFIDENCE AND REPLY TO JEMMY
        
        # Acquire lock to process this message
        async with entry.processing_lock:
            # Start typing indicator after 1 second
            typing_task = asyncio.create_task(asyncio.sleep(1))
            
            async def start_typing():
                """Start simulating typing after 1 second delay"""
                try:
                    await typing_task
                    client.simulateTyping(phone_jid, True)
                    logger.debug(f"Started typing indicator for {phone_jid}")
                except asyncio.CancelledError:
                    # Typing was cancelled before starting (response was fast)
                    pass
                except Exception:
                    logger.exception("Failed to start typing indicator")
            
            typing_handler = asyncio.create_task(start_typing())
            
            # WhatsApp Agent Question Classes
            question_class_result = await get_question_class(
                openai_client=openai_client,
                messages=llm_messages,
                question_class_details=question_class_details
            )
            question_class_dict = copy.deepcopy(question_class_details)
            for cr in question_class_result:
                question_class_dict = question_class_dict.get(cr)
                if "subclass" in question_class_dict.keys():
                    question_class_dict = question_class_dict.get("subclass")
                    
            question_class_tools: str = question_class_dict.get("tools")
                
            logger.info(f"Question class dict: {question_class_dict}")
        
            if question_class_tools == "end_session":
                logger.info("User want to end session by chat")
                await _SESSION_MANAGER.end_session(phone=phone, client=client)
                return           
            
            # POST to ORIN AI Chat
            logger.info(f"POST to ORIN AI with token: {api_tokens}")
            
            # Create an event to track if the waiting message was sent
            waiting_message_sent = False
            
            async def send_waiting_message():
                """Send waiting message after 10 seconds if processing is not complete"""
                nonlocal waiting_message_sent
                await asyncio.sleep(10)
                if not waiting_message_sent:
                    try:
                        # Stop typing before sending waiting message
                        ## NOTE: TEMPORARILY DISABLE SIMULATE TYPING
                        # client.simulateTyping(phone_jid, False)
                        
                        if USE_WAITING_MESSAGE:
                            waiting_text = WAITING_MESSAGE
                            client.sendText(phone_jid, waiting_text)
                            await _DB.add_message(entry.session_id, sender="bot", body=waiting_text)
                        waiting_message_sent = True
                    except Exception:
                        logger.exception("Failed to send waiting message")
            
            # Start the waiting message timer
            waiting_task = asyncio.create_task(send_waiting_message())
            
            try:
                bot_agent_id = await get_agent_id()
                
                async with httpx.AsyncClient(timeout=300.0) as httpx_client:
                    # Create a list of "combined" tasks
                    combined_tasks = [
                        full_fetch_ai(
                            httpx_client=httpx_client,
                            token=token,
                            llm_messages=llm_messages,
                            bot_agent_id=bot_agent_id,
                            chat_filter_is_report=chat_filter_is_report,
                            is_single_output=IS_SINGLE_OUTPUT,
                        )
                        for token in api_tokens
                    ]

                    # Run every single request (replies AND reports) simultaneously
                    results = await asyncio.gather(*combined_tasks)

                # Flatten and filter results
                all_replies = [r[0] for r in results if r[0]]
                all_reports = [r[1] for r in results if r[1]]
                
                logger.info(f"All Replies: {str(all_replies)[:100]}")
                
                all_reports_len = len(all_reports)
                logger.info(f"Total reports: {all_reports_len}")
                
                if all_replies:
                    # # Use first answer
                    # reply = all_replies[0]
                    # logger.info(f"Use the first one of All Replies: {reply[:10]}")
                    all_replies = await split_messages(
                        openai_client=openai_client,
                        all_replies=all_replies,
                        chat_filter_is_report=(chat_filter_is_report and all_reports_len)
                    )
                elif (not all_replies) and (all_reports_len > 0):
                    # If there is no replies but there is report, use report replies
                    all_replies = "[Excel File Sent]"
                    
                    all_replies = await split_messages(
                        openai_client=openai_client,
                        all_replies=all_replies,
                        chat_filter_is_report=(chat_filter_is_report and all_reports_len)
                    )
                else:
                    all_replies = [ERROR_MESSAGE]
                    reply_error = True
                
                # Parse from Marksdown style to Whatsapp style
                all_replies = [markdown_to_whatsapp(reply) for reply in all_replies]
                
                if not all_replies:
                    all_replies = [ERROR_MESSAGE]
                    reply_error = True
            finally:
                # Cancel typing tasks
                typing_task.cancel()
                typing_handler.cancel()
                
                # Always stop typing indicator
                try:
                    client.simulateTyping(phone_jid, False)
                except Exception:
                    logger.exception("Failed to stop typing indicator")
                
                # Ensure the waiting task is cancelled if it's still running
                waiting_task.cancel()
                # Mark waiting message as sent to prevent duplicate sends
                waiting_message_sent = True
    except Exception as e:
        logger.exception("Error in response chat (type=%s): %r", type(e).__name__, e)
        all_replies = [ERROR_MESSAGE]
        reply_error = True


    # send the reply
    try:
        if reply_error and USE_ERROR_MESSAGE:
            # client.sendText(phone_jid, reply)
            return
        elif not reply_error and all_replies:
            # Log text to wa
            if USE_RECEIVER_PHONE_MAPPING and RECEIVER_PHONE_MAPPING.get("log", False):
                await send_text_wrapper(
                    client=client,
                    raw_phone_number=raw_phone_number,
                    raw_lid_number=raw_lid_number,
                    text=f"Text: {last_message} incoming from {raw_phone_number}, {raw_lid_number}:",
                )
                logger.info(f"Make a log test to receiver mapping from {raw_phone_number}, {raw_lid_number}")
            
            # All File Send (reports)
            for i, report in enumerate(all_reports):
                timezone_jakarta = timezone(timedelta(hours=7))
                time_jakarta = datetime.now(timezone_jakarta)
                report_filename = time_jakarta.strftime(f"{i+1}_orin_report_%d%m%Y_%H%M%S.xlsx")
                
                logger.info(f"[chat_response] Sending excel file: {report_filename}")
                
                await send_file_wrapper(
                    client=client,
                    raw_phone_number=raw_phone_number,
                    raw_lid_number=raw_lid_number,
                    file=report,
                    filename=report_filename,
                    caption=""
                )
                await asyncio.sleep(random.uniform(1, 2))
            
            # All Message Replies
            for reply in all_replies:
                await send_text_wrapper(
                    client=client,
                    raw_phone_number=raw_phone_number,
                    raw_lid_number=raw_lid_number,
                    text=reply,
                )
                # client.sendText(phone_jid, reply)
                await asyncio.sleep(random.uniform(1, 2))
        else:
            return
    except Exception as e:
        logger.exception(f"Failed to send reply to {phone_jid}: {str(e)}")

    # store bot message
    try:
        for reply in all_replies:
            await _DB.add_message(entry.session_id, sender="bot", body=reply)
    except Exception:
        logger.exception("Failed to store bot message")

    # update session activity (this will also restart inactivity watcher)
    await _SESSION_MANAGER.touch_session(phone, client)

    return reply

# -----------------------------
# Exported helper to register decorator handler from main.py
# -----------------------------

from src.orin_wa_report.core.agent.verification import verify_wa_bot

def register_conv_handler(bot, openai_client: OpenAI):
    """Registers a on-message handler for r"^conv" on the provided ChatBotHandler instance.

    Usage (in your main.py after creating `bot = ChatBotHandler(client)`):

        from src.orin_wa_report.core.agent.handler import register_conv_handler
        register_conv_handler(bot)

    The handler simply forwards messages to chat_response.
    """
    @bot.on(r"")
    async def conv_handler(msg, client):
        # FILTERS
        ## CHECK if the message is ORIN Verifier
        ## NOTE: TEMPORARILY DEACTIVATE VERIFICATION
        # if msg["data"].get("body").strip().startswith(
        #     "Halo ORIN, saya ingin melakukan verifikasi akun ORIN AI."
        # ):
        #     logger.debug("User want to verify number")
        #     await verify_wa_bot(
        #         msg=msg,
        #         client=client
        #     )
        #     return
        
        # we ignore group messages here
        if msg.get("data", {}).get("isGroupMsg") or msg["data"]["fromMe"]:
            return
        
        raw_phone_number = msg["data"]["sender"].get("phoneNumber")
        raw_lid_number = msg["data"]["sender"].get("lid")
        
        # Development Mapping
        if USE_SENDER_PHONE_MAPPING:
            if raw_phone_number in SENDER_PHONE_MAPPING.keys():
                raw_phone_number = SENDER_PHONE_MAPPING[raw_phone_number]
        
        phone_number = raw_phone_number.split("@")[0]
        lid_number = raw_lid_number.split("@")[0]
        
        # Alternative phone number data
        wplus_phone_number = "+" + phone_number
        local_phone_number = "0" + phone_number[2:]
        
        # If phone_number is not verified
        
        # Max 3 users per question referred
        max_api_token_users = 3
        
        query = f"""
        SELECT
            id,
            name,
            api_token,
            wa_number
        FROM users
        WHERE
            (
                wa_number = :wa_number
                OR wa_lid = :wa_lid
                OR phone_number = :phone_number
                OR phone_number = :wplus_phone_number
                OR phone_number = :local_phone_number
            )
            
            AND deleted_at IS NULL
        ORDER BY updated_at DESC
        LIMIT {max_api_token_users};
        """
        # NOTE: TEMPORARILY REMOVE RULE TO BE VERIFIED
        # AND wa_verified = 1
        async with httpx.AsyncClient() as httpx_client:
            response = await httpx_client.post(db_query_url, json={
                "query": query,
                "params": {
                    "wa_number": phone_number,
                    "wa_lid": lid_number,
                    "phone_number": phone_number,
                    "wplus_phone_number": wplus_phone_number,
                    "local_phone_number": local_phone_number,
                }
            })
            response_sql: Dict = response.json()
        
        rows = response_sql.get("rows") or []
        # logger.info(f"User rows: {rows}")
        if not rows:
            logger.error(f"User {phone_number} not verified")
            # NOTE: DEATIVATED NOT VERIFIED USER MESSAGE
            # response = "Mohon maaf, nomor WhatsApp anda belum terverifikasi oleh sistem kami!"
            # try:
            #     client.sendText(raw_phone_number, response)
            # except WAError:
            #     client.sendText(raw_lid_number, response)
            
            logger.warning(f"{phone_number} messaged but they aren't verified!")
                
            return
        
        
        api_tokens = [
            row["api_token"]
            for row in response_sql.get("rows", [])
            if "api_token" in row
        ]

        # api_token = response_sql.get("rows")[0].get("api_token")
        if not api_tokens:
            logger.warning(f"No api_tokens found for {phone_number}")
            return
        
        await chat_response(
            msg=msg,
            client=client,
            api_tokens=api_tokens,
            openai_client=openai_client
        )

# -----------------------------
# Minimal placeholder for existing import in your main.py
# -----------------------------
