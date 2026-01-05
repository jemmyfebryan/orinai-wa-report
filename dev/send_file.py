# from wa_automate_socket_client import SocketClient
from src.orin_wa_report.core.openwa import SocketClient, WAError

NUMBER_lid = '12816215965755@lid'
NUMBER_cus = '6285850434383@c.us'
# NUMBER_cus = '62895623453312@c.us'

pina_lid = '229037905572043@lid'

client = SocketClient('http://localhost:8003/', 'my_secret_api_key')

import asyncio

async def run():
    res = client.sendText(
        NUMBER_lid,
        "bro"
    )
    res = client.sendFile(
        NUMBER_lid,
        "https://picsum.photos/200/300",
        'filename.jpg'
    )

    print(res)
    print(str(res))
    print(type(res))

if __name__ == "__main__":
    asyncio.run(run())