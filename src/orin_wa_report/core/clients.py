import os
import asyncio
from src.orin_wa_report.core.openwa import SocketClient

# OpenWA Client
OPEN_WA_PORT = os.getenv("OPEN_WA_PORT")
openwa_client: SocketClient | None = None

async def init_openwa():
    """Background task to initialize the client without blocking main flow."""
    global openwa_client
    try:
        # If SocketClient is blocking/synchronous, use to_thread
        # If it's native async, just await it directly
        client = await asyncio.to_thread(
            SocketClient, 
            f"http://172.17.0.1:{OPEN_WA_PORT}/", 
            api_key="my_secret_api_key"
        )
        openwa_client = client
        print("✅ OpenWA Client connected in background.")
    except Exception as e:
        print(f"❌ Failed to connect OpenWA: {e}")
    
def get_openwa_client():
    print(openwa_client)
    return openwa_client
