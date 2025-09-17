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
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.orin_wa_report.core.development.verify_wa import (
    verify_wa_key_and_store_wa_number
)
from src.orin_wa_report.core.utils import get_db_query_endpoint
from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__, service="Agent")

from dotenv import load_dotenv
load_dotenv(override=True)


db_api_key = os.getenv("ORIN_DB_API_KEY")
APP_STAGE = os.getenv("APP_STAGE", "development")

ORINAI_CHAT_ENDPOINT = os.getenv("ORINAI_CHAT_ENDPOINT")

db_query_url = get_db_query_endpoint(name=APP_STAGE)


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

# -----------------------------
# Lightweight sqlite wrapper
# -----------------------------

class ChatDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_done = False
        # small in-process sqlite is protected by an asyncio lock and run_in_executor for blocking ops
        self._lock = asyncio.Lock()

    async def initialize(self):
        async with self._lock:
            if self._init_done:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # connect
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
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
            """
        )
        self._conn.commit()

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
            warn_text = "Sesi chat akan diakhiri dalam 5 menit karena ketidakaktifan. Balas pesan untuk melanjutkan sesi ini."
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
            try:
                client.sendText(entry.jid, "Terima kasih telah menghubungi ORIN AI Chat. Jika Anda butuh bantuan di lain waktu, silakan chat kembali.")
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
            try:
                client.sendText(entry.jid, "Sesi chat akan diakhiri dalam 5 menit karena akan melalui batas wajar sesi.")
            except Exception:
                logger.exception("Failed to send forced-end warning")
            await asyncio.sleep(FORCED_WARNING_BEFORE)
            # final end
            sess = await self.db.get_session(entry.session_id)
            if not sess or sess.get("status") != "active":
                return
            logger.info(f"Force ending session {entry.session_id} for {entry.phone} due to time limit")
            try:
                client.sendText(entry.jid, "Terima kasih telah menghubungi ORIN AI Chat. Jika Anda butuh bantuan di lain waktu, silakan chat kembali.")
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

async def chat_response(
    msg: Dict[str, Any],
    client,
    api_token: str,
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

        phone_jid = msg["data"].get("from")
        phone = phone_jid.split("@")[0]
        sender = msg["data"].get("sender", {}) or {}
        user_name = sender.get("pushname", "")
        text = (msg["data"].get("body") or "").strip()

        # ensure session exists
        entry = await _SESSION_MANAGER.ensure_session(phone=phone, jid=phone_jid, user_name=user_name, client=client)

        # store user message
        try:
            await _DB.add_message(entry.session_id, sender="user", body=text)
        except Exception:
            logger.exception("Failed to store incoming message")

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
        
        logger.info(f"Get LLM message: {llm_messages[0]}")
        
        # POST to ORIN AI Chat
        logger.info(f"POST to ORIN AI Chat with token: {api_token}")
        async with httpx.AsyncClient(timeout=90.0) as httpx_client:
            response = await httpx_client.post(
                ORINAI_CHAT_ENDPOINT,
                json={
                    "messages": llm_messages
                },
                headers={"X-Api-Token": api_token}
            )
        response.raise_for_status()
        logger.info(f"Raw status code: {response.status_code}")
        logger.info(f"Raw response text: {response.text}")

        response_json: Dict = response.json()
        logger.info(f"Parsed JSON: {response_json}")
            
        reply = response_json.get("data", {}).get("response")
        if not reply:
            logger.warning(f"Unexpected API response: {response_json}")
            reply = "Mohon maaf kami belum dapat menjawab pertanyaan Anda."
        
        logger.info(f"ORIN AI Chat Reply: {reply}")
        
        # Parse from Marksdown style to Whatsapp style
        reply = markdown_to_whatsapp(reply)
        
        logger.info(f"Parsed to WA Style")
        
        if not reply:
            reply = "Mohon maaf kami belum dapat menjawab pertanyaan Anda."
    except Exception as e:
        logger.exception("Error in response chat (type=%s): %r", type(e).__name__, e)
        reply = "Mohon maaf kami belum dapat menjawab pertanyaan Anda."


    # send the reply
    try:
        client.sendText(phone_jid, reply)
    except Exception:
        logger.exception("Failed to send reply to %s", phone_jid)

    # store bot message
    try:
        await _DB.add_message(entry.session_id, sender="bot", body=reply)
    except Exception:
        logger.exception("Failed to store bot message")

    # update session activity (this will also restart inactivity watcher)
    await _SESSION_MANAGER.touch_session(phone, client)

    return reply

# -----------------------------
# Exported helper to register decorator handler from main.py
# -----------------------------

def register_conv_handler(bot):
    """Registers a on-message handler for r"^conv" on the provided ChatBotHandler instance.

    Usage (in your main.py after creating `bot = ChatBotHandler(client)`):

        from src.orin_wa_report.core.agent.handler import register_conv_handler
        register_conv_handler(bot)

    The handler simply forwards messages to chat_response.
    """
    @bot.on(r"^chat")
    async def conv_handler(msg, client, history):
        # we ignore group messages here
        if msg.get("data", {}).get("isGroupMsg"):
            return
        
        # Seen/Read the Message
        client.sendSeen(msg["data"]["from"])
        
        # If phone_number is not verified
        phone_number = msg["data"].get("from").split("@")[0]
        query = """
        SELECT
            id,
            name,
            api_token,
            wa_number
        FROM users
        WHERE
            wa_number = :wa_number
            AND wa_verified = 1
            AND deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 1;
        """
        async with httpx.AsyncClient() as httpx_client:
            response = await httpx_client.post(db_query_url, json={
                "query": query,
                "params": {"wa_number": phone_number}
            })
            response_sql: Dict = response.json()
        
        rows = response_sql.get("rows") or []
        if not rows:
            logger.error(f"User {phone_number} not verified")
            response = "Mohon maaf, nomor WhatsApp anda belum terverifikasi oleh sistem kami!"
            client.sendText(msg["data"]["from"], response)
            return
        
        api_token = response_sql.get("rows")[0].get("api_token")
        
        await chat_response(
            msg=msg,
            client=client,
            api_token=api_token
        )

# -----------------------------
# Minimal placeholder for existing import in your main.py
# -----------------------------
async def handler_verify_wa(
    wa_key: str,
    phone_number: str,
    user_name: str
) -> str:
    try:
        result = await verify_wa_key_and_store_wa_number(
            wa_key=wa_key,
            wa_number=phone_number
        )
        logger.info(f"WA Verification Result for {phone_number}: {json.dumps(result, indent=2)}")
        return f"Halo {user_name}, verifikasi ORIN Alert anda berhasil!"
    except Exception as e:
        logger.error(f"WA Verification for {phone_number} error: {str(e)}")
        return "Maaf, terjadi kesalahan saat verifikasi. Silakan coba lagi."