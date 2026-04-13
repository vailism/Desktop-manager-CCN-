from enum import Enum


class MessageType(str, Enum):
    """Protocol-level message types for server-client communication."""
    CHAT = "chat"               # Remote chat messages
    COMMAND = "command"         # Shell/system command execution
    SCREEN_FRAME = "screen_frame" # Compressed JPEG screen frames
    FILE_META = "file_meta"     # Metadata for file transfer (name, size)
    FILE_CHUNK = "file_chunk"   # Binary data chunk for file transfer
    FILE_END = "file_end"       # Signal for end of file transfer
    PING = "ping"               # Latency tracking ping
    PONG = "pong"               # Latency tracking pong
    AUTH = "auth"               # Initial authentication token payload
    STATUS = "status"           # System health (CPU/RAM) status update
    # Phase 2 — extended remote control
    VOLUME_CTRL = "volume_ctrl" # Control OS volume levels
    CLIPBOARD = "clipboard"     # Synchronize/pull clipboard content
    SYSINFO = "sysinfo"         # Detailed hardware specifications
    SCREENSHOT_REQ = "screenshot_req" # Full-resolution snapshot request


__all__ = ["MessageType"]
