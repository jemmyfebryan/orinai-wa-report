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

async def run_bot():
    global wa_client
    
    logger.info("🚀 Starting WhatsApp bot...")
    client = SocketClient(f"http://172.17.0.1:{OPEN_WA_PORT}/", api_key="my_secret_api_key")
    bot = ChatBotHandler(client)
    
    register_conv_handler(bot=bot)

    @bot.on(r"^Verifikasi ORIN Alert: ")
    async def verify_wa_bot(msg, client, history):
        if not msg["data"]["isGroupMsg"]:
            # See/Read the Message
            client.sendSeen(msg["data"]["from"])
            
            phone_number = msg["data"].get("from").split("@")[0]
            user_name = msg["data"].get("sender").get("pushname", "")
            message = msg["data"].get("body", "")
            
            logger.info(f"User {user_name} with number: {phone_number} verifying ORIN alert: {message}")
            
            # Fetch key
            regex_match = re.match(r"^Verifikasi ORIN Alert: (\S+)$", message)
            if regex_match:
                key = regex_match.group(1)
                logger.info(f"Verifying wa for number: {phone_number} with key {key}...")
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

    # Graceful shutdown handler
    async def shutdown():
        logger.info("🛑 Shutting down socket client...")
        client.disconnect()
        logger.info("✅ Socket client disconnected.")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    
    # Keep the loop alive forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run_bot())
