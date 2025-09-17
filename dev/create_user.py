# This code is to create dummy user to devsites_orin_dev database
# Contains randomized name, email, api_token, and default for wa columns

import os
import secrets
import base64
import asyncio
from typing import Dict

import httpx
import numpy as np

from src.orin_wa_report.core.utils import get_db_query_endpoint
from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__)

from dotenv import load_dotenv
load_dotenv()

db_api_key = os.getenv("ORIN_DB_API_KEY")

first_name_list = [
    "Andi",
    "Budi",
    "Charlie",
    "Danton",
    "Erik",
    "Farah"
]

second_name_list = [
    "Gunawan",
    "Arie",
    "Tanjaya",
    "Budiman",
    "Suryo",
    "Tegar"
]

async def generate_api_token(length: int = 64) -> str:
    """
    Generate a cryptographically secure opaque API token.

    Args:
        length (int): Number of random bytes to use (default 32 = 256 bits).

    Returns:
        str: A URL-safe Base64 encoded token.
    """
    random_bytes = secrets.token_bytes(length)
    token = base64.urlsafe_b64encode(random_bytes).decode("utf-8").rstrip("=")
    return token

async def create_dummy_user(wa_verified: bool = False):
    url = get_db_query_endpoint(name="devsites_orin_dev")
    
    first_name: str = np.random.choice(first_name_list)
    second_name: str = np.random.choice(second_name_list)
    random_num: int = np.random.randint(1, 1000)
    
    wa_number = f"+62{np.random.randint(100000000, 999999999)}" if wa_verified else "NULL"
    wa_verified = 1 if wa_verified else 0
    
    name = f"OrinAI {first_name} {second_name}"
    email = f"orinai_{first_name.lower()}{second_name.lower()}{random_num}@gmail.com"
    
    hashed_password = "$2y$10$orinaimantapjayajayajayaluarbiasa"
    
    user_api_token = await generate_api_token(length=32)
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "query": f"INSERT INTO users (name,email,password,created_at,updated_at,api_token,verified,account_type,license_type,google,facebook,has_tms,wa_number,wa_verified) VALUES ('{name}','{email}','{hashed_password}',NOW(),NOW(),'{user_api_token}',1,'premium','basic_annual',0,0,0,'{wa_number}',{wa_verified});COMMIT;",
            "api_key": db_api_key
        })
        response_sql: Dict = response.json()
        
    return {
        "name": name,
        "email": email,
        "api_token": user_api_token,
        "sql_response": response_sql
    }

if __name__ == '__main__':
    dummy_user_result = asyncio.run(create_dummy_user(wa_verified=True))
    print(dummy_user_result)