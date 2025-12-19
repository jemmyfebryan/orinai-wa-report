import os
import asyncio
import base64
import sqlite3
import random
from pydantic import BaseModel
from typing import List, Dict, Optional

import httpx
import yaml
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.orin_wa_report.core.openwa import SocketClient, WAError

# Import ChatDB for session management
from src.orin_wa_report.core.agent.handler import ChatDB, DB_PATH
from src.orin_wa_report.core.api.routers.demo import router as demo_router
from src.orin_wa_report.core.api.routers.alert import router as alert_router
from src.orin_wa_report.core.api.utils import (
    periodic_dummy_notifications,
    periodic_send_notifications,
    convert_phone_to_lid,
)
from src.orin_wa_report.core.db import SettingsDB, DB_PATH as SETTINGS_DB_PATH, ensure_settings_db
from src.orin_wa_report.core.development import (
    create_notifications,
    create_user
)
from src.orin_wa_report.core.logger import get_logger

from dotenv import load_dotenv
load_dotenv(override=True)

ORINAI_CHAT_ENDPOINT = os.getenv("ORINAI_CHAT_ENDPOINT")

# YAML Config
with open('config.yaml', 'r') as file:
    config_data: Dict = yaml.safe_load(file)
    
# Initialization
# SOCKET_URL = "http://localhost:8002"

# Logger
logger = get_logger(__name__, service="FastAPI")

# FastAPI App
app = FastAPI()

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
    await ChatDB.close()
    await SettingsDB.close()

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
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# OpenWA Proxy
OPEN_WA_PROXY_PORT = os.getenv("OPEN_WA_PROXY_PORT", "8002")  # default port if env var not set
BASE_URL = f"http://172.17.0.1:{OPEN_WA_PROXY_PORT}"
async def proxy_get(path: str):
    url = f"{BASE_URL}/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))

@app.get("/whatsapp/status")
async def get_status():
    return await proxy_get("status")

@app.get("/whatsapp/qr")
async def get_qr():
    return await proxy_get("qr")

@app.get("/whatsapp/qr.png")
async def get_qr_png():
    return await proxy_get("qr.png")

@app.get("/whatsapp/qr/raw")
async def get_qr_raw():
    return await proxy_get("qr/raw")


# OpenWA Client
OPEN_WA_PORT = os.getenv("OPEN_WA_PORT")
openwa_client: SocketClient | None = None

def set_openwa_client(client):
    global openwa_client
    openwa_client = client

# async def init_openwa_client():
#     global openwa_client

#     loop = asyncio.get_event_loop()
#     def blocking_init():
#         global openwa_client
#         openwa_client = SocketClient(f"http://172.17.0.1:{OPEN_WA_PORT}/", api_key="my_secret_api_key")
#         logger.info("OpenWA Client Connected!")

#     await loop.run_in_executor(None, blocking_init)
    
#     logger.info(openwa_client.getMe())

class MessageRequest(BaseModel):
    to: str       # phone number, e.g. "1234567890@c.us"
    to_fallback: Optional[str] = None
    message: str  # message text

@app.post("/send-message")
async def send_message(req: MessageRequest):
    if openwa_client is None:
        raise HTTPException(status_code=503, detail="WhatsApp client not ready")
    try:
        try:
            openwa_client.sendText(req.to, req.message)
        except WAError:
            openwa_client.sendText(req.to_fallback, req.message)
        await chat_db.add_chat_to_latest_session(
            phone_number=req.to.split(sep="@")[0],
            sender="bot",
            message=req.message
        )
        return {"status": "success", "to": req.to, "message": req.message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
    messages: List[MessageRequest]   # list of messages
    delay_seconds: Optional[float] = 0  # optional delay between messages (default: 0)

# --- API Endpoint ---
@app.post("/send-messages")
async def send_messages(req: BulkMessageRequest):
    if openwa_client is None:
        raise HTTPException(status_code=503, detail="WhatsApp client not ready")

    for msg in req.messages:
        await message_queue.put((msg, req.delay_seconds))

    return {"status": "queued", "count": len(req.messages)}

# Dummy Development
@app.post('/dummy/create_user')
async def create_dummy_user(request: Request):
    try:
        # Not allowed by config
        if not config_data.get("dummy").get("enable_create_user"):
            return JSONResponse(content={
                "status": "not allowed",
                "message": "Creating dummy user is not allowed from the server.",
                "data": None
            }, status_code=405)
        
        # Creating dummy user
        data = await request.json()
        
        verified = data.get("verified", False)
        dummy_devices_count = data.get("devices_count", 3)
        
        result = await create_user.create_dummy_user(
            wa_verified=verified,
            dummy_devices_count=dummy_devices_count
        )
        return JSONResponse(content={
            "status": "success",
            "message": "Dummy user created successfully!",
            "data": result
        }, status_code=200)
    except Exception as e:
        return JSONResponse(content={
            "status": "error",
            "message": f"Error when create dummy user: {str(e)}",
            "data": None
        }, status_code=500)

# Frontend Demo
app.include_router(demo_router)
app.include_router(alert_router)

# Notification settings
# Setting Notification routes
@app.get('/notification_setting')
async def get_notification_setting():
    agents = await settings_db.get_notification_setting()
    return JSONResponse(content=agents)

@app.post('/notification_setting')
async def create_notification_setting(request: Request):
    data = await request.json()
    try:
        content = await settings_db.create_notification_setting(data=data)
        return JSONResponse(
            content=content,
            status_code=201
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Setting must be unique")

@app.put('/notification_setting/{setting}')
async def update_notification_setting(setting: str, request: Request):
    data = await request.json()
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
    
@app.delete('/notification_setting/{setting}')
async def delete_notification_setting(setting: str):
    try:
        content = await settings_db.delete_notification_setting(
            setting=setting
        )
        return JSONResponse(content=content)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

# Alert Settings
class ApplySettings(BaseModel):
    enable_create_dummy_alert: bool
    enable_send_alert: bool

@app.get("/settings")
def get_settings():
    # logger.info(f"Get Setting, config_data: {config_data}")
    enable_create_dummy_alert = config_data.get("dummy").get("enable_create_alert", False)
    enable_send_alert = config_data.get("fastapi").get("enable_send_alert", False)
    
    settings = {
        "enable_create_dummy_alert": enable_create_dummy_alert,
        "enable_send_alert": enable_send_alert,
    }
    
    return settings

@app.post("/settings")
def apply_settings(payload: ApplySettings):
    config_data["dummy"]["enable_create_alert"] = payload.enable_create_dummy_alert
    config_data["fastapi"]["enable_send_alert"] = payload.enable_send_alert
    
    settings = {
        "enable_create_dummy_alert": payload.enable_create_dummy_alert,
        "enable_send_alert": payload.enable_send_alert,
    }
    
    return {"ok": True, "settings": settings}

# New routes for chat history and sessions
@app.get("/whatsapp/chat_history/{phone_number}")
async def get_chat_history(phone_number: str):
    """
    Fetch ALL chat history for a phone number across all sessions
    Returns: List of messages with session markers and timestamps
    """
    # Get all sessions for this phone number
    sessions = await chat_db.get_sessions_by_phone(phone_number, limit=5)
    if not sessions:
        return []
    
    # Format messages with session markers
    openai_messages = []
    for session in sessions:
        # Add session marker
        openai_messages.append({
            "role": "session",
            "content": session['id']
        })
        
        # Get messages for this session
        messages = await chat_db.get_messages_for_session(session['id'])
        # Sort messages by timestamp (oldest first)
        messages.sort(key=lambda x: x['timestamp'])
        for msg in messages:
            role = "assistant" if msg['sender'] == 'bot' else 'user'
            openai_messages.append({
                "role": role,
                "content": msg['body'],
                "timestamp": msg['timestamp']
            })
    
    return openai_messages

@app.get("/whatsapp/phone_to_lid/{phone_number}")
async def get_phone_to_lid(phone_number: str):
    """
    Fetch ALL chat history for a phone number across all sessions
    Returns: List of messages with session markers and timestamps
    """
    try:
        lid_number = await convert_phone_to_lid(
            phone_number=phone_number
        )
        
        return JSONResponse(content={
            "status": "success",
            "message": "Succesfully convert phone number to lid number",
            "lid_number": lid_number
        }, status_code=200)
    except Exception as e:
        return JSONResponse(content={
            "status": "error",
            "message": f"Error when convert phone number to lid number: {str(e)}",
            "lid_number": None
        }, status_code=500)

@app.get("/whatsapp/contacts")
async def get_contacts():
    """
    Fetch all phone numbers that have chat history
    Returns: List of dicts with key "phone_number"
    """
    # Query distinct phone numbers from sessions
    def _get_phones():
        cur = chat_db._conn.cursor()
        cur.execute("SELECT DISTINCT phone FROM sessions")
        return [row[0] for row in cur.fetchall()]
    
    phones = await chat_db._run(_get_phones)
    return [{"phone_number": phone} for phone in phones]

@app.get("/whatsapp/sessions/{phone_number}")
async def get_sessions(phone_number: str):
    """
    Fetch all session IDs for a phone number
    Returns: List of session IDs (strings)
    """
    # Query sessions for phone number
    def _get_sessions():
        cur = chat_db._conn.cursor()
        cur.execute(
            "SELECT id FROM sessions WHERE phone = ? ORDER BY started_at DESC",
            (phone_number,)
        )
        return [row[0] for row in cur.fetchall()]
    
    session_ids = await chat_db._run(_get_sessions)
    return session_ids

@app.get("/whatsapp/chat_history_by_session/{session_id}")
async def get_chat_history_by_session(session_id: str):
    """
    Fetch chat history by session ID in OpenAI format with timestamps
    Returns: List of messages with 'role', 'content', and 'timestamp'
    """
    messages = await chat_db.get_messages_for_session(session_id)
    if not messages:
        return []
    
    # Format messages for OpenAI with timestamps
    openai_messages = []
    # Sort messages by timestamp (oldest first)
    messages.sort(key=lambda x: x['timestamp'])
    for msg in messages:
        role = "assistant" if msg['sender'] == 'bot' else 'user'
        openai_messages.append({
            "role": role,
            "content": msg['body'],
            "timestamp": msg['timestamp']
        })
    
    return openai_messages


@app.get("/whatsapp/profile/{phone_number}")
async def get_profile(phone_number: str):
    """
    Fetch ALL chat history for a phone number across all sessions
    Returns: List of messages with session markers and timestamps
    """
    
    global openwa_client
    
    contact_details = openwa_client.getContact(f"{phone_number}@c.us")
    if contact_details is None:
        contact_details = openwa_client.getContact(f"{phone_number}@lid")
    
    profile_url = contact_details.get("profilePicThumbObj", "")
    # logger.info(f"Profile Url: {profile_url}")
    if profile_url: profile_url = profile_url.get("eurl")
    contact_name = contact_details.get("name", "Unnamed")
    
    push_name = contact_details.get("pushname", "Unnamed")
    is_business = "Yes" if contact_details.get("isBusiness") else "No"
    is_my_contact = "Yes" if contact_details.get("isMyContact") else "No"
    
    description = f"Push Name: {push_name}, Business Account: {is_business}, In Contact: {is_my_contact}"
    
    # async with httpx.AsyncClient() as client:
    #     response = await client.get(profile_url)
    #     response.raise_for_status()
    #     image_bytes = response.content

    #     # Convert to Base64
    #     image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    #     # Try to detect MIME type from headers
    #     mime_type = response.headers.get("Content-Type", "image/jpeg")
    #     profile_image = f"data:{mime_type};base64,{image_base64}"
    
    # Placeholder
    return {
        "profile_image": profile_url,
        "contact_name": contact_name,
        "description": description
    }
    
@app.post("/whatsapp/dummy_notification")
async def wa_dummy_notification(request: Request):
    data = await request.json()
    number_type = data.get("number_type")
    to = data.get("to")
    if number_type == "lid":
        to = f"{to}@lid"
    else:
        to = f"{to}@c.us"
    alert_type: str = data.get("alert_type")
    
    # async with httpx.AsyncClient() as client:
    #     resp = await client.get(f"{ORINAI_CHAT_ENDPOINT}/notification_setting")
    #     resp_json: List[Dict] = resp.json()
        
    resp_json = await settings_db.get_notification_setting()
        
    alert_setting = [val for val in resp_json if val.get("setting") == f"prompt_{alert_type}"]
    if len(alert_setting) == 0:
        alert_setting = [val for val in resp_json if val.get("setting") == "prompt_default"]
    alert_setting = alert_setting[0]
    
    prompt_device_name = random.choice(["Truk", "Pesawat", "Bis", "Sepeda"])
    prompt_message = (alert_type.replace("_", " ").replace("-", "")).title()
        
    message_final = alert_setting["value"].format(device_name=prompt_device_name, message=prompt_message)
    
    if openwa_client is None:
        raise HTTPException(status_code=503, detail="WhatsApp client not ready")

    try:
        openwa_client.sendText(to, message_final)
        return {"status": "success", "to": to, "message": message_final}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/whatsapp/disable_agent/{phone_number}")
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
    
@app.put("/whatsapp/disable_agent")
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