import asyncio
from typing import List, Dict

import httpx
import pandas as pd

from src.orin_wa_report.core.logger import get_logger
from src.orin_wa_report.core.development import (
    create_notifications,
)
from src.orin_wa_report.core.utils import get_db_query_endpoint

logger = get_logger(__name__, service="FastAPI")

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
        
# PLEASE IMPLEMENT SQLITE FOR THIS, AND SETTINGS FOR MORE ROBUST
alert_last_id = None

async def periodic_send_notifications():
    global alert_last_id
    while True:
        await asyncio.sleep(6)
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8000/settings")
                config_data = response.json()
                
            # Check config
            # if not config_data.get("fastapi").get("enable_send_alert", False):
            if not config_data.get("enable_send_alert"):
                # logger.info(f"Periodic send notifications disabled...")
                alert_last_id = None
                continue
                
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
                
                messages = [
                    {
                        "to": f"{row['wa_number']}@c.us",
                        "message": f"Notifikasi ORIN! Kendaraan anda ({row['device_name']}) {row['message']}"
                    }
                    for _, row in df_notif.iterrows()
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
            