import json
import re
import time
import uuid
# import logging

import requests
import socketio
from socketio.exceptions import ConnectionError

from src.orin_wa_report.core.logger import get_logger

__version__ = '1.1.0'

# Configure logging to help with debugging
logger = get_logger(__name__)

class WAError(Exception):
    """Custom Exception for OpenWA errors."""
    def __init__(self, message):
        self.raw_response = message
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"WAError: {self.message}"

class SocketClient(object):
    def __init__(self, url, api_key=None, sync=True):
        """
        :param url: wa-automate URL
        :param api_key: Authentication key (required if provided on wa-automate cli initialization)
        :param sync: Default sync/async behavior
        """
        self.handlers = {}
        self.url = re.sub(r'\/$', '', url)
        self.sync = sync
        self.api_key = api_key

        # Initialize SocketIO client
        self.io = socketio.Client()

        @self.io.event
        def connect():
            logger.info("Connected to OpenWA Server")
            self.io.emit("register_ev")

        @self.io.on('*')
        def catch_all(event, data):
            # Clean event name if necessary
            event_name = event.split('.')[0]
            if event_name in self.handlers:
                for handler in self.handlers[event_name].values():
                    try:
                        handler(data)
                    except Exception as e:
                        logger.error(f"Error in handler for {event_name}: {e}")

        @self.io.event
        def connect_error(data):
            logger.error(f"Connection Error: {data}")

        @self.io.event
        def disconnect():
            logger.info("Disconnected from OpenWA Server")

        # Connection retry loop
        while True:
            try:
                self.io.connect(self.url, auth={'apiKey': self.api_key})
                break
            except (ConnectionError, Exception) as e:
                logger.warning(f"Connection failed, retrying in 5s... ({e})")
                time.sleep(5)

    def __dir__(self):
        """Dynamically fetch available methods from the server for autocomplete/inspection."""
        try:
            self.methods = json.loads(requests.get(self.url + '/meta/basic/commands').content.decode())
            self.on_events = json.loads(requests.get(self.url + '/meta/basic/listeners').content.decode())
            methods = list(self.methods.keys()) + self.on_events + super().__dir__()
            methods.sort()
            return methods
        except Exception as e:
            logger.error(f"Failed to fetch metadata: {e}")
            return super().__dir__()

    def _validate_response(self, response):
        """
        Internal helper to check if a response string indicates an error.
        Raises WAError if the response looks like an error.
        """
        if isinstance(response, str) and response.startswith("ERROR"):
            # You can add more parsing here if the error format is specific (e.g. ERROR: 404)
            logger.error(f"Command failed: {response}")
            raise WAError(response)
        return response

    def __getattr__(self, item):
        client = self

        class Func:
            def __call__(self, *args, **kwargs):
                if item.startswith('on'):
                    return client.listen(item, args[0])
                else:
                    sync = kwargs.get('sync', client.sync)

                    # Prepare the payload
                    payload = {'args': args}
                    # If apiKey is needed in args or headers, it's usually handled by auth, 
                    # but some versions might need it in the payload. 
                    # Kept as is based on your original code.

                    if sync:
                        try:
                            # Synchronous call: Wait for acknowledgment/return
                            res = client.io.call(item, payload)
                            return client._validate_response(res)
                        except socketio.exceptions.TimeoutError:
                            logger.error(f"Timeout calling {item}")
                            raise WAError("Timeout waiting for response")
                    else:
                        # Asynchronous call
                        user_callback = kwargs.get('callback', lambda _: None)

                        def wrapped_callback(res):
                            # We can't raise exception back to main thread easily here,
                            # so we log it and pass it to user callback.
                            if isinstance(res, str) and res.startswith("ERROR"):
                                logger.error(f"Async command {item} failed: {res}")
                            user_callback(res)

                        client.io.emit(item, payload, callback=wrapped_callback)
                        return None

        return Func()

    def stop_listener(self, listener, listener_id):
        if listener in self.handlers and listener_id in self.handlers[listener]:
            del self.handlers[listener][listener_id]
            return True
        return False

    def listen(self, event, handler):
        id = str(uuid.uuid4())
        if event not in self.handlers:
            self.handlers[event] = {}
        self.handlers[event][id] = handler
        return id

    def disconnect(self):
        self.io.disconnect()