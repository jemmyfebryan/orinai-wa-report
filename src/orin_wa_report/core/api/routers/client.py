import os

import httpx
from fastapi import APIRouter, Response

from dotenv import load_dotenv
load_dotenv(override=True)

router = APIRouter(prefix="/client", tags=["whatsapp-client"], include_in_schema=True)

# OpenWA Proxy
OPEN_WA_PROXY_PORT = os.getenv("OPEN_WA_PROXY_PORT", "8002")  # default port if env var not set
BASE_URL = f"http://172.17.0.1:{OPEN_WA_PROXY_PORT}"
async def proxy_get(path: str):
    url = f"{BASE_URL}/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))

@router.get(
    path="/whatsapp/status",
)
async def get_status():
    return await proxy_get("status")

@router.get(
    path="/whatsapp/qr",
)
async def get_qr():
    return await proxy_get("qr")

@router.get(
    path="/whatsapp/qr.png",
)
async def get_qr_png():
    return await proxy_get("qr.png")

@router.get(
    path="/whatsapp/qr/raw",
)
async def get_qr_raw():
    return await proxy_get("qr/raw")
