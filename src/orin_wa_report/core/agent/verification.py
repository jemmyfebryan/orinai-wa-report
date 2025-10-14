import re
import json
from src.orin_wa_report.core.development.verify_wa import (
    verify_wa_key_and_store_wa_number
)
from src.orin_wa_report.core.logger import get_logger

logger = get_logger(__name__, service="Agent")

async def handler_verify_wa(
    wa_key: str,
    phone_number: str,
    user_name: str
) -> str:
    try:
        result = await verify_wa_key_and_store_wa_number(
            wa_key=wa_key,
            wa_number=phone_number
        )
        logger.info(f"WA Verification Result for {phone_number}: {json.dumps(result, indent=2)}")
        return f"Halo {user_name}, verifikasi ORIN AI anda berhasil!"
    except Exception as e:
        logger.error(f"WA Verification for {phone_number} error: {str(e)}")
        return "Maaf, terjadi kesalahan saat verifikasi. Silakan coba lagi."

async def verify_wa_bot(msg, client):
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
        regex_match = re.search(r"\*\[([A-Za-z0-9]+)\]\*", message)

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