import sqlite3

from typing import Dict

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse

from src.orin_wa_report.core.db import SettingsDB, get_settings_db

from dotenv import load_dotenv
load_dotenv(override=True)

router = APIRouter(prefix="", tags=["dashboard-client"], include_in_schema=True)


# Notification settings
# Setting Notification routes
@router.get(
    path='/notification_setting',
)
async def get_notification_setting(
    settings_db: SettingsDB = Depends(get_settings_db),
):
    agents = await settings_db.get_notification_setting()
    return JSONResponse(content=agents)

@router.post(
    path='/notification_setting',
)
async def create_notification_setting(
    request: Request,
    settings_db: SettingsDB = Depends(get_settings_db),
):
    data: Dict[str, str] = await request.json()
    
    if data.get("setting") == "allowed_alert_type":
        raise HTTPException(status_code=400, detail="Creating allowed_alert_type setting is prohibited")

    try:
        content = await settings_db.create_notification_setting(data=data)
        return JSONResponse(
            content=content,
            status_code=201
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Setting must be unique")

@router.put(
    path='/notification_setting/{setting}',
)
async def update_notification_setting(
    setting: str,
    request: Request,
    settings_db: SettingsDB = Depends(get_settings_db),
):
    data: Dict[str, str] = await request.json()
    
    # Value validation for allowed_alert_type
    if data.get("setting") == "allowed_alert_type":
        try:
            value = data.get("value")
            value_split = value.split(sep=";")
            assert isinstance(value_split, list)
        except:
            raise HTTPException(status_code=400, detail="allowed_alert_type must be a string separated by ';'")
    
    try:
        content = await settings_db.update_notification_setting(
            setting=setting,
            data=data
        )
        return JSONResponse(
            content=content
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Setting must be unique")
    
@router.delete(
    path='/notification_setting/{setting}',
)
async def delete_notification_setting(
    setting: str,
    settings_db: SettingsDB = Depends(get_settings_db),
):
    if setting == "allowed_alert_type":
        raise HTTPException(status_code=400, detail="Deleting allowed_alert_type setting is prohibited")

    try:
        content = await settings_db.delete_notification_setting(
            setting=setting
        )
        return JSONResponse(content=content)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
