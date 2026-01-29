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
        
        # Hard-coded settings
        self.required_alert_type = ["expired_license", "warning_expired_license"]
        
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
            
            CREATE TABLE IF NOT EXISTS user_alert_setting (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                value TEXT
            );
            
            CREATE TABLE IF NOT EXISTS chat_filter_setting (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting TEXT NOT NULL UNIQUE,
                value TEXT
            )
            """
        )
        self._conn.commit()
        
        # Default Value
        ## Notification Setting Default Value
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
        except Exception as e:
            logger.error(f"Error initializing default notification setting: {e}")
        
        # User Alert Setting
        # try:
        #     c.execute("SELECT setting FROM user_alert_setting WHERE setting=?", ("allowed_alert_type",))
        #     if c.fetchone() is None:
        #         c.execute(
        #             "INSERT INTO user_alert_setting (setting, value) VALUES (?, ?)",
        #             (
        #                 "allowed_alert_type",
        #                 "notif_speed_alert;notif_geofence_inside;notif_geofence_outside;notif_cut_off;notif_sleep;notif_online;notif_offline"
        #             )
        #         )
        #         self._conn.commit()
        #         logger.info("Default notification setting initialized")
                
        #     # Default prompt
        #     c.execute("SELECT setting FROM user_alert_setting WHERE setting=?", ("prompt_default",))
        #     if c.fetchone() is None:
        #         c.execute(
        #             "INSERT INTO user_alert_setting (setting, value) VALUES (?, ?)",
        #             (
        #                 "prompt_default",
        #                 r"Notifikasi ORIN! Kendaraan anda ({device_name}) {message}"
        #             )
        #         )
        #         self._conn.commit()
        #         logger.info("Default notification prompt initialized")
        # except Exception as e:
        #     logger.error(f"Error initializing default notification setting: {e}")
        
        ## Chat Filter Setting Default Value
        try:
            c.execute("SELECT setting FROM chat_filter_setting WHERE setting=?", ("chat_filter_instruction",))
            if c.fetchone() is None:
                c.execute(
                    "INSERT INTO chat_filter_setting (setting, value) VALUES (?, ?)",
                    (
                        "chat_filter_instruction",
                        """
Tugas Anda adalah menentukan apakah pesan user termasuk dalam kategori Manajemen Device/Kendaraan berikut:
1. Waktu Operasional: Jam kerja, waktu mulai/berhenti, durasi idle (mesin nyala tapi diam), dan durasi moving (perjalanan).
2. Utilisasi Kendaraan: Jumlah hari kendaraan tidak beroperasi atau frekuensi penggunaan kendaraan.
3. Jarak Tempuh: Estimasi kilometer (KM) yang ditempuh dalam periode tertentu.
4. Perilaku Berkendara: Insiden keselamatan seperti mengebut (overspeed), pengereman mendadak (braking), akselerasi tajam (speedup), dan manuver tajam (cornering).
5. Analisis Kecepatan: Data kecepatan rata-rata atau kecepatan maksimal kendaraan.
6. Estimasi BBM: Perkiraan konsumsi bahan bakar atau biaya bensin berdasarkan aktivitas.
7. Data Statis: Data mengenai lokasi, kecepatan, status kendaraan/device pada spesifik waktu tertentu
8. Alert Notifikasi: Data mengenai notifikasi real-time terkait kendaraan seperti speeding, keluar/masuk lokasi, device dihidupkan/dimatikan, notifikasi lisensi kendaraan, dan notifikasi lainnya
9. Report/Laporan Kendaraan: Report atau Laporan tentang history rangkuman/summary kendaraan di kurun waktu tertentu dalam file Excel.
10. Akun: Pertanyaan mengenai akun seperti lupa password/kata sandi, status akun, waktu expired lisensi akun

Kriteria Output pada Key 'is_processed':
- Berikan True jika pertanyaan berkaitan dengan salah satu poin di atas, meskipun disampaikan dengan bahasa santai/tidak baku. Pertanyaan bisa saja tersirat merujuk pesan sebelumnya.
- Berikan False jika pesan berupa:
  a. Salam (Halo, Selamat pagi, dll) tanpa diikuti pertanyaan teknis.
  b. Pertanyaan di luar data kendaraan (Contoh: cara ganti password, harga paket produk, minta refund, atau komplain admin).
  c. Pertanyaan kurang jelas atau kurang bisa dimengerti.
  d. Agent tidak bisa menjawab pertanyaan
  
Kriteria Output pada Key 'is_report':
- Berikan True jika pertanyaan berkaitan dengan Report atau Laporan Kendaraan (Poin nomor 7) termasuk permintaan pembuatan Excel, meskipun disampaikan dengan bahasa santai/tidak baku. Pertanyaan bisa saja tersirat merujuk pesan sebelumnya. Pilih jika menurutmu user membutuhkan file Excel karena agent nanti akan mengirimkan file Excel sesuai permintaan user.
- Berikan False jika pertanyaan tidak berkaitan dengan Report atau Laporan Kendaraan.

Kriteria Output pada Key 'is_handover':
- Berikan True jika user membutuhkan bantuan Human Agent untuk menjawab pertanyaan, dikarenakan pertanyaan terlalu kompleks untuk dijawab oleh Agent.
"""
                    )
                )
                self._conn.commit()
                logger.info("Default chat filter instruction setting initialized")
                
            c.execute("SELECT setting FROM chat_filter_setting WHERE setting=?", ("chat_filter_questions",))
            if c.fetchone() is None:
                c.execute(
                    "INSERT INTO chat_filter_setting (setting, value) VALUES (?, ?)",
                    (
                        "chat_filter_questions",
                        """
- "Mobil B 1234 ABC kemarin mulai jalan jam berapa ya?"
- "Berapa lama total waktu idle truk saya selama seminggu terakhir?"
- "Tampilkan daftar kendaraan yang tidak jalan sama sekali di hari kerja bulan ini."
- "Berapa estimasi jarak tempuh unit Avanza saya dari tanggal 1 sampai 10?"
- "Siapa sopir yang paling sering ngerem mendadak kemarin?"
- "Berapa kecepatan maksimal yang dicapai bus nomor 05 tadi siang?"
- "Estimasi bensin yang habis buat perjalanan ke Bandung kemarin berapa rupiah?"
- "Apakah ada kendaraan yang overspeed di jalan tol tadi pagi?"
- "Total jam operasional semua kendaraan saya di bulan Desember."
- "Berapa hari mobil saya nganggur dalam sebulan ini?"
- "Dimana posisi mobil wuling saya"
- "Status gps mobil xpander saya bagaimana"
- "Mobil innova saya sekarang lagi dimana?"
- "Bisa buatkan report dalam sebulan terakhir?"
- "Report penggunaan bensin hari ini"
- "Buatkan excel ringkasan perjalanan minggu ini"
- "Laporan perjalanan per device sebulan terakhir"
- "Halo kapan ya terakhir kali kendaraan saya dimatikan"
- "Kapan lisensi kendaraan saya habis"
- "Saya lupa password tolong"
- "Status akun apa dan expirednya kapan ya?"
"""
                    )
                )
                self._conn.commit()
                logger.info("Default chat filter questions setting initialized")
        except Exception as e:
            logger.error(f"Error initializing default chat filter setting: {e}")
    
    def include_required_alert(self, allowed_alert_type: str) -> str:
        allowed_alert_type_list = allowed_alert_type.split(sep=";")
        
        allowed_alert_type_list = list(
            set(allowed_alert_type_list)
            | set(self.required_alert_type)
        )
            
        allowed_alert_type = ";".join(allowed_alert_type_list)
        
        return allowed_alert_type
        
    async def get_notification_setting(
        self,
        get_allowed_alert_type: bool = False,
        include_required_alert_type: bool = True,
    ) -> List[Dict[str, str]] | Dict[str, str]:
        cursor = self._conn.cursor()
        
        if get_allowed_alert_type:
            query = "SELECT id, setting, value FROM notification_setting WHERE setting = 'allowed_alert_type'"
            cursor.execute(query)
            row: List[str] = cursor.fetchone()
            
            allowed_alert_type = row[2]
            if include_required_alert_type:
                allowed_alert_type = self.include_required_alert(
                    allowed_alert_type=allowed_alert_type
                )
            
            notification_setting = {
                "id": row[0],
                "setting": row[1],
                "value": allowed_alert_type,
            }
        else:
            query = "SELECT id, setting, value FROM notification_setting"
            cursor.execute(query)
            notification_setting = []
            for row in cursor.fetchall():
                value = row[2]
                if row[2] == "allowed_alert_type" and include_required_alert_type:
                    value = self.include_required_alert(
                        allowed_alert_type=value
                    )
                notification_setting.append(
                    {
                        "id": row[0],
                        "setting": row[1],
                        "value": value,
                    }
                )
        return notification_setting
    
    async def create_notification_setting(self, data: Dict):
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
                    value,
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
    
    async def get_user_alert_setting(
        self,
        user_id: int,
        include_required_alert_type: bool = False,
    ) -> str:
        cursor = self._conn.cursor()
        cursor.execute("SELECT id, user_id, value FROM user_alert_setting WHERE user_id = ?", (user_id,))
        
        alert_settings = cursor.fetchone()
        
        if alert_settings is None:
            logger.info(f"(get_user_alert_setting) No setting for {user_id}, add the default.")
            notification_setting = await self.get_notification_setting(
                get_allowed_alert_type =True,
                include_required_alert_type=False,
            )
            user_alert_setting = notification_setting.get("value")
            
            cursor.execute(
                "INSERT INTO user_alert_setting (user_id, value) VALUES (?, ?)",
                (
                    user_id,
                    user_alert_setting,
                )
            )
            self._conn.commit()
            
            if include_required_alert_type:
                user_alert_setting = self.include_required_alert(
                    allowed_alert_type=user_alert_setting
                )
        else:
            user_alert_setting = alert_settings[2]
        
        return user_alert_setting
    
    async def put_user_alert_setting(self, user_id: str, value: str | Dict) -> None:
        """
        Update User Alert Setting for the user_id
        value can either be str for direct update with no filtering
        or Dict that could dynamically set the value
        
        :param user_id: ID of user that the alert settings need to be updated
        :type user_id: str
        :param value: Either str or Dict of updated alert settings value
        :type value: str | Dict
        """
        cursor = self._conn.cursor()
        
        if isinstance(value, str):
            updated_alert_type = value
        else:
            allowed_alert_type = await self.get_notification_setting(
                get_allowed_alert_type=True,
                include_required_alert_type=False,
            )
            allowed_alert_type_list = allowed_alert_type.get("value").split(sep=";")
            
            current_alert_type = await self.get_user_alert_setting(
                user_id=user_id,
                include_required_alert_type=False,
            )
            current_alert_type_set = set(current_alert_type.split(sep=";"))
            
            for key, value in value.items():
                if value == True and value in allowed_alert_type_list:
                    current_alert_type_set.add(key)
                else:
                    current_alert_type_set.discard(key)
                    
            updated_alert_type = ";".join(current_alert_type_set)
        
        cursor.execute(
            "UPDATE user_alert_setting SET value=? WHERE user_id=?",
            (
                updated_alert_type,
                user_id,
            )
        )
        self._conn.commit()
        
        return updated_alert_type
    
    # async def get_chat_filter_setting(self) -> tuple[Optional[str], Optional[str]]:
    #     """
    #     Returns a tuple of (instruction, questions).
    #     """
    #     cursor = self._conn.cursor()
    #     # Fetch only the two specific settings we need
    #     cursor.execute(
    #         "SELECT setting, value FROM chat_filter_setting WHERE setting IN (?, ?)",
    #         ("chat_filter_instruction", "chat_filter_questions")
    #     )
        
    #     # Create a lookup dict from the results
    #     results = {row[0]: row[1] for row in cursor.fetchall()}
        
    #     # Return as a tuple in the specific order requested
    #     return (
    #         results.get("chat_filter_instruction"),
    #         results.get("chat_filter_questions")
    #     )
        
    # async def update_chat_filter_setting(self, setting: str, data: Dict):
    #     value = data.get('value')
    #     if (
    #         not setting
    #     ):
    #         raise RuntimeError("Key 'setting' is required in arg data")
        
    #     cursor = self._conn.cursor()
    #     try:
    #         cursor.execute(
    #             "UPDATE chat_filter_setting SET value=? WHERE setting=?",
    #             (
    #                 value,
    #                 setting,
    #             )
    #         )
    #         if cursor.rowcount == 0:
    #             raise ValueError("Setting not found")
    #         self._conn.commit()
    #         return {
    #             "setting": setting,
    #             "value": value,
    #         }
    #     except sqlite3.IntegrityError:
    #         raise RuntimeError("Setting must be unique")

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
            
async def get_settings_db() -> SettingsDB:
    await ensure_settings_db()
    return SETTINGS_DB