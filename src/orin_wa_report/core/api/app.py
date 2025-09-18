import os
import asyncio
import httpx
from pydantic import BaseModel
from typing import List, Dict, Optional

import yaml
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from wa_automate_socket_client import SocketClient

from src.orin_wa_report.core.api.routers.demo import router as demo_router
from src.orin_wa_report.core.api.routers.alert import router as alert_router
from src.orin_wa_report.core.api.utils import (
    periodic_dummy_notifications,
    periodic_send_notifications
)
from src.orin_wa_report.core.development import (
    create_notifications,
    create_user
)
from src.orin_wa_report.core.logger import get_logger

from dotenv import load_dotenv
load_dotenv(override=True)

# YAML Config
with open('config.yaml', 'r') as file:
    config_data: Dict = yaml.safe_load(file)
    
# Initialization
# SOCKET_URL = "http://localhost:8002"

# Logger
logger = get_logger(__name__, service="FastAPI")

# FastAPI App
app = FastAPI()

# Periodic Task
@app.on_event("startup")
async def start_background_task():
    # Initialize openwa_client
    asyncio.create_task(init_openwa_client())
    
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
openwa_client = None

async def init_openwa_client():
    global openwa_client

    loop = asyncio.get_event_loop()
    def blocking_init():
        global openwa_client
        openwa_client = SocketClient(f"http://172.17.0.1:{OPEN_WA_PORT}/", api_key="my_secret_api_key")
        logger.info("OpenWA Client Connected!")

    await loop.run_in_executor(None, blocking_init)

class MessageRequest(BaseModel):
    to: str       # phone number, e.g. "1234567890@c.us"
    message: str  # message text

@app.post("/send-message")
async def send_message(req: MessageRequest):
    if openwa_client is None:
        raise HTTPException(status_code=503, detail="WhatsApp client not ready")

    try:
        openwa_client.sendText(req.to, req.message)
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
            openwa_client.sendText(msg.to, msg.message)
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