import asyncio
import re
import os
import signal
from wa_automate_socket_client import SocketClient
from src.orin_wa_report.core.agent.listener import ChatBotHandler
from src.orin_wa_report.core.agent.handler import (
    register_conv_handler,
    handler_verify_wa,
)
from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__, service="Agent")

from dotenv import load_dotenv
load_dotenv(override=True)

OPEN_WA_PORT = os.getenv("OPEN_WA_PORT")

def printResponse(message):
    print(message)

async def init_openwa_client() -> SocketClient:
    """
    Initialize the OpenWA SocketClient in a non-blocking way.
    Returns the initialized client instead of using a global.
    """
    loop = asyncio.get_event_loop()

    def blocking_init():
        client = SocketClient(
            f"http://172.17.0.1:{OPEN_WA_PORT}/",
            api_key="my_secret_api_key",
        )
        return client

    client = await loop.run_in_executor(None, blocking_init)
    return client

async def run_bot():
    logger.info("🚀 Starting WhatsApp bot...")
    client = await init_openwa_client()
    bot = ChatBotHandler(client)
    
    # DEBUG: Log bot initialization
    logger.debug("⚙️ Bot initialized, registering handlers...")
    
    register_conv_handler(bot=bot)

    @bot.on(r"^Verifikasi ORIN Alert: ")
    async def verify_wa_bot(msg, client, history):
        # DEBUG: Log message received
        logger.debug(f"📨 Received message: {msg['data']['body']}")
        
        if not msg["data"]["isGroupMsg"] and msg["data"]["fromMe"] == False:
            # DEBUG: Log message passed conditions
            logger.debug("✅ Message passed group/fromMe checks")
            
            # See/Read the Message
            client.sendSeen(msg["data"]["from"])
            
            phone_number = msg["data"].get("from").split("@")[0]
            user_name = msg["data"].get("sender").get("pushname", "")
            message = msg["data"].get("body", "")
            
            logger.info(f"👤 User {user_name} ({phone_number}) verifying ORIN alert: {message}")
            
            # Fetch key
            regex_match = re.match(r"^Verifikasi ORIN Alert: (\S+)$", message)
            if regex_match:
                key = regex_match.group(1)
                logger.info(f"Verifying wa for number: {phone_number} with key {key}...")
                if key == None or key == "":
                    logger.info(f"User with number: {phone_number} invalid key.")
                    response = "Maaf, kode verifikasi Anda tidak sesuai. Silakan coba lagi."
                else:
                    response = await handler_verify_wa(
                        wa_key=key,
                        phone_number=phone_number,
                        user_name=user_name
                    )
            else:
                logger.info(f"User with number: {phone_number} key not match")
                response = "Maaf, kode verifikasi Anda tidak sesuai. Silakan coba lagi."
            await client.sendText(msg["data"]["from"], response)

    logger.info("✅ Bot is running. Waiting for messages...")
    
    # DEBUG: Log handler registration
    logger.debug(f"⏳ Registered handlers: {list(bot._handlers.keys())}")

    # Graceful shutdown handler
    async def shutdown():
        logger.info("🛑 Shutting down socket client...")
        await asyncio.to_thread(client.disconnect)
        logger.info("✅ Socket client disconnected.")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    
    # Keep the loop alive forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run_bot())
