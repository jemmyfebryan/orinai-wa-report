import os
import random
import asyncio
from typing import Dict

import httpx
import numpy as np

from src.orin_wa_report.core.utils import get_db_query_endpoint
from src.orin_wa_report.core.logger import get_logger

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

if __name__ == '__main__':
    dummy_alert_result = asyncio.run(insert_dummy_alert(user_id="39790", device_id="57913"))
    print(dummy_alert_result)