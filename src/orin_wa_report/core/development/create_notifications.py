# This code is to create rows on alert_notifications
# for every user that subscribe to the wa service.

import random
import os
from typing import List, Dict

import numpy as np
import pandas as pd
import httpx

from src.orin_wa_report.core.logger import get_logger
from src.orin_wa_report.core.utils import get_db_query_endpoint

logger = get_logger(__name__)

from dotenv import load_dotenv
load_dotenv(override=True)

db_api_key = os.getenv("ORIN_DB_API_KEY")

alert_type_list = [
    "notif_speed_alert",
    "notif_geofence_inside",
    "notif_geofence_outside"
]

address_list = [
    "KANTOR A",
    "KANTOR B",
    "GUDANG U",
    "GUDANG V",
    "TEMPAT P",
    "TEMPAT Q",
    "JALAN X",
    "JALAN Y",
    "JALAN Z"
]

async def insert_dummy_alert(user_id: int, device_id: int):
    url = get_db_query_endpoint(name="devsites_orin_dev")
    
    alert_type = np.random.choice(alert_type_list)
    
    if alert_type == "notif_speed_alert":
        speed = round(random.uniform(80, 120), 2)
        message = f"Overspeed {speed}km/h"
    elif alert_type == "notif_geofence_inside":
        address = np.random.choice(address_list)
        message = f"Masuk [{address}]."
    elif alert_type == "notif_geofence_outside":
        address = np.random.choice(address_list)
        message = f"Keluar [{address}]."
    else:
        message = "Unknown alert."
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "query": f"INSERT INTO alert_notifications (device_id, user_id, alert_type, message) VALUES ({device_id}, {user_id}, '{alert_type}', '{message}');COMMIT;",
            "api_key": db_api_key
        })
        response_sql: Dict = response.json()
    
    return response_sql

async def get_subscribed_users() -> List[Dict]:
    url = get_db_query_endpoint(name="devsites_orin_dev")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "query": f"SELECT id, name, wa_key, wa_notif, wa_number, wa_verified from users WHERE wa_notif = 1 AND wa_verified = 1"
        })
        response_sql: Dict = response.json()
    
    return response_sql.get("rows")

async def create_dummy_notifications(sample: float = 0.25):
    url = get_db_query_endpoint(name="devsites_orin_dev")

    subscribed_users = await get_subscribed_users()
    for user in subscribed_users:
        user_id = user.get("id")
        user_name = user.get("name")

        if random.random() < sample:
            # Get Devices from user
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json={
                    "query": """
                        SELECT id, user_id, device_sn   , device_name 
                        FROM devices 
                        WHERE user_id = :user_id AND deleted_at IS NULL
                    """,
                    "params": {"user_id": user_id}
                })
                response_sql: Dict = response.json()

            user_devices = pd.DataFrame(response_sql.get("rows", []))

            if user_devices.empty:
                logger.info(f"No devices for user {user_name} (id={user_id})")
                continue

            random_device = user_devices.sample(n=1).iloc[0]
            device_id = random_device["id"]
            device_sn = random_device["device_sn"]
            device_name = random_device["device_name"]

            # Insert alert_notifications
            dummy_alert_response = await insert_dummy_alert(
                user_id=user_id,
                device_id=device_id
            )

            logger.info(
                f"Alert inserted for User: {user_name} (id={user_id}), "
                f"Device: {device_name} (id={device_id}, sn={device_sn})."
            )

# import asyncio
# if __name__ == '__main__':
#     dummy_notifications_result = asyncio.run(create_dummy_notifications())
#     print(dummy_notifications_result)