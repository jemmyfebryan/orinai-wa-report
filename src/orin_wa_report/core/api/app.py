import os
import asyncio
import logging
from pydantic import BaseModel
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer

from src.orin_wa_report.core.openwa import WAError

from src.orin_wa_report.core.config import get_config_data
from src.orin_wa_report.core.clients import get_openwa_client
from src.orin_wa_report.core.agent.handler import ChatDB, DB_PATH
from src.orin_wa_report.core.api.routers.client import router as client_router
from src.orin_wa_report.core.api.routers.alert import router as alert_router
from src.orin_wa_report.core.api.routers.dev import router as dev_router
from src.orin_wa_report.core.api.routers.dashboard import router as dashboard_router
from src.orin_wa_report.core.api.utils import (
    periodic_dummy_notifications,
    periodic_send_notifications,
)
from src.orin_wa_report.core.db import SettingsDB, DB_PATH as SETTINGS_DB_PATH
from src.orin_wa_report.core.models import SendMessageRequest
from src.orin_wa_report.core.logger import get_logger

from dotenv import load_dotenv
load_dotenv(override=True)

ORINAI_CHAT_ENDPOINT = os.getenv("ORINAI_CHAT_ENDPOINT")

config_data = get_config_data()
    
# Initialization
# SOCKET_URL = "http://localhost:8002"

# Bearer Token Security
security = HTTPBearer()

# Logger
logger = get_logger(__name__, service="FastAPI")

# FastAPI App
app = FastAPI()

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Only log requests that are NOT to /settings
        return "/settings" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# Initialize ChatDB for session management
chat_db = ChatDB(DB_PATH)

# Initialize SettingDB for setting management
settings_db = SettingsDB(SETTINGS_DB_PATH)

# Periodic Task
@app.on_event("startup")
async def start_background_task():
    # Initialize chat database
    await chat_db.initialize()
    
    # Initialize settings database
    await settings_db.initialize()
    
    # Initialize openwa_client
    # asyncio.create_task(init_openwa_client())
    
    # Message Queue for Bulk Messages
    asyncio.create_task(message_worker())
    
    # Dummy alert notifications creating
    asyncio.create_task(periodic_dummy_notifications())
    
    # Send Alert to ORIN Subscribers
    asyncio.create_task(periodic_send_notifications())
        
# Disconnect gracefully on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    openwa_client.disconnect()
    await chat_db.close()
    await settings_db.close()

# Configure CORS with allowed origins
origins = os.getenv('CORS_ORIGINS', '').split(',')
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates
templates = Jinja2Templates(directory="src/orin_wa_report/web/templates")

# Static files
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="src/orin_wa_report/web/static"), name="static")

# Endpoints
@app.get(
    path="/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Clients
openwa_client = get_openwa_client()

## Bulk Messages
message_queue = asyncio.Queue()

# --- Worker that runs in background ---
async def message_worker():
    while True:
        msg, delay = await message_queue.get()
        try:
            try:
                openwa_client.sendText(msg.to, msg.message)
            except WAError:
                openwa_client.sendText(msg.to_fallback, msg.message)
            logger.info(f"Message worker to {msg.to} with delay {delay}")
        except Exception as e:
            print(f"❌ Failed to send {msg.to}: {e}")
        if delay and delay > 0:
            await asyncio.sleep(delay)
        message_queue.task_done()

class BulkMessageRequest(BaseModel):
    messages: List[SendMessageRequest]   # list of messages
    delay_seconds: Optional[float] = 0  # optional delay between messages (default: 0)

# --- API Endpoint ---
@app.post(
    path="/send-messages",
    include_in_schema=False,
)
async def send_messages(req: BulkMessageRequest):
    if openwa_client is None:
        raise HTTPException(status_code=503, detail="WhatsApp client not ready")

    for msg in req.messages:
        await message_queue.put((msg, req.delay_seconds))

    return {"status": "queued", "count": len(req.messages)}

# Frontend Demo
# app.include_router(demo_router)
app.include_router(alert_router)
app.include_router(client_router)
app.include_router(dashboard_router)
app.include_router(dev_router)

# Alert Settings
class ApplySettings(BaseModel):
    enable_create_dummy_alert: bool
    enable_send_alert: bool

@app.get(
    path="/settings",
    include_in_schema=False,
)
def get_settings():
    # logger.info(f"Get Setting, config_data: {config_data}")
    enable_create_dummy_alert = config_data.get("dummy").get("enable_create_alert", False)
    enable_send_alert = config_data.get("fastapi").get("enable_send_alert", False)
    
    settings = {
        "enable_create_dummy_alert": enable_create_dummy_alert,
        "enable_send_alert": enable_send_alert,
    }
    
    return settings

@app.post(
    path="/settings",
    include_in_schema=False,
)
def apply_settings(payload: ApplySettings):
    config_data["dummy"]["enable_create_alert"] = payload.enable_create_dummy_alert
    config_data["fastapi"]["enable_send_alert"] = payload.enable_send_alert
    
    settings = {
        "enable_create_dummy_alert": payload.enable_create_dummy_alert,
        "enable_send_alert": payload.enable_send_alert,
    }
    
    return {"ok": True, "settings": settings}

@app.get(
    path="/whatsapp/disable_agent/{phone_number}",
    include_in_schema=False,
)
async def get_disable_agent(phone_number: str):
    disable_agent = await chat_db.get_config(
        phone=phone_number,
        key="disable_agent",
        create_if_not_exists=True,
    )
    
    return {
        "phone_number": phone_number,
        "disable_agent": disable_agent,
    }
    
class DisableAgentUpdate(BaseModel):
    """
    Defines the request body for updating only the 'disable_agent' flag.
    """
    phone_number: str
    disable_agent: bool
    
@app.put(
    path="/whatsapp/disable_agent",
    include_in_schema=False,
)
async def update_disable_agent(data: DisableAgentUpdate):
    """
    Updates the 'disable_agent' configuration value for a specific phone number.
    Creates a config row if it doesn't exist.
    """
    
    # 1. Prepare the dictionary for update_config: {"disable_agent": True/False}
    update_values = {
        "disable_agent": data.disable_agent
    }
    
    # 2. Call the update_config method
    await chat_db.update_config(
        phone=data.phone_number,
        values=update_values,
        create_if_not_exists=True, # Ensure a row exists or is created before updating
    )
    
    # 3. Return a confirmation response
    return {
        "status": "success",
        "phone_number": data.phone_number,
        "disable_agent_new_value": data.disable_agent,
    }