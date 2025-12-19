from src.orin_wa_report.core.db import SettingsDB, DB_PATH
import asyncio
import sqlite3

conn = sqlite3.connect(str(DB_PATH), check_same_thread=True)
cursor = conn.cursor()
print(cursor.execute("SELECT id, setting, value FROM notification_setting").fetchall())

# print(DB_PATH)
# SETTINGS_DB = None

# async def run():
#     global SETTINGS_DB
    
#     SETTINGS_DB = SettingsDB(DB_PATH)
#     await SETTINGS_DB.initialize()

#     config = await SETTINGS_DB.get_notification_setting()
#     print(config)
#     print(len(config))
#     print(SETTINGS_DB.db_path)
    
# if __name__ == "__main__":
#     asyncio.run(run())