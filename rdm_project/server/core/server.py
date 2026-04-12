import argparse
import base64
import os
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Optional, Tuple

import cv2
import numpy as np

from rdm_project.shared.packet import Packet, recv_packet, send_packet
from rdm_project.shared.constants import DEFAULT_HOST, DEFAULT_PASSWORD, DEFAULT_PORT
from rdm_project.shared.protocol import MessageType


@dataclass
class ClientConnection:
    client_id: str
    address: Tuple[str, int]
    sock: socket.socket


class RemoteManagerServer:
    def __init__(self, host: str, port: int, password: str) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self.clients: Dict[str, ClientConnection] = {}
        self.clients_lock = threading.Lock()
        self.latest_frames: Dict[str, str] = {}
        self.stream_stats: Dict[str, Dict[str, float]] = {}
        self.stream_lock = threading.Lock()
        self.selected_client_id: Optional[str] = None
        self.selected_lock = threading.Lock()
        self.net_stats: Dict[str, Dict[str, float]] = {}
        self.net_lock = threading.Lock()
        self.completed_sessions: Dict[str, Dict[str, float]] = {}
        self.completed_lock = threading.Lock()
        self.chat_events: Deque[Tuple[str, str, str]] = deque(maxlen=500)
        self.chat_lock = threading.Lock()
        self.preview_enabled = True
        self._preview_warned = False
        # Command acknowledgment queue
        self.command_acks_queue: list = []
        self.command_acks_lock = threading.Lock()
        # System info store (per client)
        self.sysinfo_store: Dict[str, dict] = {}
        self.sysinfo_lock = threading.Lock()
        # Clipboard store (per client)
        self.clipboard_store: Dict[str, str] = {}
        self.clipboard_lock = threading.Lock()
        # On-demand screenshot store (per client)
        self.screenshot_store: Dict[str, str] = {}
        self.screenshot_lock = threading.Lock()

    def _record_chat_event(self, from_client_id: str, to_client_id: str, text: str) -> None:
        with self.chat_lock:
            self.chat_events.append((from_client_id, to_client_id, text))

    def pop_chat_events(self) -> list[Tuple[str, str, str]]:
        with self.chat_lock:
            if not self.chat_events:
                return []
            events = list(self.chat_events)
            self.chat_events.clear()
            return events

    def _format_bytes(self, value: float) -> float:
        return max(0.0, float(value))

    def _build_session_summary(self, client_id: str) -> Dict[str, float]:
        with self.net_lock:
            net = self.net_stats.get(client_id, {}).copy()

        connected_at = float(net.get("connected_at", time.time()))
        duration_s = max(0.0, time.time() - connected_at)
        latency_count = max(1.0, float(net.get("latency_count", 0.0)))
        avg_latency = float(net.get("latency_sum", 0.0)) / latency_count if latency_count > 0 else 0.0

        return {
            "client_id": client_id,
            "duration_s": duration_s,
            "bytes_sent": self._format_bytes(net.get("bytes_sent", 0.0)),
            "bytes_recv": self._format_bytes(net.get("bytes_recv", 0.0)),
            "avg_latency_ms": max(0.0, avg_latency),
        }

    def pop_completed_session_summary(self, client_id: str) -> Optional[Dict[str, float]]:
        with self.completed_lock:
            return self.completed_sessions.pop(client_id, None)

    def _send_file(
        self,
        target_client_id: str,
        file_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> bool:
        with self.clients_lock:
            target = self.clients.get(target_client_id)

        if target is None:
            return False

        if not os.path.isfile(file_path):
            return False

        transfer_id = str(uuid.uuid4())
        file_name = os.path.basename(file_path)
        total_size = os.path.getsize(file_path)
        sent_size = 0

        meta_packet = Packet.build(
            MessageType.FILE_META,
            sender_id="server",
            payload={
                "transfer_id": transfer_id,
                "name": file_name,
                "size": total_size,
            },
        )
        sent = send_packet(target.sock, meta_packet)
        self._record_sent(target_client_id, sent)

        chunk_size = 64 * 1024
        seq = 0
        with open(file_path, "rb") as fp:
            while True:
                if should_cancel is not None and should_cancel():
                    cancel_packet = Packet.build(
                        MessageType.FILE_END,
                        sender_id="server",
                        payload={"transfer_id": transfer_id, "cancelled": True},
                    )
                    sent = send_packet(target.sock, cancel_packet)
                    self._record_sent(target_client_id, sent)
                    return False

                chunk = fp.read(chunk_size)
                if not chunk:
                    break
                seq += 1
                sent_size += len(chunk)
                chunk_b64 = base64.b64encode(chunk).decode("ascii")
                pkt = Packet.build(
                    MessageType.FILE_CHUNK,
                    sender_id="server",
                    payload={
                        "transfer_id": transfer_id,
                        "seq": seq,
                        "data": chunk_b64,
                    },
                )
                sent = send_packet(target.sock, pkt)
                self._record_sent(target_client_id, sent)
                if progress_callback is not None:
                    progress_callback(sent_size, total_size)

        end_packet = Packet.build(
            MessageType.FILE_END,
            sender_id="server",
            payload={"transfer_id": transfer_id, "cancelled": False},
        )
        sent = send_packet(target.sock, end_packet)
        self._record_sent(target_client_id, sent)
        if progress_callback is not None:
            progress_callback(total_size, total_size)
        return True

    def _resolve_client_id(self, token: str) -> Optional[str]:
        with self.clients_lock:
            ids = list(self.clients.keys())

        if token in ids:
            return token

        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(ids):
                return ids[idx - 1]

        return None

    def _set_selected_client(self, client_id: Optional[str]) -> None:
        with self.selected_lock:
            self.selected_client_id = client_id

    def _get_selected_client(self) -> Optional[str]:
        with self.selected_lock:
            return self.selected_client_id

    def _send_selected_command(self, action: str) -> None:
        target = self._get_selected_client()
        if not target:
            print("[SERVER] No selected client. Use /select <id_or_index> first.")
            return

        delivered = self._send_command(target_client_id=target, action=action)
        if delivered:
            print(f"[SERVER] Command sent: {action} -> {target}")
        else:
            print(f"[SERVER] Selected client is unavailable: {target}")
            self._set_selected_client(None)

    def _record_sent(self, client_id: str, byte_count: int) -> None:
        if byte_count <= 0:
            return
        with self.net_lock:
            stats = self.net_stats.setdefault(
                client_id,
                {
                    "bytes_sent": 0.0,
                    "bytes_recv": 0.0,
                    "latency_ms": 0.0,
                    "latency_sum": 0.0,
                    "latency_count": 0.0,
                    "connected_at": time.time(),
                },
            )
            stats["bytes_sent"] = stats.get("bytes_sent", 0.0) + float(byte_count)

    def _record_recv(self, client_id: str, byte_count: int) -> None:
        if byte_count <= 0:
            return
        with self.net_lock:
            stats = self.net_stats.setdefault(
                client_id,
                {
                    "bytes_sent": 0.0,
                    "bytes_recv": 0.0,
                    "latency_ms": 0.0,
                    "latency_sum": 0.0,
                    "latency_count": 0.0,
                    "connected_at": time.time(),
                },
            )
            stats["bytes_recv"] = stats.get("bytes_recv", 0.0) + float(byte_count)

    def _update_latency(self, client_id: str, latency_ms: float) -> None:
        with self.net_lock:
            stats = self.net_stats.setdefault(
                client_id,
                {
                    "bytes_sent": 0.0,
                    "bytes_recv": 0.0,
                    "latency_ms": 0.0,
                    "latency_sum": 0.0,
                    "latency_count": 0.0,
                    "connected_at": time.time(),
                },
            )
            prev = stats.get("latency_ms", 0.0)
            stats["latency_ms"] = latency_ms if prev == 0.0 else (0.8 * prev + 0.2 * latency_ms)
            stats["latency_sum"] = stats.get("latency_sum", 0.0) + latency_ms
            stats["latency_count"] = stats.get("latency_count", 0.0) + 1.0

    def _update_system_usage(self, client_id: str, cpu_pct: float, ram_pct: float) -> None:
        with self.net_lock:
            stats = self.net_stats.setdefault(
                client_id,
                {
                    "bytes_sent": 0.0,
                    "bytes_recv": 0.0,
                    "latency_ms": 0.0,
                    "latency_sum": 0.0,
                    "latency_count": 0.0,
                    "connected_at": time.time(),
                },
            )
            stats["cpu_pct"] = max(0.0, min(100.0, float(cpu_pct)))
            stats["ram_pct"] = max(0.0, min(100.0, float(ram_pct)))
            stats["system_updated_at"] = time.time()

    def _ping_loop(self) -> None:
        while True:
            with self.clients_lock:
                snapshot = list(self.clients.items())

            for client_id, connection in snapshot:
                packet = Packet.build(
                    MessageType.PING,
                    sender_id="server",
                    payload={"ping_ts": time.time()},
                )
                try:
                    sent = send_packet(connection.sock, packet)
                    self._record_sent(client_id, sent)
                except OSError:
                    pass

            time.sleep(2.0)

    def _print_dashboard(self) -> None:
        with self.clients_lock:
            connected = list(self.clients.keys())

        with self.selected_lock:
            selected = self.selected_client_id

        with self.stream_lock:
            stats_snapshot = {cid: self.stream_stats.get(cid, {}).copy() for cid in connected}

        with self.net_lock:
            net_snapshot = {cid: self.net_stats.get(cid, {}).copy() for cid in connected}

        print("\n[SERVER DASHBOARD]")
        print(f"Selected client: {selected if selected else '(none)'}")
        print("ID                 FPS   S-LAT  PING   KB/FRM   RX(KB)   TX(KB)")
        print("-----------------  ----  -----  -----  -------  -------  -------")
        if not connected:
            print("(no connected clients)")
            return

        for cid in connected:
            stream_stat = stats_snapshot.get(cid, {})
            net_stat = net_snapshot.get(cid, {})
            fps = stream_stat.get("fps", 0.0)
            stream_latency = stream_stat.get("latency_ms", 0.0)
            ping_latency = net_stat.get("latency_ms", 0.0)
            encoded_kb = stream_stat.get("encoded_bytes", 0.0) / 1024.0
            rx_kb = net_stat.get("bytes_recv", 0.0) / 1024.0
            tx_kb = net_stat.get("bytes_sent", 0.0) / 1024.0
            print(
                f"{cid[:17]:17}  {fps:>4.1f}  {stream_latency:>5.1f}  {ping_latency:>5.1f}  "
                f"{encoded_kb:>7.1f}  {rx_kb:>7.1f}  {tx_kb:>7.1f}"
            )

    def _screen_display_loop(self) -> None:
        while True:
            if not self.preview_enabled:
                time.sleep(0.2)
                continue

            with self.stream_lock:
                frame_snapshot = self.latest_frames.copy()
                stats_snapshot = {cid: self.stream_stats.get(cid, {}).copy() for cid in frame_snapshot}

            if not frame_snapshot:
                time.sleep(0.03)
                continue

            for client_id, frame_b64 in frame_snapshot.items():
                try:
                    frame_bytes = base64.b64decode(frame_b64)
                    frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
                    frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    stat = stats_snapshot.get(client_id, {})
                    fps = stat.get("fps", 0.0)
                    latency = stat.get("latency_ms", 0.0)
                    label = f"{client_id} | {fps:.1f} FPS | {latency:.1f} ms"
                    cv2.putText(
                        frame,
                        label,
                        (12, 28),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                        cv2.LINE_AA,
                    )
                    cv2.imshow(f"Screen - {client_id}", frame)
                except cv2.error as exc:
                    if not self._preview_warned:
                        print(f"[SERVER] Preview disabled: {exc}")
                        self._preview_warned = True
                    self.preview_enabled = False
                    break
                except Exception:
                    continue

            try:
                cv2.waitKey(1)
            except cv2.error as exc:
                if not self._preview_warned:
                    print(f"[SERVER] Preview disabled: {exc}")
                    self._preview_warned = True
                self.preview_enabled = False
            time.sleep(0.01)

    def _send_command(
        self,
        target_client_id: str,
        action: str,
        delay_s: int = 0,
        warning_text: str = "",
    ) -> bool:
        with self.clients_lock:
            target = self.clients.get(target_client_id)

        if target is None:
            return False

        payload = {
            "action": action,
            "issued_by": "server",
            "issued_at": time.time(),
            "delay_s": max(0, int(delay_s)),
            "warning_text": str(warning_text),
        }
        sent = send_packet(target.sock, Packet.build(MessageType.COMMAND, sender_id="server", payload=payload))
        self._record_sent(target_client_id, sent)
        return True

    def send_command_all(self, action: str, delay_s: int = 0, warning_text: str = "") -> int:
        """Broadcast a command to ALL connected clients. Returns count of successful sends."""
        with self.clients_lock:
            ids = list(self.clients.keys())
        return sum(1 for cid in ids if self._send_command(cid, action, delay_s, warning_text))

    def _send_volume_ctrl(self, target_client_id: str, cmd: str) -> bool:
        """Send a volume control command (mute/unmute/up/down) to a client."""
        with self.clients_lock:
            target = self.clients.get(target_client_id)
        if target is None:
            return False
        sent = send_packet(
            target.sock,
            Packet.build(MessageType.VOLUME_CTRL, sender_id="server", payload={"cmd": cmd}),
        )
        self._record_sent(target_client_id, sent)
        return True

    def _request_clipboard(self, target_client_id: str) -> bool:
        """Ask a client to send its current clipboard content."""
        with self.clients_lock:
            target = self.clients.get(target_client_id)
        if target is None:
            return False
        sent = send_packet(
            target.sock,
            Packet.build(MessageType.CLIPBOARD, sender_id="server", payload={"op": "get"}),
        )
        self._record_sent(target_client_id, sent)
        return True

    def _push_clipboard(self, target_client_id: str, text: str) -> bool:
        """Push text into a client's clipboard."""
        with self.clients_lock:
            target = self.clients.get(target_client_id)
        if target is None:
            return False
        sent = send_packet(
            target.sock,
            Packet.build(MessageType.CLIPBOARD, sender_id="server", payload={"op": "set", "text": text}),
        )
        self._record_sent(target_client_id, sent)
        return True

    def _request_sysinfo(self, target_client_id: str) -> bool:
        """Ask a client to send a full system-info snapshot."""
        with self.clients_lock:
            target = self.clients.get(target_client_id)
        if target is None:
            return False
        sent = send_packet(
            target.sock,
            Packet.build(MessageType.SYSINFO, sender_id="server", payload={"op": "request"}),
        )
        self._record_sent(target_client_id, sent)
        return True

    def _request_screenshot(self, target_client_id: str, quality: int = 90) -> bool:
        """Ask a client to send a single on-demand high-quality screenshot."""
        with self.clients_lock:
            target = self.clients.get(target_client_id)
        if target is None:
            return False
        sent = send_packet(
            target.sock,
            Packet.build(
                MessageType.SCREENSHOT_REQ,
                sender_id="server",
                payload={"quality": max(50, min(95, quality)), "scale": 1.0},
            ),
        )
        self._record_sent(target_client_id, sent)
        return True

    def pop_command_acks(self) -> list:
        """Drain and return all pending command acknowledgments from clients."""
        with self.command_acks_lock:
            acks = list(self.command_acks_queue)
            self.command_acks_queue.clear()
        return acks

    def pop_sysinfo(self) -> Dict[str, dict]:
        """Drain and return all cached system-info snapshots."""
        with self.sysinfo_lock:
            result = dict(self.sysinfo_store)
            self.sysinfo_store.clear()
        return result

    def pop_clipboard(self) -> Dict[str, str]:
        """Drain and return all cached clipboard responses."""
        with self.clipboard_lock:
            result = dict(self.clipboard_store)
            self.clipboard_store.clear()
        return result

    def pop_screenshots(self) -> Dict[str, str]:
        """Drain and return all on-demand screenshots (client_id -> base64 JPEG)."""
        with self.screenshot_lock:
            result = dict(self.screenshot_store)
            self.screenshot_store.clear()
        return result

    def _command_input_loop(self) -> None:
        print("[SERVER] Command console ready")
        print("[SERVER] Usage: /cmd <client_id> <LOCK|SHUTDOWN|RESTART>")
        print("[SERVER] Usage: /list")
        print("[SERVER] Usage: /select <client_id_or_index>")
        print("[SERVER] Usage: /selected")
        print("[SERVER] Usage: /lock | /shutdown | /restart")
        print("[SERVER] Usage: /dashboard")
        print("[SERVER] Usage: /net")
        print("[SERVER] Usage: /help")

        while True:
            try:
                line = input("[SERVER-CONSOLE] ").strip()
            except EOFError:
                break

            if not line:
                continue

            if line == "/list":
                self._print_connected_clients()
                continue

            if line == "/dashboard":
                self._print_dashboard()
                continue

            if line == "/net":
                self._print_dashboard()
                continue

            if line == "/selected":
                selected = self._get_selected_client()
                print(f"[SERVER] Selected client: {selected if selected else '(none)'}")
                continue

            if line.startswith("/select "):
                token = line.split(maxsplit=1)[1].strip()
                resolved = self._resolve_client_id(token)
                if not resolved:
                    print(f"[SERVER] Client not found for '{token}'. Use /list.")
                    continue
                self._set_selected_client(resolved)
                print(f"[SERVER] Selected client set to: {resolved}")
                continue

            if line == "/lock":
                self._send_selected_command("LOCK")
                continue

            if line == "/shutdown":
                self._send_selected_command("SHUTDOWN")
                continue

            if line == "/restart":
                self._send_selected_command("RESTART")
                continue

            if line == "/help":
                print("[SERVER] /list")
                print("[SERVER] /select <client_id_or_index>")
                print("[SERVER] /selected")
                print("[SERVER] /lock | /shutdown | /restart")
                print("[SERVER] /dashboard")
                print("[SERVER] /net")
                print("[SERVER] /cmd <client_id> <LOCK|SHUTDOWN|RESTART>")
                continue

            if not line.startswith("/cmd "):
                print("[SERVER] Unknown command. Use /cmd or /list")
                continue

            parts = line.split(maxsplit=3)
            if len(parts) < 3:
                print("[SERVER] Usage: /cmd <client_id> <LOCK|SHUTDOWN|RESTART>")
                continue

            target_client_id = parts[1].strip()
            action = parts[2].strip().upper()

            if action not in {"LOCK", "SHUTDOWN", "RESTART"}:
                print("[SERVER] Unsupported action. Allowed: LOCK, SHUTDOWN, RESTART")
                continue

            delivered = self._send_command(target_client_id=target_client_id, action=action)
            if delivered:
                print(f"[SERVER] Command sent: {action} -> {target_client_id}")
            else:
                print(f"[SERVER] Client not found: {target_client_id}")

    def _send_chat(self, target_client_id: str, from_client_id: str, text: str) -> bool:
        with self.clients_lock:
            target = self.clients.get(target_client_id)

        if target is None:
            return False

        payload = {
            "from": from_client_id,
            "to": target_client_id,
            "text": text,
            "sent_at": time.time(),
        }
        sent = send_packet(target.sock, Packet.build(MessageType.CHAT, sender_id="server", payload=payload))
        self._record_sent(target_client_id, sent)
        return True

    def _broadcast_chat(self, from_client_id: str, text: str, exclude_client: Optional[str] = None) -> None:
        with self.clients_lock:
            snapshot = list(self.clients.items())

        for client_id, connection in snapshot:
            if exclude_client and client_id == exclude_client:
                continue
            payload = {
                "from": from_client_id,
                "to": "*",
                "text": text,
                "sent_at": time.time(),
            }
            try:
                sent = send_packet(connection.sock, Packet.build(MessageType.CHAT, sender_id="server", payload=payload))
                self._record_sent(client_id, sent)
            except OSError:
                pass

    def start(self) -> None:
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen()
        print(f"[SERVER] Listening on {self.host}:{self.port}")

        command_thread = threading.Thread(target=self._command_input_loop, daemon=True)
        command_thread.start()

        display_thread = threading.Thread(target=self._screen_display_loop, daemon=True)
        display_thread.start()

        ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        ping_thread.start()

        try:
            while True:
                try:
                    client_sock, client_addr = self.server_socket.accept()
                except ConnectionAbortedError:
                    # Transient on some platforms; keep accepting new sockets.
                    continue
                except OSError:
                    # Ignore brief accept glitches; shutdown path is handled by KeyboardInterrupt/finally.
                    continue
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                thread = threading.Thread(
                    target=self._handle_new_socket,
                    args=(client_sock, client_addr),
                    daemon=True,
                )
                thread.start()
        except KeyboardInterrupt:
            print("\n[SERVER] Shutting down...")
        finally:
            self.shutdown()

    def _handle_new_socket(self, client_sock: socket.socket, client_addr: Tuple[str, int]) -> None:
        client_id = f"{client_addr[0]}:{client_addr[1]}"
        print(f"[SERVER] Incoming socket from {client_id}")

        try:
            first_packet = recv_packet(client_sock)
            if first_packet is None:
                print(f"[SERVER] {client_id} disconnected before authentication")
                client_sock.close()
                return

            if first_packet.msg_type != MessageType.AUTH.value:
                print(f"[SERVER] {client_id} sent invalid handshake packet")
                client_sock.close()
                return

            supplied_password = str(first_packet.payload.get("password", ""))
            if supplied_password != self.password:
                sent = send_packet(
                    client_sock,
                    Packet.build(
                        MessageType.STATUS,
                        sender_id="server",
                        payload={"ok": False, "error": "authentication_failed"},
                    ),
                )
                self._record_sent(client_id, sent)
                print(f"[SERVER] Authentication failed for {client_id}")
                client_sock.close()
                return

            declared_id = first_packet.payload.get("client_name") or first_packet.sender_id
            base_client_id = str(declared_id).strip() or str(first_packet.sender_id)

            with self.clients_lock:
                client_id = base_client_id
                if client_id in self.clients:
                    suffix = 2
                    while f"{base_client_id}-{suffix}" in self.clients:
                        suffix += 1
                    client_id = f"{base_client_id}-{suffix}"
                    print(
                        f"[SERVER] Duplicate client name '{base_client_id}' from {client_addr[0]}:{client_addr[1]}, assigned '{client_id}'"
                    )

                connection = ClientConnection(client_id=client_id, address=client_addr, sock=client_sock)
                self.clients[client_id] = connection

            self._record_recv(client_id, int(getattr(first_packet, "_wire_size", 0)))

            self._print_connected_clients()

            sent = send_packet(
                client_sock,
                Packet.build(
                    MessageType.STATUS,
                    sender_id="server",
                    payload={"ok": True, "message": "authenticated", "client_id": client_id},
                ),
            )
            self._record_sent(client_id, sent)

            while True:
                packet = recv_packet(client_sock)
                if packet is None:
                    break
                self._record_recv(client_id, int(getattr(packet, "_wire_size", 0)))

                if packet.msg_type == MessageType.CHAT.value:
                    text = str(packet.payload.get("text", "")).strip()
                    target = packet.payload.get("to", "*")

                    if not text:
                        continue

                    if target == "*":
                        print(f"[CHAT][{client_id} -> ALL] {text}")
                        self._record_chat_event(client_id, "*", text)
                        self._broadcast_chat(from_client_id=client_id, text=text)
                    else:
                        target_id = str(target)
                        delivered = self._send_chat(
                            target_client_id=target_id,
                            from_client_id=client_id,
                            text=text,
                        )
                        if delivered:
                            print(f"[CHAT][{client_id} -> {target_id}] {text}")
                            self._record_chat_event(client_id, target_id, text)
                            self._send_chat(
                                target_client_id=client_id,
                                from_client_id=client_id,
                                text=f"(to {target_id}) {text}",
                            )
                        else:
                            sent = send_packet(
                                client_sock,
                                Packet.build(
                                    MessageType.STATUS,
                                    sender_id="server",
                                    payload={"ok": False, "error": f"target '{target_id}' not connected"},
                                ),
                            )
                            self._record_sent(client_id, sent)
                    continue

                if packet.msg_type == MessageType.STATUS.value:
                    kind = str(packet.payload.get("kind", ""))
                    if kind == "system_stats":
                        cpu_pct = float(packet.payload.get("cpu_pct", 0.0))
                        ram_pct = float(packet.payload.get("ram_pct", 0.0))
                        self._update_system_usage(client_id, cpu_pct, ram_pct)
                        continue

                    if kind == "command_result":
                        with self.command_acks_lock:
                            self.command_acks_queue.append({
                                "client_id": client_id,
                                "action": str(packet.payload.get("action", "")),
                                "ok": bool(packet.payload.get("ok", False)),
                                "message": str(packet.payload.get("message", "")),
                                "received_at": time.time(),
                            })
                        print(f"[ACK][{client_id}] {packet.payload.get('action','')} ok={packet.payload.get('ok')}")
                        continue

                    if kind in {"volume_result", "file_cancelled", "file_received", "awaiting_save"}:
                        continue

                    print(f"[STATUS][{client_id}] {packet.payload}")
                    continue

                if packet.msg_type == MessageType.PONG.value:
                    ping_ts = float(packet.payload.get("ping_ts", packet.timestamp))
                    latency_ms = max(0.0, (time.time() - ping_ts) * 1000.0)
                    self._update_latency(client_id, latency_ms)
                    continue

                if packet.msg_type == MessageType.SCREEN_FRAME.value:
                    frame_b64 = packet.payload.get("frame_b64")
                    if isinstance(frame_b64, str):
                        # On-demand screenshots go to separate store
                        if packet.payload.get("on_demand"):
                            with self.screenshot_lock:
                                self.screenshot_store[client_id] = frame_b64
                            continue

                        now_ts = time.time()
                        captured_at = float(packet.payload.get("captured_at", now_ts))
                        encoded_bytes = float(packet.payload.get("encoded_bytes", 0.0))
                        with self.stream_lock:
                            self.latest_frames[client_id] = frame_b64
                            stats = self.stream_stats.setdefault(
                                client_id,
                                {
                                    "fps": 0.0,
                                    "latency_ms": 0.0,
                                    "encoded_bytes": 0.0,
                                    "frames_received": 0.0,
                                    "last_frame_at": now_ts,
                                },
                            )

                            dt = now_ts - stats.get("last_frame_at", now_ts)
                            inst_fps = 1.0 / dt if dt > 0 else 0.0
                            prev_fps = stats.get("fps", 0.0)
                            stats["fps"] = inst_fps if prev_fps == 0.0 else (0.8 * prev_fps + 0.2 * inst_fps)
                            stats["latency_ms"] = max(0.0, (now_ts - captured_at) * 1000.0)
                            stats["encoded_bytes"] = encoded_bytes
                            stats["frames_received"] = stats.get("frames_received", 0.0) + 1.0
                            stats["last_frame_at"] = now_ts
                    continue

                if packet.msg_type == MessageType.SYSINFO.value:
                    with self.sysinfo_lock:
                        info = {k: v for k, v in packet.payload.items()}
                        info["_client_id"] = client_id
                        self.sysinfo_store[client_id] = info
                    continue

                if packet.msg_type == MessageType.CLIPBOARD.value:
                    if str(packet.payload.get("op", "")) == "response":
                        with self.clipboard_lock:
                            self.clipboard_store[client_id] = str(packet.payload.get("text", ""))
                    continue

                print(f"[SERVER] Packet from {client_id}: {packet.msg_type}")

        except ConnectionError:
            pass
        except OSError:
            pass
        finally:
            self._remove_client(client_id)
            client_sock.close()

    def _remove_client(self, client_id: str) -> None:
        removed = False
        with self.clients_lock:
            if client_id in self.clients:
                self.clients.pop(client_id, None)
                removed = True

        if removed:
            summary = self._build_session_summary(client_id)
            with self.completed_lock:
                self.completed_sessions[client_id] = summary

        with self.stream_lock:
            self.latest_frames.pop(client_id, None)
            self.stream_stats.pop(client_id, None)

        with self.net_lock:
            self.net_stats.pop(client_id, None)

        if self._get_selected_client() == client_id:
            self._set_selected_client(None)
            print("[SERVER] Selected client disconnected. Selection cleared.")

        try:
            cv2.destroyWindow(f"Screen - {client_id}")
        except Exception:
            pass

        if removed:
            print(f"[SERVER] Disconnected: {client_id}")
            self._print_connected_clients()

    def _print_connected_clients(self) -> None:
        with self.clients_lock:
            client_ids = list(self.clients.keys())

        selected = self._get_selected_client()

        print("[SERVER] Connected clients:")
        if not client_ids:
            print("  - (none)")
            return

        for idx, cid in enumerate(client_ids, start=1):
            marker = "*" if cid == selected else " "
            print(f"  {idx:>2}. [{marker}] {cid}")

    def shutdown(self) -> None:
        with self.clients_lock:
            all_clients = list(self.clients.values())
            self.clients.clear()

        for client in all_clients:
            try:
                client.sock.close()
            except OSError:
                pass

        try:
            self.server_socket.close()
        except OSError:
            pass

        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN Remote Desktop Manager Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server bind IP")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server TCP port")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Shared authentication password")
    args = parser.parse_args()

    server = RemoteManagerServer(args.host, args.port, args.password)
    server.start()


if __name__ == "__main__":
    main()
