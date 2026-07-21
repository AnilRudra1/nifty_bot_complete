"""
Direct WebSocket connection to Angel One SmartStream.
Uses correct subscription format from Angel One documentation.
"""

import json
import time
import struct
import threading
import websocket
from utils.logger import get_logger

log = get_logger("websocket")

WS_URL = "wss://smartapisocket.angelone.in/smart-stream"


class AngelWebSocket:
    def __init__(self, auth_token, api_key, client_code, feed_token, on_tick_callback):
        self.auth_token  = auth_token
        self.api_key     = api_key
        self.client_code = client_code
        self.feed_token  = feed_token
        self.on_tick     = on_tick_callback
        self.ws          = None
        self.connected   = False
        self.running     = False
        self._tokens     = []

    def subscribe(self, tokens: list):
        self._tokens = tokens

    def _send_subscribe(self):
        nse_tokens = [t for t in self._tokens if t == "99926000"]
        nfo_tokens = [t for t in self._tokens if t != "99926000"]

        token_list = []
        if nse_tokens:
            token_list.append({"exchangeType": 1, "tokens": nse_tokens})
        if nfo_tokens:
            token_list.append({"exchangeType": 2, "tokens": nfo_tokens})

        payload = {
            "action": 1,
            "params": {
                "mode":      3,
                "tokenList": token_list,
            }
        }
        msg = json.dumps(payload)
        log.info(f"Sending subscribe: {msg[:200]}")
        try:
            self.ws.send(msg)
            log.info(f"Subscribed {len(self._tokens)} tokens")
        except Exception as e:
            log.error(f"Subscribe error: {e}")

    def _on_open(self, ws):
        self.connected = True
        log.info("WebSocket on_open fired")

        # Angel One requires this exact auth format
        auth = {
            "clientCode": self.client_code,
            "feedToken":  self.feed_token,
            "jwtToken":   self.auth_token,
        }
        ws.send(json.dumps(auth))
        log.info(f"Auth sent: clientCode={self.client_code}")

        # Must wait for auth to be processed before subscribing
        time.sleep(3)
        self._send_subscribe()

        # Send a heartbeat ping to check if server responds
        time.sleep(2)
        try:
            self.ws.send("ping")
            log.info("Ping sent to WebSocket server")
        except Exception as e:
            log.error(f"Ping failed: {e}")

    def _on_message(self, ws, message):
        try:
            if isinstance(message, bytes):
                log.info(f"Binary tick: {len(message)} bytes")
                self._parse_binary(message)
            else:
                log.info(f"Text message: {str(message)[:200]}")
                try:
                    data = json.loads(message)
                    # Handle auth response
                    if isinstance(data, dict):
                        if data.get("type") == "success":
                            log.info("Auth successful, subscribing...")
                            self._send_subscribe()
                        elif data.get("type") == "error":
                            log.error(f"WebSocket error response: {data}")
                        else:
                            self.on_tick(data)
                    elif isinstance(data, list):
                        for tick in data:
                            self.on_tick(tick)
                except json.JSONDecodeError:
                    log.info(f"Non-JSON message: {message[:100]}")
        except Exception as e:
            log.error(f"Message error: {e}")

    def _parse_binary(self, data):
        """
        Angel One SmartStream binary format (Mode 3):
        Offset 0:    subscription mode (1 byte)
        Offset 1:    exchange type (1 byte)
        Offset 2-27: token (25 bytes)
        Offset 28-35: sequence number (8 bytes)
        Offset 36-43: exchange timestamp (8 bytes)
        Offset 44-51: LTP * 100 (8 bytes, big endian signed)
        """
        try:
            if len(data) < 52:
                log.info(f"Short binary message: {len(data)} bytes, skipping")
                return

            mode     = data[0]
            exch     = data[1]
            token    = data[2:27].decode("utf-8").strip("\x00").strip()
            ltp_raw  = struct.unpack(">q", data[44:52])[0]
            ltp      = ltp_raw / 100.0

            log.info(f"Tick | mode:{mode} exch:{exch} token:{token} ltp:{ltp}")

            if token and ltp > 0:
                self.on_tick({
                    "token":             token,
                    "last_traded_price": ltp_raw,
                    "ltp":               ltp,
                })
        except Exception as e:
            log.error(f"Binary parse error: {e} | data[:20]={data[:20].hex()}")

    def _on_error(self, ws, error):
        log.error(f"WebSocket error: {error}")
        self.connected = False

    def _on_close(self, ws, code, msg):
        log.warning(f"WebSocket closed: {code} {msg}")
        self.connected = False
        if self.running:
            log.info("Reconnecting in 5 seconds...")
            time.sleep(5)
            self._connect()

    def _connect(self):
        headers = {
            "Authorization": self.auth_token,
            "x-api-key":     self.api_key,
            "x-client-code": self.client_code,
            "x-feed-token":  self.feed_token,
        }
        self.ws = websocket.WebSocketApp(
            WS_URL,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws.run_forever(
            ping_interval=30,
            ping_timeout=10,
        )

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._connect, daemon=True)
        thread.start()
        log.info("WebSocket thread started")
        return thread

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
