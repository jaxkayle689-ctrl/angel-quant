"""Lifecycle of the desktop's embedded pipeline server."""
import socket
import threading
import time

import uvicorn

from .server import create_app


class DesktopPipeline:
    def __init__(self):
        self._lock = threading.Lock()
        self.server = None
        self.thread = None
        self.url = ''
        self.app = None

    def start(self):
        with self._lock:
            if self.server and self.server.started:
                return {'url': self.url}
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            sock.listen(128)
            self.app = create_app()
            self.server = uvicorn.Server(uvicorn.Config(self.app, log_config=None, loop='asyncio', http='h11', ws='websockets', lifespan='off'))
            self.url = 'http://127.0.0.1:' + str(sock.getsockname()[1])
            self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [sock]}, daemon=True)
            self.thread.start()
            deadline = time.monotonic() + 10
            while not self.server.started:
                if not self.thread.is_alive() or time.monotonic() > deadline:
                    self.server.should_exit = True
                    sock.close()
                    raise RuntimeError('策略工作台启动失败，请重试')
                time.sleep(.05)
            return {'url': self.url}

    def stop(self):
        with self._lock:
            if self.app:
                self.app.state.runtime.liquidation_feed.stop()
            if self.server:
                self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=3)
