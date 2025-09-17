# This code is to create rows on alert_notifications
# for every user that subscribe to the wa service.

import asyncio
import json
from typing import List, Dict

import httpx

from src.orin_wa_report.core.utils import get_db_query_endpoint
from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__)

from dotenv import load_dotenv
load_dotenv(override=True)

async def get_subscribed_users() -> List[Dict]:
    url = get_db_query_endpoint(name="devsites_orin_dev")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "query": f"SELECT id, name, wa_key, wa_notif, wa_number, wa_verified from users WHERE wa_notif = 1 AND wa_verified = 1"
        })
        response_sql: Dict = response.json()
    
    return response_sql.get("rows")

if __name__ == '__main__':
    dummy_user_result = asyncio.run(get_subscribed_users())
    print(json.dumps(dummy_user_result, indent=2))