# main.py
import asyncio
import uvicorn
import yaml
import os
from typing import Dict
from src.orin_wa_report.core.openwa import SocketClient
from src.orin_wa_report.core.agent.main import run_bot
from src.orin_wa_report.core.api.app import app, set_openwa_client

from dotenv import load_dotenv
load_dotenv(override=True)

OPEN_WA_PORT = os.getenv("OPEN_WA_PORT")

with open('config.yaml', 'r') as file:
    config_data: Dict = yaml.safe_load(file)

def init_openwa():
    return SocketClient(
        f"http://172.17.0.1:{OPEN_WA_PORT}/",
        api_key="my_secret_api_key",
    )
    
async def main():
    openwa_client = await asyncio.to_thread(init_openwa)
    
    set_openwa_client(openwa_client)
    
    if config_data.get("services").get("enable_agent"):
        bot_task = asyncio.create_task(run_bot(openwa_client))
    
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, reload=False)
    api_task = asyncio.create_task(uvicorn.Server(config).serve())
    
    await asyncio.gather(bot_task, api_task)
    
    # service_tasks = []
    
    # # Start FastAPI server
    # config = uvicorn.Config(app, host="0.0.0.0", port=8000, reload=True)
    # server = uvicorn.Server(config)
    # api_task = asyncio.create_task(server.serve())
    # service_tasks.append(api_task)
    
    # # Start bot in background
    # if config_data.get("services").get("enable_agent"):
    #     bot_task = asyncio.create_task(run_bot())
    #     service_tasks.append(bot_task)

    # # Wait for both
    # await asyncio.gather(*service_tasks)

if __name__ == "__main__":
    asyncio.run(main())
