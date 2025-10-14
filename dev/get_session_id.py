from wa_automate_socket_client import SocketClient
import json

client = SocketClient('http://localhost:8003/', 'my_secret_api_key')

print(json.dumps(client.getSessionInfo(), indent=2))