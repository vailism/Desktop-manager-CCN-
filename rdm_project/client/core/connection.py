from dataclasses import dataclass


@dataclass
class ConnectionState:
    connected: bool = False
    last_error: str = ""
    reconnect_attempt: int = 0
