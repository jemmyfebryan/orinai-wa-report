# This code is to create dummy devices to devsites_orin_dev database

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

first_name_list = [
    "Sepeda",
    "Mobil",
    "Truk",
    "Bis",
    "Pesawat",
    "Skuter"
]

second_name_list = [
    "Cepat",
    "Mantap",
    "Awet",
    "Mahal",
    "Murah",
    "Gesit",
    "Sat Set",
    "Wasweswos",
    "Ngebut"
]

async def create_dummy_devices(user_id: int, count: int = 3):
    url = get_db_query_endpoint(name="devsites_orin_dev")
    
    values = []
    for _ in range(count):
        device_sn = f"6789{np.random.randint(1000000, 9999999)}"
        first_name = np.random.choice(first_name_list)
        second_name = np.random.choice(second_name_list)
        device_name = f"{first_name} {second_name}"
        
        gsm = f"081{np.random.randint(10000000, 99999999)}"
        
        # Escape strings properly
        values.append(f"({user_id}, 64, {device_sn}, '{device_name}', {gsm}, 'premium', NOW(), NOW())")
    
    # Build one INSERT query with multiple rows
    query = f"""
    INSERT INTO devices (user_id, device_type_id, device_sn, device_name, gsm, status, created_at, updated_at) 
    VALUES {", ".join(values)};
    COMMIT;
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "query": query,
            "api_key": db_api_key
        })
        response_sql: Dict = response.json()
    
    return response_sql

if __name__ == '__main__':
    dummy_device_result = asyncio.run(create_dummy_devices(user_id="39790", count=1))
    print(dummy_device_result)