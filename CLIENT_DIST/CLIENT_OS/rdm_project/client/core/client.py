import socket
import time
from typing import Optional

from rdm_project.shared.constants import HEARTBEAT_INTERVAL_SEC
from rdm_project.shared.packet import Packet
from rdm_project.shared.protocol import MessageType

from rdm_project.client.core.connection import ConnectionState
from rdm_project.client.core.networking import HeartbeatLoop, ReconnectManager

from rdm_project.client.core.base_client import RemoteManagerClient as BaseRemoteManagerClient


class RemoteManagerClient(BaseRemoteManagerClient):
    """Compatibility wrapper that adds resilient send/reconnect behavior."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._heartbeat: Optional[HeartbeatLoop] = None
        self._conn_state = ConnectionState()
        self._reconnector = ReconnectManager(self._reconnect_once)

    def connect(self, interactive: bool = True) -> bool:
        ok = super().connect(interactive=interactive)
        self._conn_state.connected = bool(ok)
        self._conn_state.last_error = "" if ok else "connect_failed"
        if ok and self._heartbeat is None:
            self._heartbeat = HeartbeatLoop(self._send_heartbeat, interval_sec=HEARTBEAT_INTERVAL_SEC)
            self._heartbeat.start()
        return ok

    def _send(self, packet) -> None:  # type: ignore[override]
        try:
            super()._send(packet)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.error, OSError):
            self._conn_state.connected = False
            self._conn_state.last_error = "broken_pipe"
            if not self._reconnector.reconnect_with_backoff(max_attempts=5):
                raise
            super()._send(packet)

    def _send_heartbeat(self) -> None:
        if not self.running:
            return
        try:
            super()._send(
                Packet.build(
                    MessageType.PING,
                    sender_id=self.client_id,
                    payload={"ping_ts": time.time()},
                )
            )
        except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.error, OSError):
            self._conn_state.connected = False
            self._conn_state.last_error = "heartbeat_failed"
            self._reconnector.reconnect_with_backoff(max_attempts=5)
        except Exception:
            pass

    def _reconnect_once(self) -> bool:
        try:
            ok = bool(self.reconnect(self.server_port, self.server_ip))
            self._conn_state.connected = ok
            self._conn_state.last_error = "" if ok else "reconnect_failed"
            self._conn_state.reconnect_attempt += 1
            return ok
        except Exception:
            self._conn_state.connected = False
            self._conn_state.last_error = "reconnect_exception"
            self._conn_state.reconnect_attempt += 1
            return False

    def disconnect(self) -> None:  # type: ignore[override]
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        self._conn_state.connected = False
        super().disconnect()
