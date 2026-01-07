from src.orin_wa_report.core.openai import create_client
from src.orin_wa_report.core.agent.llm import chat_filter
import asyncio
import time

client = create_client()

async def chat_filter_func(msg):
    return await chat_filter(openai_client=client, messages=[
        {
            "role": "user",
            "content": msg
        }
    ])
    

if __name__ == "__main__":
    print("Starting...")
    
    message_test = [
        "Halo",
        "askdoaksoakdowad",
        "Saya mau nanya dong bang",
        "Saya mau bertanya tentang paket saya",
        "Yang ini gimana ya kendaraan saya",
        "Ini kendaraan saya kok mati kenapa?",
        "Minta tolong reset device saya",
        "Penggunaan bensin sebulan terakhir berapa",
        "Boleh minta report idle kendaraan saya sebulan terakhir?",
        "Kendaraan saya tanggal 22 Desember 2025 menempuh berapa km?",
        "Bisa minta history L 8274 tgl 5-6 des",
        "tadi siang kebetulan dipakai keluar kota tapi di gps terpantau parkir di garasi",
        "yg bermaslaah reportnya saja",
        "Saya ingin berbicara dengan human agent",
        "alihkan ke orang asli",
        "saya tidak mau dijawab AI"
    ]
    
    time_now = time.time()
    for msg in message_test:
        result = asyncio.run(chat_filter_func( 
            msg
        ))
        print("")
        print(f"Msg: {msg}")
        print(result)
        print(f"Time needed: {time.time() - time_now}")
        time_now = time.time()