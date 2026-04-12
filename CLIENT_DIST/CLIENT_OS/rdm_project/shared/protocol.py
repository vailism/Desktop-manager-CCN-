from enum import Enum


class MessageType(str, Enum):
    CHAT = "chat"
    COMMAND = "command"
    SCREEN_FRAME = "screen_frame"
    FILE_META = "file_meta"
    FILE_CHUNK = "file_chunk"
    FILE_END = "file_end"
    PING = "ping"
    PONG = "pong"
    AUTH = "auth"
    STATUS = "status"
    # Phase 2 — extended remote control
    VOLUME_CTRL = "volume_ctrl"
    CLIPBOARD = "clipboard"
    SYSINFO = "sysinfo"
    SCREENSHOT_REQ = "screenshot_req"


__all__ = ["MessageType"]
