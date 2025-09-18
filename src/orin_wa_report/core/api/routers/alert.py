import uuid
import os
from pydantic import BaseModel
from typing import List, Dict, Optional

import pandas as pd
import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.orin_wa_report.core.development.create_user import create_dummy_user
from src.orin_wa_report.core.utils import get_db_query_endpoint
from src.orin_wa_report.core.logger import get_logger

from dotenv import load_dotenv
load_dotenv(override=True)

logger = get_logger(__name__, service="FastAPI")

APP_STAGE = os.getenv("APP_STAGE")

# Implement fetch BOT Number from Socket Client, otherwise its default to environment
BOT_PHONE_NUMBER = os.getenv("BOT_PHONE_NUMBER")

logger.info(f"BOT_PHONE_NUMBER: {BOT_PHONE_NUMBER}")

ORIN_DB_API_KEY = os.getenv("ORIN_DB_API_KEY", None)

router = APIRouter(prefix="/alert", tags=["alert"])
security = HTTPBearer()

# Bearer Token Security
def get_bearer_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Extract and return the Bearer token from the request.
    """
    if not credentials.scheme.lower() == "bearer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication scheme",
        )
    return credentials.credentials

# Pydantic models
class CreateUser(BaseModel):
    name: str
    email: str | None = None
    verified: bool = False
    wa_number: str | None = None
    mimic_user: str | None = "None"
    
async def get_users_util(url: str) -> Dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "query": """
                SELECT
                    id,
                    name,
                    email,
                    api_token,
                    wa_key,
                    wa_notif,
                    wa_number,
                    wa_verified
                FROM users
                WHERE
                    name LIKE 'OrinAI%'
                    AND deleted_at IS NULL
            """
        })
        response_sql: Dict = response.json()
    return response_sql

# Routes
@router.get("/users")
async def get_users():
    # Forbidden for Production
    if APP_STAGE == "production":
        return JSONResponse(content={
            "status": "error",
            "message": "Creating user with is Forbidden on production stage!"
        }, status_code=403)
    
    url = get_db_query_endpoint(name=APP_STAGE)
    response_sql = await get_users_util(url=url)
    return response_sql.get("rows")

@router.post("/users/create")
async def create_user(payload: CreateUser):
    mimic_user = payload.mimic_user or "None"
    
    url_stage = get_db_query_endpoint(name=APP_STAGE)
    url_prod = get_db_query_endpoint(name="production")
    
    # Get api_token from mimic_user
    if mimic_user != "None":
        async with httpx.AsyncClient() as client:
            response = await client.post(url_prod, json={
                "query": """
                    SELECT id, api_token
                    FROM users
                    WHERE
                        id = :id
                        AND deleted_at IS NULL
                    LIMIT 1
                """,
                "params": {"id": mimic_user}
            })
            response_sql: Dict = response.json()
        mimic_token = response_sql.get("rows")[0].get("api_token")
        
        
        # Check if users token already taken
        response_users = await get_users_util(url=url_stage)
        df_response_users = pd.DataFrame(response_users.get("rows"))
        
        logger.info(f"Creating demo user: df_response_user: {str(df_response_users)}")
        
        if len(df_response_users) != 0:
            if mimic_token in df_response_users["api_token"].tolist():
                raise HTTPException(status_code=409, detail="mimic_user already taken")
    else:
        mimic_token = None
    
    logger.info(f"Demo creating user: mimic_token: {mimic_token}")

    if payload.verified and not payload.wa_number:
        raise HTTPException(status_code=400, detail="verified users must provide wa_number")
    
    # Insert new users
    phone_number = payload.wa_number if payload.verified else ""
    result = await create_dummy_user(
        wa_verified=payload.verified,
        name=payload.name,
        phone_number=phone_number,
        api_token=mimic_token,
        dummy_devices_count=3
    )

    new = {
        "id": result.get("user_id"),
        "name": payload.name,
        "email": payload.email or f"{payload.name.lower().replace(' ','.')}@example.com",
        "api_token": str(uuid.uuid4()),
        "wa_key": None,
        "wa_notif": 1 if payload.verified else 0,
        "wa_number": payload.wa_number or "",
        "wa_verified": 1 if payload.verified else 0
    }
    return {"ok": True, "user": new}

@router.post("/users/{user_id}/delete")
async def delete_user(user_id: int):
    # Forbidden for Production
    if APP_STAGE == "production":
        return JSONResponse(content={
            "status": "error",
            "message": "Deleting user with is Forbidden on production stage!"
        }, status_code=403)
    
    # Deleting a user
    try:
        url = get_db_query_endpoint(name=APP_STAGE)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "query": """
                    UPDATE users
                    SET
                        deleted_at = NOW(),
                        api_token = NULL,
                        wa_key = "",
                        wa_notif = 0,
                        wa_number = "",
                        wa_verified = 0
                    WHERE id = :id; COMMIT;
                """,
                "params": {"id": user_id},
                "api_key": ORIN_DB_API_KEY
            })
            response_sql: Dict = response.json()
        
        return {"ok": True, "status": "success", "message": response_sql}
    except Exception as e:
        return JSONResponse(content={
            "ok": False,
            "status": "error",
            "message": f"Error when deleting user: {str(e)}"
        }, status_code=500)


from src.orin_wa_report.core.development.verify_wa import (
    generate_and_store_wa_key
)

@router.post("/users/verify")
async def verify_user(token: str = Depends(get_bearer_token)):
    try:
        url = get_db_query_endpoint(name=APP_STAGE)
        
        # Get user_id from Bearer token
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "query": """
                    SELECT id, api_token
                    FROM users
                    WHERE
                        api_token = :api_token
                        AND deleted_at IS NULL
                    LIMIT 1
                """,
                "params": {"api_token": token}
            })
            response_sql: Dict = response.json()
            
        user_id = response_sql.get("rows")[0].get("id")
        
        if len(response_sql.get("rows")) == 0:
            return JSONResponse(content={
                "ok": False,
                "status": "error",
                "message": "User not found",
                "key": None,
                "bot_number": None,
                "wa_url": None
            }, status_code=404)
        
        wa_key_response = await generate_and_store_wa_key(user_id=user_id)
        wa_key = wa_key_response.get("wa_key")
        
        wa_message = f"Verifikasi ORIN Alert: {wa_key}"
        wa_url = f'https://wa.me/{BOT_PHONE_NUMBER}?text={wa_message}'
        return {
            "ok": True,
            "status": "success",
            "message": f"Successfully send wa_key and wa_url",
            "key": wa_key,
            "bot_number": BOT_PHONE_NUMBER,
            "wa_url": wa_url
        }
    except Exception as e:
        return JSONResponse(content={
            "ok": False,
            "status": "error",
            "message": f"Error when verifying user: {str(e)}",
            "key": None,
            "bot_number": None,
            "wa_url": None
        }, status_code=500)

# Unsubscribe
@router.post("/users/unsubscribe")
async def unsubscribe_user(token: str = Depends(get_bearer_token)):
    try:
        url = get_db_query_endpoint(name=APP_STAGE)
        
        query = """
            UPDATE users
            SET
                wa_notif = 0,
                wa_verified = 0,
                wa_number = "",
                wa_key = ""
            WHERE
                api_token = :api_token
                AND deleted_at IS NULL;
            COMMIT;
        """
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "query": query,
                "params": {
                    "api_token": token
                },
                "api_key": ORIN_DB_API_KEY,
            })
            
        response.raise_for_status()
        response_sql = response.json()
        
        logger.info(f"User token {token} unsubscribed: {response_sql}")
        return {
            "ok": True,
            "status": "success",
            "message": "Successfully unsubscribe user."
        }
    except Exception as e:
        return JSONResponse(content={
            "ok": False,
            "status": "error",
            "message": f"Error when unsubscribe user {str(e)}",
        }, status_code=500)
    # global df
    # idx = df.index[df["id"] == user_id]
    # if idx.empty:
    #     raise HTTPException(status_code=404, detail="user not found")
    # idx = idx[0]
    # df.at[idx, "wa_notif"] = 0
    # df.at[idx, "wa_verified"] = 0
    # df.at[idx, "wa_key"] = None
    # return {"ok": True}

# Toggle Notification
class ToggleRequest(BaseModel):
    toggle: int  # 0 or 1
    
@router.get("/users/toggle_notif")
async def get_toggle_notif(token: str = Depends(get_bearer_token)):
    try:
        url = get_db_query_endpoint(name=APP_STAGE)
        
        query = "SELECT wa_notif FROM users WHERE api_token = :api_token AND deleted_at IS NULL LIMIT 1;"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "query": query,
                "params": {
                    "api_token": token
                }
            })
        
        response.raise_for_status()
        response_sql = response.json()
        
        wa_notif = response_sql.get("rows")[0].get("wa_notif")
        
        logger.info(f"User token {token} GET wa_notif: {wa_notif}: {response_sql}")
        
        return {
            "ok": True,
            "status": "success",
            "message": "Notification fetched successfully",
            "toggle": wa_notif
        }
    except Exception as e:
        return JSONResponse(content={
            "ok": False,
            "status": "error",
            "message": f"Error when fetch toggle: {str(e)}",
            "toggle": None
        }, status_code=500)
        
@router.post("/users/toggle_notif")
async def set_toggle_notif(payload: ToggleRequest, token: str = Depends(get_bearer_token)):
    try:
        url = get_db_query_endpoint(name=APP_STAGE)
        
        desired_toggle = payload.toggle
        
        query = "UPDATE users SET wa_notif = :desired_toggle WHERE api_token = :api_token AND deleted_at IS NULL; COMMIT;"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "query": query,
                "params": {
                    "desired_toggle": desired_toggle,
                    "api_token": token
                },
                "api_key": ORIN_DB_API_KEY,
            })
        
        response.raise_for_status()
        response_sql: Dict = response.json()
        
        logger.info(f"Toggled for api_token: {token} to {desired_toggle}: {response_sql}")
        
        return {
            "ok": True,
            "status": "success",
            "message": "Notification toggled successfully",
            "toggle": desired_toggle
        }
    except Exception as e:
        return JSONResponse(content={
            "ok": False,
            "status": "error",
            "message": f"Error when toggle notif: {str(e)}",
            "toggle": None
        }, status_code=500)
