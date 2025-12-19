from src.orin_wa_report.core.agent.listener import ChatBotHandler
from wa_automate_socket_client import SocketClient
import asyncio
import json

open_wa_client = SocketClient('http://localhost:8003/', 'my_secret_api_key')


async def run_bot(openwa_client: SocketClient):
    bot = ChatBotHandler(client=open_wa_client)
    
    @bot.on(r"")
    async def conv_handler(msg, client):
        # print(msg["data"]["sender"]["id"])
        print(json.dumps(msg, indent=2))
        
    await asyncio.Event().wait()
    
if __name__ == "__main__":
    asyncio.run(run_bot(open_wa_client))