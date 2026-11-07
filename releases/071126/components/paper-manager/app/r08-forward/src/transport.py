"""TLS-verified transport boundary, no default network or socket creation."""
import ssl
from .common import Blocked
ENDPOINT='wss://stream.binance.com:9443/ws/btcusdt@aggTrade'
class SpotTransport:
    def __init__(self,recorder,*,network_opt_in=False):
        self.recorder=recorder;self.network_opt_in=network_opt_in
        self.context=ssl.create_default_context();self.context.check_hostname=True;self.context.verify_mode=ssl.CERT_REQUIRED
    def start(self,connector=None):
        if not self.network_opt_in:raise Blocked('NETWORK_ACTIVATION_DISABLED')
        if self.context.verify_mode!=ssl.CERT_REQUIRED or not self.context.check_hostname:raise Blocked('INSECURE_TRANSPORT_FORBIDDEN')
        if connector is None:
            from .ws_connection import Connection
            connector=Connection
        # The network implementation is unreachable from the disabled research entrypoint.
        conn=connector(endpoint=ENDPOINT,ssl_context=self.context,on_message=self.recorder.application_callback,max_message_bytes=65536,on_reconnect=self.recorder.reconnect,on_transport=self.recorder.transport_observation)
        return conn.run()
