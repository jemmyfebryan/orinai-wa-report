from wa_automate_socket_client import SocketClient


client = SocketClient('http://localhost:8003/', 'my_secret_api_key')

print(client.getProfilePicFromServer("6285850434383@c.us"))