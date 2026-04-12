import base64
import json
import socket
import struct
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from rdm_project.shared.protocol import MessageType


ENABLE_MESSAGE_ENCODING = True


@dataclass
class Packet:
	msg_type: str
	sender_id: str
	payload: Dict[str, Any]
	timestamp: float

	@staticmethod
	def build(msg_type: MessageType, sender_id: str, payload: Dict[str, Any]) -> "Packet":
		return Packet(
			msg_type=msg_type.value,
			sender_id=sender_id,
			payload=payload,
			timestamp=time.time(),
		)


def pack_packet(packet: Packet) -> bytes:
	body = json.dumps(asdict(packet), separators=(",", ":")).encode("utf-8")
	if ENABLE_MESSAGE_ENCODING:
		body = base64.b64encode(body)
	header = struct.pack("!I", len(body))
	return header + body


def _recv_exact(sock: socket.socket, size: int) -> Optional[bytes]:
	data = bytearray()
	while len(data) < size:
		chunk = sock.recv(size - len(data))
		if not chunk:
			return None
		data.extend(chunk)
	return bytes(data)


def recv_packet(sock: socket.socket) -> Optional[Packet]:
	header = _recv_exact(sock, 4)
	if header is None:
		return None

	body_len = struct.unpack("!I", header)[0]
	if body_len <= 0:
		return None

	body = _recv_exact(sock, body_len)
	if body is None:
		return None

	if ENABLE_MESSAGE_ENCODING:
		body = base64.b64decode(body)

	raw = json.loads(body.decode("utf-8"))
	packet = Packet(
		msg_type=raw["msg_type"],
		sender_id=raw["sender_id"],
		payload=raw["payload"],
		timestamp=raw["timestamp"],
	)
	setattr(packet, "_wire_size", 4 + body_len)
	return packet


def send_packet(sock: socket.socket, packet: Packet) -> int:
	data = pack_packet(packet)
	sock.sendall(data)
	return len(data)


__all__ = [
	"ENABLE_MESSAGE_ENCODING",
	"Packet",
	"pack_packet",
	"recv_packet",
	"send_packet",
]
