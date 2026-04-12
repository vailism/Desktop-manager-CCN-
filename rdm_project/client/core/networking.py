import socket
import threading
import time
from typing import Callable, Optional


class HeartbeatLoop:
    def __init__(self, heartbeat_fn: Callable[[], None], interval_sec: float = 3.0) -> None:
        self.heartbeat_fn = heartbeat_fn
        self.interval_sec = min(5.0, max(2.0, float(interval_sec)))
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self.heartbeat_fn()
            except Exception:
                pass
            time.sleep(self.interval_sec)


class ReconnectManager:
    def __init__(self, reconnect_fn: Callable[[], bool], max_backoff_sec: float = 12.0) -> None:
        self.reconnect_fn = reconnect_fn
        self.max_backoff_sec = max(2.0, float(max_backoff_sec))
        self._lock = threading.Lock()
        self._last_attempt = 0.0
        self._attempt = 0

    def reconnect_with_backoff(self, max_attempts: int = 5) -> bool:
        with self._lock:
            while self._attempt < max_attempts:
                delay = min(self.max_backoff_sec, 0.5 * (2 ** self._attempt))
                since = time.time() - self._last_attempt
                if since < delay:
                    time.sleep(delay - since)
                self._last_attempt = time.time()
                ok = False
                try:
                    ok = bool(self.reconnect_fn())
                except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.error, OSError):
                    ok = False
                except Exception:
                    ok = False
                if ok:
                    self._attempt = 0
                    return True
                self._attempt += 1
            return False
