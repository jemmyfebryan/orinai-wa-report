import os
import json
import httpx
import aiofiles
from enum import Enum
from typing import Dict, List

import pandas as pd

from src.orin_wa_report.core.logger import get_logger
from src.orin_wa_report.core.config import DB_QUERY_ENDPOINT

from dotenv import load_dotenv

load_dotenv(override=True)
vps_ip = os.getenv("VPS_IP")
vps_db_port = os.getenv("VPS_DB_PORT")
vps_db_base_url = f"http://{vps_ip}:{vps_db_port}"

logger = get_logger(__name__)

def get_db_query_endpoint(db_base_url: str = vps_db_base_url, name: str = ""):
    url = DB_QUERY_ENDPOINT.get(name, "")
    if name == "":
        url = f"{db_base_url}/query"  # default to /query
    else:
        url = url.format(db_base_url=db_base_url)
    return url

async def log_data(file_name, data_dict):
    """
    Appends a dictionary as a single line in a .jsonl file asynchronously.
    """
    # Convert dictionary to a JSON string + newline
    # ensure_ascii=False handles special characters better
    json_line = json.dumps(data_dict, ensure_ascii=False) + "\n"
    
    # Use aiofiles for non-blocking disk I/O
    async with aiofiles.open(file_name, mode='a', encoding='utf-8') as f:
        await f.write(json_line)
        

async def get_user_id_from_api_token(
    db_base_url: str,
    api_token: str,
    derive_parent_id: bool = True,
):
    """
    Retrieves the user identity associated with a given API token.

    The function checks the 'users' table first, followed by the 'user_tokens' table.
    If 'derive_parent_id' is True, it evaluates if the user is a sub-account. 
    If a valid 'parent_id' exists (not NULL and not 0), it returns the 'parent_id'; 
    otherwise, it returns the primary 'user_id'.

    Args:
        db_base_url (str): The base URL for the database service.
        api_token (str): The unique API token to look up.
        derive_parent_id (bool): If True, returns parent_id for sub-users. Defaults to True.

    Returns:
        int/str: The resolved user_id or parent_id.

    Raises:
        RuntimeError: If no user is found or a network error occurs.
    """
    try:
        url = get_db_query_endpoint(db_base_url=db_base_url)
        
        async with httpx.AsyncClient() as client:
            # 1. Try fetching from the users table (including parent_id)
            res_users = await client.post(url, json={
                "query": "SELECT id as user_id, parent_id FROM users WHERE api_token = :token AND deleted_at IS NULL LIMIT 1",
                "params": {"token": api_token}
            })
            data_rows = res_users.json().get("rows", [])

            # 2. If not found in users, try user_tokens table (joining users to get parent_id)
            if not data_rows:
                res_tokens = await client.post(url, json={
                    "query": """
                        SELECT t.user_id, u.parent_id 
                        FROM user_tokens t
                        LEFT JOIN users u ON t.user_id = u.id
                        WHERE t.api_token = :token 
                        ORDER BY t.created_at DESC LIMIT 1
                    """,
                    "params": {"token": api_token}
                })
                data_rows = res_tokens.json().get("rows", [])
                
        # Replace the Pandas logic with this:
        if not data_rows:
            logger.error(f"No user_id found for api_token: {api_token}")
            raise RuntimeError("No user_id found from the api_token")

        # data_rows is usually a list of dicts: [{"user_id": 123, "parent_id": 456}]
        row = data_rows[0]

        user_id = row.get("user_id")
        parent_id = row.get("parent_id")

        # Logic: If derive_parent_id is True and parent_id is valid
        if derive_parent_id and parent_id and parent_id != 0:
            final_id = int(parent_id) # Explicit cast to be safe
            logger.info(f"Sub-user detected. Derived parent_id: {final_id}")
        else:
            final_id = int(user_id)
            logger.info(f"Retrieved primary user_id: {final_id}")

        return final_id

    except Exception as e:
        logger.error(f"Error when getting user_id from api_token: {str(e)}")
        raise RuntimeError(f"Error when getting user_id from api_token: {str(e)}")