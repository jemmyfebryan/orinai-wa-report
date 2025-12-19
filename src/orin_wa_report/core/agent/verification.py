import re
import json
from src.orin_wa_report.core.development.verify_wa import (
    verify_wa_key_and_store_wa_number
)
from src.orin_wa_report.core.logger import get_logger
from src.orin_wa_report.core.openwa import WAError

logger = get_logger(__name__, service="Agent")

async def handler_verify_wa(
    wa_key: str,
    phone_number: str,
    lid_number: str,  # WhatsApp will migrate from phone number to lid number
    user_name: str,
) -> str:
    try:
        result = await verify_wa_key_and_store_wa_number(
            wa_key=wa_key,
            wa_number=phone_number,
            wa_lid=lid_number,
        )
        logger.info(f"WA Verification Result for phone-{phone_number}/lid-{lid_number}: {json.dumps(result, indent=2)}")
        return f"Halo {user_name}, verifikasi ORIN AI anda berhasil!"
    except Exception as e:
        logger.error(f"WA Verification for phone-{phone_number}/lid-{lid_number} error: {str(e)}")
        return "Maaf, terjadi kesalahan saat verifikasi. Silakan coba lagi."

async def verify_wa_bot(msg, client):
    # DEBUG: Log message received
    logger.debug(f"📨 Received message: {msg['data']['body']}")
    
    if not msg["data"]["isGroupMsg"] and msg["data"]["fromMe"] == False:
        # DEBUG: Log message passed conditions
        logger.debug("✅ Message passed group/fromMe checks")
        
        # See/Read the Message
        # client.sendSeen(msg["data"]["from"])
        
        raw_phone_number = msg["data"]["sender"].get("phoneNumber")
        raw_lid_number = msg["data"]["sender"].get("lid")
        
        phone_number = raw_phone_number.split("@")[0]
        lid_number = raw_lid_number.split("@")[0]
        user_name = msg["data"].get("sender").get("pushname", "")
        message = msg["data"].get("body", "")
        
        logger.info(f"👤 User {user_name} phone-({phone_number})/lid-({lid_number}) verifying ORIN alert: {message}")
        
        # Fetch key
        # regex_match = re.search(r"\*\[([A-Za-z0-9]+)\]\*", message)
        regex_match = re.search(r"^Halo ORIN, saya ingin melakukan verifikasi akun ORIN AI\.[\s\S]*?\*\[(.*?)\]\*", message)

        if regex_match:
            key = regex_match.group(1)
            logger.info(f"Verifying wa for number: phone-({phone_number})/lid-({lid_number}) with key {key}...")
            if key == None or key == "":
                logger.info(f"User with number: phone-({phone_number})/lid-({lid_number}) invalid key.")
                response = "Maaf, kode verifikasi Anda tidak sesuai. Silakan coba lagi."
            else:
                response = await handler_verify_wa(
                    wa_key=key,
                    phone_number=phone_number,
                    lid_number=lid_number,
                    user_name=user_name
                )
        else:
            logger.info(f"User with number: phone-({phone_number})/lid-({lid_number}) key not match")
            response = "Maaf, kode verifikasi Anda tidak sesuai. Silakan coba lagi."
        try:
            client.sendText(raw_phone_number, response)
        except WAError:
            client.sendText(raw_lid_number, response)
            