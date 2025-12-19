import asyncio
import re
import os
import signal
from src.orin_wa_report.core.openwa import SocketClient
from src.orin_wa_report.core.openai import create_client
from src.orin_wa_report.core.agent.listener import ChatBotHandler
from src.orin_wa_report.core.agent.handler import (
    register_conv_handler,
)
from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__, service="Agent")

from dotenv import load_dotenv
load_dotenv(override=True)

OPEN_WA_PORT = os.getenv("OPEN_WA_PORT")

openai_client = create_client()

def printResponse(message):
    print(message)

# async def init_openwa_client() -> SocketClient:
#     """
#     Initialize the OpenWA SocketClient in a non-blocking way.
#     Returns the initialized client instead of using a global.
#     """
#     loop = asyncio.get_event_loop()

#     def blocking_init():
#         client = SocketClient(
#             f"http://172.17.0.1:{OPEN_WA_PORT}/",
#             api_key="my_secret_api_key",
#         )
#         return client

#     client = await loop.run_in_executor(None, blocking_init)
#     return client

async def run_bot(openwa_client: SocketClient):
    logger.info("🚀 Starting WhatsApp bot...")
    # client = await init_openwa_client()
    bot = ChatBotHandler(openwa_client)
    
    # DEBUG: Log bot initialization
    logger.debug("⚙️ Bot initialized, registering handlers...")
    
    register_conv_handler(bot=bot, openai_client=openai_client)

    logger.info("✅ Bot is running. Waiting for messages...")
    
    # print(openwa_client.sendText("6285850434383@c.us", "tesssss bro"))
    
    # Graceful shutdown handler
    async def shutdown():
        logger.info("🛑 Shutting down socket client...")
        await asyncio.to_thread(openwa_client.disconnect)
        logger.info("✅ Socket client disconnected.")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    
    # Keep the loop alive forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run_bot())
