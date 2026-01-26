# main.py
import asyncio
import uvicorn
import yaml
import os
from typing import Dict
from src.orin_wa_report.core.openwa import SocketClient
from src.orin_wa_report.core.agent.main import run_bot
from src.orin_wa_report.core.api.app import app
from src.orin_wa_report.core.clients import init_openwa, get_openwa_client

from dotenv import load_dotenv
load_dotenv(override=True)

OPEN_WA_PORT = os.getenv("OPEN_WA_PORT")

with open('config.yaml', 'r') as file:
    config_data: Dict = yaml.safe_load(file)

async def main():
    # 1. Setup the API Task
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, reload=False)
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    # 2. Define the background worker for OpenWA
    async def openwa_worker():
        print("⏳ Connecting to OpenWA in background...")
        # If init_openwa is 'async def', await it directly. 
        # If it's a regular 'def', use await asyncio.to_thread(init_openwa)
        await init_openwa() 
        
        client = get_openwa_client()
        if client and config_data.get("services").get("enable_agent"):
            print("🚀 OpenWA Connected. Starting Bot...")
            await run_bot(client)

    # 3. Fire the worker task - this is NON-BLOCKING
    asyncio.create_task(openwa_worker())

    # 4. Keep the main loop alive with the API task
    await api_task

if __name__ == "__main__":
    asyncio.run(main())
