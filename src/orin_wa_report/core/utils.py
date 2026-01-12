import os
import json
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