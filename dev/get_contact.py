from wa_automate_socket_client import SocketClient
import json

client = SocketClient('http://localhost:8003/', 'my_secret_api_key')

contact_details = client.getContact("6285850434383@c.us")

print(json.dumps(contact_details, indent=2))

print(contact_details.get("name"))