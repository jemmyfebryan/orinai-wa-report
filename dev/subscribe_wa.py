# This code is to subscribe wa reports
## If user not verified (wa_verified == 0),
## return user is not verified, otherwise will set wa_notif

import os
import asyncio
import secrets
import base64
import json
from typing import List, Dict

import httpx
import pandas as pd
import numpy as np

from src.orin_wa_report.core.utils import get_db_query_endpoint

from dotenv import load_dotenv
load_dotenv(override=True)

db_api_key = os.getenv("ORIN_DB_API_KEY")

async def subscribe_wa(api_token: str, subscribe: bool):
    url = get_db_query_endpoint(name="devsites_orin_dev")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "query": f"SELECT id, wa_notif, wa_verified from users WHERE api_token = :api_token LIMIT 1",
                "params": {"api_token": api_token}
            })
            response_sql: Dict = response.json()
        
        df_sql = pd.DataFrame(response_sql["rows"])
        
        is_wa_notif = True if df_sql["wa_notif"].tolist()[0] else False
        is_wa_verified = True if df_sql["wa_verified"].tolist()[0] else False
        
        user_id = df_sql["id"].tolist()[0]
        
        subscribe = 1 if subscribe else 0
        subscribe_bool = True if subscribe else False
        
        query = None
        
        if not is_wa_verified:
            status = "error"
            message = "User is not WhatsApp verified!"
        else:
            query = f"UPDATE users SET wa_notif = {subscribe} WHERE id = {user_id}; COMMIT;"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json={
                    "query": query,
                    "api_key": db_api_key,
                })
                response_sql: Dict = response.json()
                
            status = "success"
            message = f"User wa_notif set from {is_wa_notif} to {subscribe_bool}"
        
        
        return {
            "status": status,
            "message": message,
            "is_wa_verified": is_wa_verified
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Unknown error: {str(e)}",
        }


if __name__ == '__main__':
    result = asyncio.run(subscribe_wa(
        api_token="7S5B2asD1xVXaZf_qN8pDSMqELnd5jsi_uCjl0i6awc",
        subscribe=True
    ))
    print(json.dumps(result, indent=2))