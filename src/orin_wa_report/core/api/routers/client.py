import os
import random

import httpx
from fastapi import APIRouter, Response, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

from src.orin_wa_report.core.agent.handler import ChatDB, get_chat_db
from src.orin_wa_report.core.db import SettingsDB, get_settings_db
from src.orin_wa_report.core.openwa import SocketClient, WAError
from src.orin_wa_report.core.clients import get_openwa_client
from src.orin_wa_report.core.models import SendMessageRequest, SendFileRequest
from src.orin_wa_report.core.api.utils import (
    convert_phone_to_lid,
)

from dotenv import load_dotenv
load_dotenv(override=True)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp-client"], include_in_schema=True)

# OpenWA Proxy
OPEN_WA_PROXY_PORT = os.getenv("OPEN_WA_PROXY_PORT", "8002")  # default port if env var not set
BASE_URL = f"http://172.17.0.1:{OPEN_WA_PROXY_PORT}"
async def proxy_get(path: str):
    url = f"{BASE_URL}/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))

@router.get(
    path="/status",
)
async def get_status():
    return await proxy_get("status")

@router.get(
    path="/qr",
)
async def get_qr():
    return await proxy_get("qr")

@router.get(
    path="/qr.png",
)
async def get_qr_png():
    return await proxy_get("qr.png")

@router.get(
    path="/qr/raw",
)
async def get_qr_raw():
    return await proxy_get("qr/raw")


@router.post(
    path="/send_message",
    include_in_schema=True,
)
async def send_message(
    req: SendMessageRequest,
    openwa_client: SocketClient = Depends(get_openwa_client),
    chat_db: ChatDB = Depends(get_chat_db),
):
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

@router.post(
    path="/send_file",
    include_in_schema=True,
)
async def send_file(
    req: SendFileRequest,
    openwa_client: SocketClient = Depends(get_openwa_client),
):
    if openwa_client is None:
        raise HTTPException(status_code=503, detail="WhatsApp client not ready")

    # Define the helper to call the function positionally
    def call_send_file(target_to):
        # We pass only the values in the specific order the library expects:
        # 1. to, 2. file, 3. filename, 4. caption
        return openwa_client.sendFile(
            target_to, 
            req.file, 
            req.filename, 
            req.caption
        )

    try:
        try:
            # Try with primary 'to'
            result = call_send_file(req.to)
        except Exception:
            # Try with fallback if primary fails
            if req.to_fallback:
                result = call_send_file(req.to_fallback)
            else:
                raise
            
        return JSONResponse(
            content={"status": "success", "result": str(result)},
            status_code=200, # Changed to 200 for success
        )
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "detail": str(e)},
            status_code=500,
        )


# New routes for chat history and sessions
@router.get(
    path="/chat_history/{phone_number}",
    include_in_schema=False,
)
async def get_chat_history(
    phone_number: str,
    chat_db: ChatDB = Depends(get_chat_db),
):
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


@router.get(
    path="/whatsapp/phone_to_lid/{phone_number}",
    include_in_schema=False,
)
async def get_phone_to_lid(
    phone_number: str,
    chat_db: ChatDB = Depends(get_chat_db),
):
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

@router.get(
    path="/whatsapp/contacts",
    include_in_schema=False,
)
async def get_contacts(
    chat_db: ChatDB = Depends(get_chat_db),
):
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

@router.get(
    path="/whatsapp/sessions/{phone_number}",
    include_in_schema=False,
)
async def get_sessions(
    phone_number: str,
    chat_db: ChatDB = Depends(get_chat_db),
):
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

@router.get(
    path="/whatsapp/chat_history_by_session/{session_id}",
    include_in_schema=False,
)
async def get_chat_history_by_session(
    session_id: str,
    chat_db: ChatDB = Depends(get_chat_db),
):
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


@router.get(
    path="/whatsapp/profile/{phone_number}",
    include_in_schema=False,
)
async def get_profile(
    phone_number: str,
    openwa_client: SocketClient = Depends(get_openwa_client),
):
    """
    Fetch ALL chat history for a phone number across all sessions
    Returns: List of messages with session markers and timestamps
    """
    
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
    
    # Placeholder
    return {
        "profile_image": profile_url,
        "contact_name": contact_name,
        "description": description
    }
    
@router.post(
    path="/whatsapp/dummy_notification",
    include_in_schema=False,
)
async def wa_dummy_notification(
    request: Request,
    settings_db: SettingsDB = Depends(get_settings_db),
    openwa_client: SocketClient = Depends(get_openwa_client),
):
    data = await request.json()
    number_type = data.get("number_type")
    to = data.get("to")
    if number_type == "lid":
        to = f"{to}@lid"
    else:
        to = f"{to}@c.us"
    alert_type: str = data.get("alert_type")
    
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
    