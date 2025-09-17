import base64, hmac, hashlib, time
import os
import httpx
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from typing import Dict

from fastapi import Header, HTTPException

from src.orin_wa_report.core.utils import get_db_query_endpoint
from dotenv import load_dotenv

# from core.logger import get_logger

# logger = get_logger(__name__)

load_dotenv()

db_api_key = os.getenv("ORIN_DB_API_KEY")
APP_STAGE = os.getenv("APP_STAGE")
SECRET_KEY = os.getenv("SECRET_KEY").encode()
DERIVED_AES_KEY = hashlib.sha256(SECRET_KEY).digest()  # 32 bytes
BLOCK_SIZE = 16

db_query_url = get_db_query_endpoint(name=APP_STAGE)

async def generate_wa_key() -> str:
    """
    Generate opaque API token (≤32 chars) valid for 24h.
    """
    ts_sec = int(time.time())
    ts_bytes = ts_sec.to_bytes(4, "big")  # 4-byte timestamp

    sig = hmac.new(SECRET_KEY, ts_bytes, hashlib.sha256).digest()[:8]  # 8-byte HMAC

    token_bytes = ts_bytes + sig  # total 12 bytes
    token_b64 = base64.urlsafe_b64encode(token_bytes).decode().rstrip("=")

    return token_b64  # ~16 chars, always ≤32


async def verify_wa_key(token: str, max_age_seconds: int = 24 * 3600) -> dict:
    """
    Verify token and check expiry (default 24 hours).
    """
    try:
        # Pad base64 string if stripped
        padded = token + "=" * (-len(token) % 4)
        token_bytes = base64.urlsafe_b64decode(padded)

        if len(token_bytes) != 12:
            raise ValueError("Invalid token length")

        ts_bytes, sig_given = token_bytes[:4], token_bytes[4:]
        ts_sec = int.from_bytes(ts_bytes, "big")

        # Recompute signature
        sig_check = hmac.new(SECRET_KEY, ts_bytes, hashlib.sha256).digest()[:8]
        if not hmac.compare_digest(sig_given, sig_check):
            raise ValueError("Invalid signature")

        ts_now_sec = int(time.time())
        if ts_now_sec - ts_sec >= max_age_seconds:
            raise ValueError("Token expired")

        return {"ts_sec": ts_sec, "ts_now_sec": ts_now_sec}

    except Exception as e:
        raise ValueError(f"Invalid token: {e}")

async def generate_and_store_wa_key(user_id: str):
    
    generated_wa_key = await generate_wa_key()
    query = f"UPDATE users SET wa_key = '{generated_wa_key}' WHERE id = {user_id}; COMMIT;"
    async with httpx.AsyncClient() as client:
        response = await client.post(db_query_url, json={
            "query": query,
            "api_key": db_api_key,
        })
        response_sql: Dict = response.json()
        
    return {
        "wa_key": generated_wa_key,
        "response_sql": response_sql
    }
    
async def verify_wa_key_and_store_wa_number(wa_key: str, wa_number: str):
    verification_result = await verify_wa_key(token=wa_key)
    
    query = f"UPDATE users SET wa_number = '{wa_number}' WHERE wa_key = :wa_key; COMMIT;"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(db_query_url, json={
            "query": query,
            "api_key": db_api_key,
            "params": {"wa_key": wa_key}
        })
        response_sql: Dict = response.json()
        
    return {
        "verification_result": verification_result,
        "response_sql": response_sql
    }
    
    
    
    

if __name__ == '__main__':
    ## Wa Key Generation and Store Key
    # wa_key_generated = asyncio.run(generate_and_store_wa_key(user_id="39790"))
    # print(f"WA Key Generated: {wa_key_generated}")
    
    ## Wa Key Verify and Store/Update Wa Number
    wa_key_verify = asyncio.run(verify_wa_key_and_store_wa_number(
        wa_key="aMqRpXUvsq57XUqq",
        wa_number="6285850434383"
    ))
    print(f"WA Key Verification Result: {wa_key_verify}")