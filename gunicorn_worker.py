# Gunicorn worker: GeventWebSocketWorker with a fix for proxies that send "Connection: upgrade"
# on every request (e.g. nginx with an unconditional `proxy_set_header Connection "upgrade"`).
#
# gevent's pywsgi treats any request with "Connection: upgrade" as a WebSocket upgrade and then
# gives the application the raw socket as wsgi.input, with no length limit. Reading the body of an
# ordinary POST then blocks until the proxy closes the connection (60 s -> 504 for every POST).
# Here a request counts as an upgrade only when it actually asks for one ("Upgrade: websocket").
#
# Usage: gunicorn -k gunicorn_worker.Worker ...

from geventwebsocket.gunicorn.workers import GeventWebSocketWorker
from geventwebsocket.handler import WebSocketHandler


class UpgradeAwareWebSocketHandler(WebSocketHandler):
    def _connection_upgrade_requested(self):
        return self.headers.get("Upgrade", "").lower() == "websocket"


class Worker(GeventWebSocketWorker):
    wsgi_handler = UpgradeAwareWebSocketHandler
