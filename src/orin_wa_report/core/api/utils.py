import asyncio
import os
from typing import List, Dict

import httpx
import pandas as pd
from dotenv import load_dotenv

from src.orin_wa_report.core.logger import get_logger
from src.orin_wa_report.core.development import (
    create_notifications,
)
from src.orin_wa_report.core.utils import get_db_query_endpoint
from src.orin_wa_report.core.db import SettingsDB, DB_PATH

load_dotenv(override=True)

logger = get_logger(__name__, service="FastAPI")

APP_STAGE = os.getenv("APP_STAGE", "development")
db_query_url = get_db_query_endpoint(name=APP_STAGE)

SETTINGS_DB = None
_db_init_lock = asyncio.Lock()

async def ensure_settings_db():
    global SETTINGS_DB
    async with _db_init_lock:
        if SETTINGS_DB is None:
            SETTINGS_DB = SettingsDB(DB_PATH)
            await SETTINGS_DB.initialize()

async def periodic_dummy_notifications():
    while True:
        await asyncio.sleep(1)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8000/settings")
                config_data = response.json()
            # if not config_data.get("dummy").get("enable_create_alert", False):
            if not config_data.get("enable_create_dummy_alert"):
                # logger.info(f"Periodic dummy notifications disabled...")
                continue
                
            logger.info("Run periodic dummy notifications...")
            await create_notifications.create_dummy_notifications(sample=0.5)
        except Exception as e:
            logger.error(f"Error in dummy notifications background job: {e}")

async def build_notification_message(
    notification_setting: Dict[str, str],
    row_data: pd.Series
) -> str:
    alert_type = row_data["alert_type"]
    device_name = row_data["device_name"]
    message = row_data["message"]
    
    # Check if there is a specific message format
    # "prompt_{alert_type}" is the key in notification_setting
    # if there is any specific message format based on alert_type
    alert_type_key = f"prompt_{alert_type}"
    if alert_type_key in notification_setting.keys():
        message = notification_setting.get(alert_type_key).format(
            device_name=device_name,
            message=message
        )
    else:  # use 'prompt_default' if there is no specific alert
        message = notification_setting.get("prompt_default").format(
            device_name=device_name,
            message=message,
        )
    return message
    
    

# PLEASE IMPLEMENT SQLITE FOR THIS, AND SETTINGS FOR MORE ROBUST
alert_last_id = None

async def periodic_send_notifications():
    global alert_last_id
    await ensure_settings_db()
    while True:
        await asyncio.sleep(6)
        try:
            notification_config: List[Dict[str, str]] = await SETTINGS_DB.get_notification_setting()
            notification_setting = {item["setting"]: item["value"] for item in notification_config}
            
            allowed_alert_type = notification_setting.get("allowed_alert_type").split(sep=";")
            
            # logger.info(notification_setting)
            
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8000/settings")
                config_data = response.json()
                
            # Check config
            # if not config_data.get("fastapi").get("enable_send_alert", False):
            if not config_data.get("enable_send_alert"):
                # logger.info(f"Periodic send notifications disabled...")
                alert_last_id = None
                continue
            
            logger.info(f"Periodic send notifications: alllowed_alert_type: {allowed_alert_type}")
                
            url = get_db_query_endpoint(name="devsites_orin_dev")
            if alert_last_id is None:
                logger.info("Periodic send notifications: Undefined alert id, fetch one...")
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json={
                        "query": """
                            SELECT id FROM alert_notifications ORDER BY id DESC LIMIT 1
                        """
                    })
                    response_sql: Dict = response.json()
                alert_last_id = response_sql.get("rows")[0].get("id")
                logger.info(f"Get alert_last_id: {alert_last_id}")
            else:
                # Fetch all alert notifications from last known to now with 1000 limit order from newest
                
                logger.info("Periodic send notifications: Begin fetching notifications...")
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json={
                        "query": """
SELECT 
    an.*, 
    u.wa_number,
    u.wa_lid, 
    u.wa_notif, 
    u.wa_verified,
    d.device_name
FROM alert_notifications an
JOIN users u ON u.id = an.user_id
LEFT JOIN devices d ON d.id = an.device_id
WHERE an.id > :id
  AND u.wa_notif = 1
  AND u.wa_verified = 1
  AND u.deleted_at IS NULL
ORDER BY an.id ASC
LIMIT 1000;

"""
                    , "params": {"id": alert_last_id}})
                    response_sql: Dict = response.json()
                
                # Parse to messages
                df_notif = pd.DataFrame(response_sql.get("rows", {}))
                
                if len(df_notif) == 0:
                    logger.info(f"No new notif to subscribed user, continue...")
                    continue
                
                alert_last_id = int(df_notif["id"].iloc[-1])
                logger.info(f"Get alert_last_id: {alert_last_id}")
                
                # old message: f"Notifikasi ORIN! Kendaraan anda ({row['device_name']}) {row['message']}"
                # TODO: Alert type filter + Required is inside the sql query, not after fetching
                # TODO: IMPLEMENT PERSONALIZED USER_ALERT
                
                # 1. Filter the rows we need to process
                rows_to_process = [
                    row
                    for _, row in df_notif.iterrows()
                    if row['alert_type'] in allowed_alert_type
                ]
                
                # 2. Create a list of awaitable tasks for building messages
                message_building_tasks = [
                    build_notification_message(
                        notification_setting=notification_setting,
                        row_data=row
                    )
                    for row in rows_to_process
                ]
                
                # 3. Use asyncio.gather to run all tasks concurrently
                # The results will be a list of the resolved message strings, in the same order as the tasks.
                message_contents = await asyncio.gather(*message_building_tasks)
                
                # 4. Construct the final 'messages' list using the concurrent results
                messages = [
                    {
                        "to": f"{row['wa_number']}@c.us",
                        "to_fallback": f"{row['wa_lid']}@lid",
                        "message": content
                    }
                    for row, content in zip(rows_to_process, message_contents)
                ]
                
                messages_delay_seconds = round(5.9/len(messages), 2)
                messages_payload = {
                    "messages": messages,
                    "delay_seconds": messages_delay_seconds
                }
                
                logger.info(f"Sending messages from id {alert_last_id} with delay {messages_delay_seconds}")
                
                # Send bulking using API "send-bulk"
                async with httpx.AsyncClient() as client:
                    response = await client.post("http://localhost:8000/send-messages", json=messages_payload)
                    response_sql: Dict = response.json()
                
                logger.info(f"Send messages result: {response_sql}")
        except Exception as e:
            logger.error(f"Error in send notifications background job: {e}")

async def convert_phone_to_lid(phone_number: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(db_query_url, json={
            "query": """
                SELECT 
                    wa_number,
                    wa_lid
                FROM users
                WHERE
                    wa_number = :wa_number
                LIMIT 1
            """,
            "params": {"wa_number": phone_number}
        })
        response_sql: Dict = response.json()
    wa_lid = response_sql.get("rows")[0].get("wa_lid")
    return wa_lid