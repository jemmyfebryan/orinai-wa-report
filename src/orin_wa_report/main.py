# main.py
import asyncio
import uvicorn
import yaml
from typing import Dict
from src.orin_wa_report.core.agent.main import run_bot
from src.orin_wa_report.core.api.app import app


with open('config.yaml', 'r') as file:
    config_data: Dict = yaml.safe_load(file)
    
async def main():
    service_tasks = []
    
    # Start bot in background
    if config_data.get("services").get("enable_agent"):
        bot_task = asyncio.create_task(run_bot())
        service_tasks.append(bot_task)

    # Start FastAPI server
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, reload=True)
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())
    service_tasks.append(api_task)

    # Wait for both
    await asyncio.gather(*service_tasks)

if __name__ == "__main__":
    asyncio.run(main())
