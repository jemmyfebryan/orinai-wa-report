import os
from src.orin_wa_report.core.openwa import SocketClient

# OpenWA Client
OPEN_WA_PORT = os.getenv("OPEN_WA_PORT")
openwa_client: SocketClient | None = None

def init_openwa():
    global openwa_client
    openwa_client = SocketClient(
        f"http://172.17.0.1:{OPEN_WA_PORT}/",
        api_key="my_secret_api_key",
    )
    
def get_openwa_client():
    print(openwa_client)
    return openwa_client
