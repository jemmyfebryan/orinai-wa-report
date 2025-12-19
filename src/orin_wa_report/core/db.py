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
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__, service="Agent")


CORE_DIR = Path(__file__).resolve().parents[0]  # core/
DB_DIR = CORE_DIR / "database"
DB_PATH = DB_DIR / "settings.db"

db_path = Path(DB_PATH)

class SettingsDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_done = False
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
            CREATE TABLE IF NOT EXISTS notification_setting (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting TEXT NOT NULL UNIQUE,
                value TEXT
            );
            """
        )
        self._conn.commit()
        
        # Default Value
        try:
            c.execute("SELECT setting FROM notification_setting WHERE setting=?", ("allowed_alert_type",))
            if c.fetchone() is None:
                c.execute(
                    "INSERT INTO notification_setting (setting, value) VALUES (?, ?)",
                    (
                        "allowed_alert_type",
                        "notif_speed_alert;notif_geofence_inside;notif_geofence_outside;notif_cut_off;notif_sleep;notif_online;notif_offline"
                    )
                )
                self._conn.commit()
                logger.info("Default notification setting initialized")
                
            # Default prompt
            c.execute("SELECT setting FROM notification_setting WHERE setting=?", ("prompt_default",))
            if c.fetchone() is None:
                c.execute(
                    "INSERT INTO notification_setting (setting, value) VALUES (?, ?)",
                    (
                        "prompt_default",
                        r"Notifikasi ORIN! Kendaraan anda ({device_name}) {message}"
                    )
                )
                self._conn.commit()
                logger.info("Default notification prompt initialized")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error initializing default notification setting: {e}")
            return False
            
    async def get_notification_setting(self):
        cursor = self._conn.cursor()
        cursor.execute("SELECT id, setting, value FROM notification_setting")
        agents = [
            {
                "id": row[0],
                "setting": row[1],
                "value": row[2],
            }
            for row in cursor.fetchall()
        ]
        return agents
    
    async def create_notification_setting(self, data):
        setting = data.get('setting')
        value = data.get('value')
        if (
            not setting
        ):
            raise ValueError("'setting' key is required in data")
        
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO notification_setting (setting, value) VALUES (?, ?)",
                (
                    setting,
                    value
                )
            )
            self._conn.commit()
            setting_id = cursor.lastrowid
            return {
                "id": setting_id,
                "setting": setting,
                "value": value
            }
        except sqlite3.IntegrityError:
            raise RuntimeError("Setting must be unique")
        
    async def update_notification_setting(self, setting: str, data: Dict):
        value = data.get('value')
        if (
            not setting
        ):
            raise RuntimeError("Key 'setting' is required in arg data")
        
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "UPDATE notification_setting SET value=? WHERE setting=?",
                (
                    value,
                    setting,
                )
            )
            if cursor.rowcount == 0:
                raise ValueError("Setting not found")
            self._conn.commit()
            return {
                "setting": setting,
                "value": value,
            }
        except sqlite3.IntegrityError:
            raise RuntimeError("Setting must be unique")
        
    async def delete_notification_setting(self, setting: str):
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM notification_setting WHERE setting=?", (setting,))
        if cursor.rowcount == 0:
            raise ValueError("Setting not found")
        self._conn.commit()
        return {"status": "success", "message": "Setting deleted"}

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
# Module-level singletons
# -----------------------------
SETTINGS_DB: Optional[SettingsDB] = None
_db_init_lock = asyncio.Lock()

async def ensure_settings_db():
    global SETTINGS_DB
    async with _db_init_lock:
        if SETTINGS_DB is None:
            SETTINGS_DB = SettingsDB(DB_PATH)
            await SETTINGS_DB.initialize()