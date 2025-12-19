# from wa_automate_socket_client import SocketClient
from src.orin_wa_report.core.openwa import SocketClient, WAError

NUMBER_lid = '12816215965755@lid'
NUMBER_cus = '6285850434383@c.us'
# NUMBER_cus = '62895623453312@c.us'

client = SocketClient('http://localhost:8003/', 'my_secret_api_key')

import asyncio

async def run():
    try:
        res = client.sendText(NUMBER_cus, "this is a text")
    except WAError:
        res = client.sendText(NUMBER_lid, "this is a text")
    print(res)
    print(type(res))

if __name__ == "__main__":
    asyncio.run(run())
# def printResponse(message):
#     print(message)


# # Listening for events
# client.onMessage(printResponse)

# # Executing commands

# # # Sync/Async support
# # print(client.getHostNumber())  # Sync request
# client.sendAudio(NUMBER,
#                  "https://download.samplelib.com/mp3/sample-3s.mp3",
#                  sync=False,
#                  callback=printResponse)  # Async request. Callback is optional

# # Finally disconnect
# client.disconnect()