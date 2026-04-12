"""Thread-safe in-memory connection registry for active clients."""

import socket
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class ClientConnection:
    client_id: str
    address: Tuple[str, int]
    sock: socket.socket


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: Dict[str, ClientConnection] = {}
        self._lock = threading.Lock()

    def add(self, conn: ClientConnection) -> None:
        with self._lock:
            self._clients[conn.client_id] = conn

    def remove(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)

    def get(self, client_id: str) -> Optional[ClientConnection]:
        with self._lock:
            return self._clients.get(client_id)

    def snapshot(self) -> Dict[str, ClientConnection]:
        with self._lock:
            return dict(self._clients)
