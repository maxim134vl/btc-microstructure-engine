"""Opt-in verified Spot transport; imported only after explicit opt-in.

Pinned optional websocket-client interface. Offline qualification uses injected
frame/socket factories. Does not borrow or patch any canonical connection.
"""
from .common import Blocked,Capacity
from .transport import ENDPOINT
import ssl

def bounded_socket_class(max_bytes):
    import websocket
    from websocket._abnf import frame_buffer
    class BoundedBuffer(frame_buffer):
        remaining=max_bytes
        def recv_length(self):
            super().recv_length()
            # Check before frame_buffer.recv_strict(length) allocates payload.
            opcode=self.header[4]
            limit=125 if opcode in (8,9,10) else self.remaining
            if self.length>limit:raise Capacity('WS_FRAME_OR_MESSAGE_CAP_INCOMPLETE')
    class BoundedSocket(websocket.WebSocket):
        def __init__(self,*args,**kw):
            super().__init__(*args,**kw)
            self.frame_buffer=BoundedBuffer(self._recv,False)
    return BoundedSocket

class Connection:
    def __init__(self,*,endpoint,ssl_context,on_message,max_message_bytes,on_reconnect,on_transport=None,connect=None,max_messages=4096):
        if endpoint!=ENDPOINT or ssl_context.verify_mode!=ssl.CERT_REQUIRED or not ssl_context.check_hostname:raise Blocked('VERIFIED_FIXED_SPOT_TRANSPORT_REQUIRED')
        if not 1<=max_message_bytes<=65536 or not 1<=max_messages<=4096:raise ValueError('TRANSPORT_TECHNICAL_CAP')
        self.endpoint=endpoint;self.context=ssl_context;self.callback=on_message;self.max_bytes=max_message_bytes;self.max_messages=max_messages;self.connect=connect;self.on_reconnect=on_reconnect;self.on_transport=on_transport
    def run(self):
        import websocket
        factory=self.connect or websocket.create_connection
        ws=factory(self.endpoint,timeout=10,sslopt={'context':self.context,'cert_reqs':ssl.CERT_REQUIRED,'check_hostname':True},class_=bounded_socket_class(self.max_bytes),redirect_limit=0,http_no_proxy=['stream.binance.com'],enable_multithread=False)
        # No reconnect loop or REST fallback. A new session requires explicit
        # new connection and a retained boundary; uncertainty never auto-clears.
        partial=bytearray();opcode=None;delivered=0
        try:
            if self.on_transport:
                sock=getattr(ws,'sock',None)
                cert=sock.getpeercert(binary_form=True) if isinstance(sock,ssl.SSLSocket) else None
                from .common import sha
                self.on_transport({'endpoint':self.endpoint,'certificate_verification_required':True,'hostname_verification_required':True,'peer_certificate_sha256':sha(cert) if cert else None,'tls_version':sock.version() if cert else None,'transport_peer_witness':'OBSERVED_VERIFIED_POLICY_SESSION' if cert else 'UNQUALIFIED_OFFLINE_OR_NO_PEER_RECEIPT','websocket_client_version':websocket.__version__})
            while delivered<self.max_messages:
                ws.frame_buffer.remaining=self.max_bytes-len(partial)
                frame=ws.recv_frame()
                if frame.opcode==8:break
                if frame.opcode==9:ws.pong(frame.data);continue
                if frame.opcode==10:continue
                if frame.opcode in (1,2):
                    if opcode is not None:raise Blocked('OVERLAPPING_WS_MESSAGE')
                    opcode=frame.opcode
                elif frame.opcode!=0 or opcode is None:raise Blocked('WS_FRAGMENT_ORDER')
                if len(partial)+len(frame.data)>self.max_bytes:raise Capacity('WS_MESSAGE_CAP_INCOMPLETE')
                partial.extend(frame.data)
                if frame.fin:
                    raw=bytes(partial);msg=raw.decode('utf-8') if opcode==1 else raw
                    self.callback(ws,msg) # callback records receive before JSON
                    delivered+=1;partial.clear();opcode=None
            if partial:raise Blocked('INCOMPLETE_WS_APPLICATION_MESSAGE')
            return {'delivered':delivered,'stop':'BOUNDED_TRANSPORT_END','tls_session_authentication':'NOT_QUALIFIED_BY_OFFLINE_TESTS'}
        except BaseException as e:
            self.on_reconnect('TRANSPORT_STOP_UNCERTAINTY:'+type(e).__name__+':'+str(e))
            raise
        finally:ws.close()
