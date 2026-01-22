import re
import os
from typing import List, Dict
from dotenv import load_dotenv

import httpx
from openai import AsyncOpenAI

from src.orin_wa_report.core.agent.llm import split_messages

load_dotenv()

ORINAI_CHAT_ENDPOINT = os.getenv("ORINAI_CHAT_ENDPOINT")

def markdown_to_whatsapp(text: str) -> str:
    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.*?)\*\*", r"*\1*", text)

    # Italic: _text_ or *text* → _text_
    # (Markdown often uses *italic* as well)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?<!\*)", r"_\1_", text)
    text = re.sub(r"_(.*?)_", r"_\1_", text)

    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.*?)~~", r"~\1~", text)

    # Inline code: `text` → ```text```
    text = re.sub(r"`(.*?)`", r"```\1```", text)

    # Remove Markdown headers (#, ##, ### etc.)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)

    return text

async def get_reset_password_answer():
    all_replies = [
        f"Jika Anda mengalami lupa password, Anda dapat melakukan langkah-langkah sebagai berikut:\n"
        f"\n- Masuk ke aplikasi Orin atau website https://app.orin.id/"
        f"\n- Pilih opsi _'Lupa Password'_ atau _'Forgot Password'_"
        f"\n- Masukkan *Email* yang digunakan saat mendaftar akun"
        f"\n- Setelah itu pengajuan perubahan password akan dikirimkan ke *Email* Anda",
        "Ada lagi yang bisa saya bantu?"
    ]
    all_replies = [markdown_to_whatsapp(reply) for reply in all_replies]
    return all_replies

async def get_account_status_answer(
    openai_client: AsyncOpenAI,
    api_tokens: List[str],
    last_message: str,
):
    accounts_status = []
    async with httpx.AsyncClient(timeout=10.0) as httpx_client:
        for api_token in api_tokens:
            response = await httpx_client.get(
                f"{ORINAI_CHAT_ENDPOINT}/user/account_status",
                headers={
                    "Authorization": f"Bearer {api_token}"
                }
            )
            accounts_status.append(response.json())
            
    all_replies = ["Berikut adalah status dari akun Anda"] + [str(val) for val in accounts_status]
    
    all_replies = await split_messages(
        openai_client=openai_client,
        all_replies=all_replies,
        chat_filter_is_report=False,
        additional_instructions=f"-Parafrase pesan agar pantas dikirim ke user.\n\nPesan dari user: {last_message}"
    )
    all_replies = [markdown_to_whatsapp(reply) for reply in all_replies]
    return all_replies