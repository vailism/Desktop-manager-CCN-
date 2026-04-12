import argparse
import base64
import os
import platform
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import Callable, Optional

import cv2
import mss
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rdm_project.shared.packet import Packet, recv_packet, send_packet
from rdm_project.shared.protocol import MessageType
from rdm_project.client.system.metrics import sample_metrics


class RemoteManagerClient:
    def __init__(
        self,
        server_ip: str,
        server_port: int,
        password: str,
        client_name: str,
        stream_fps: float,
        jpeg_quality: int,
        scale: float,
    ) -> None:
        self.server_ip = server_ip
        self.server_port = server_port
        self.password = password
        self.client_name = client_name
        self.client_id = f"{client_name}-{str(uuid.uuid4())[:8]}"
        self.sock: Optional[socket.socket] = None
        self._reset_socket()
        self.running = False
        self.screen_enabled = True
        self.stream_fps = max(1.0, stream_fps)
        self.jpeg_quality = min(90, max(25, jpeg_quality))
        self.scale = min(1.0, max(0.25, scale))
        self.adaptive_fps = self.stream_fps
        self.adaptive_quality = float(self.jpeg_quality)
        self.last_frame_bytes = 0
        self.bytes_sent = 0
        self.bytes_recv = 0
        self.last_ping_ms = 0.0
        self._bw_prev_sent = 0
        self._bw_prev_ts = time.time()
        self._bw_kbps = 0.0
        self.received_transfers = {}
        self.on_chat_received: Optional[Callable[[str, str, str], None]] = None
        self.on_status_received: Optional[Callable[[dict], None]] = None
        self.on_file_received: Optional[Callable[[str, bytes], None]] = None
        self.on_connection_changed: Optional[Callable[[bool, str], None]] = None
        # Phase-2 callbacks
        self.on_command_received: Optional[Callable[[str, int, str], None]] = None
        self.on_command_countdown: Optional[Callable[[str, int], None]] = None
        self._connect_lock = threading.Lock()

    def _reset_socket(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _update_adaptation(self) -> None:
        now = time.time()
        dt = max(0.2, now - self._bw_prev_ts)
        delta_bytes = max(0, self.bytes_sent - self._bw_prev_sent)
        inst_kbps = (delta_bytes / dt) / 1024.0
        self._bw_kbps = inst_kbps if self._bw_kbps == 0.0 else (0.85 * self._bw_kbps + 0.15 * inst_kbps)
        self._bw_prev_sent = self.bytes_sent
        self._bw_prev_ts = now

        target_fps = self.stream_fps
        target_q = float(self.jpeg_quality)

        if self.last_ping_ms > 140.0 or self._bw_kbps > 2500.0:
            target_fps = max(1.0, self.stream_fps * 0.55)
            target_q = max(30.0, float(self.jpeg_quality) * 0.65)
        elif self.last_ping_ms > 90.0 or self._bw_kbps > 1700.0:
            target_fps = max(1.0, self.stream_fps * 0.75)
            target_q = max(35.0, float(self.jpeg_quality) * 0.78)
        elif self.last_ping_ms > 55.0 or self._bw_kbps > 1200.0:
            target_fps = max(1.0, self.stream_fps * 0.9)
            target_q = max(40.0, float(self.jpeg_quality) * 0.9)

        # Smooth transitions to avoid sudden visual jumps.
        self.adaptive_fps = 0.86 * self.adaptive_fps + 0.14 * target_fps
        self.adaptive_quality = 0.86 * self.adaptive_quality + 0.14 * target_q

    def _send(self, packet: Packet) -> None:
        if self.sock is None:
            raise OSError("socket not initialized")
        sent = send_packet(self.sock, packet)
        self.bytes_sent += sent

    def _print_help(self) -> None:
        print("[CLIENT] Commands:")
        print("[CLIENT] /to <client_id> <message>")
        print("[CLIENT] /stream on|off")
        print("[CLIENT] /stats")
        print("[CLIENT] /quit")

    def _print_stats(self) -> None:
        print("[CLIENT STATS]")
        print(f"  id: {self.client_id}")
        print(f"  stream_enabled: {self.screen_enabled}")
        print(f"  target_fps: {self.stream_fps}")
        print(f"  adaptive_fps: {self.adaptive_fps:.2f}")
        print(f"  jpeg_quality: {self.jpeg_quality}")
        print(f"  adaptive_quality: {self.adaptive_quality:.1f}")
        print(f"  scale: {self.scale}")
        print(f"  ping_ms: {self.last_ping_ms:.1f}")
        print(f"  tx_kbps: {self._bw_kbps:.1f}")
        print(f"  last_frame_kb: {self.last_frame_bytes / 1024.0:.1f}")
        print(f"  tx_kb: {self.bytes_sent / 1024.0:.1f}")
        print(f"  rx_kb: {self.bytes_recv / 1024.0:.1f}")

    def _screen_stream_loop(self) -> None:
        with mss.mss() as screen_capture:
            monitor = screen_capture.monitors[1]

            while self.running:
                if not self.screen_enabled:
                    time.sleep(0.2)
                    continue

                try:
                    screenshot = screen_capture.grab(monitor)
                    frame = np.array(screenshot)
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                    if self.scale < 1.0:
                        frame_bgr = cv2.resize(
                            frame_bgr,
                            None,
                            fx=self.scale,
                            fy=self.scale,
                            interpolation=cv2.INTER_AREA,
                        )

                    ok, encoded = cv2.imencode(
                        ".jpg",
                        frame_bgr,
                        [int(cv2.IMWRITE_JPEG_QUALITY), int(self.adaptive_quality)],
                    )
                    if not ok:
                        time.sleep(1.0 / max(1.0, self.adaptive_fps))
                        continue

                    encoded_bytes = encoded.tobytes()
                    self.last_frame_bytes = len(encoded_bytes)
                    frame_b64 = base64.b64encode(encoded_bytes).decode("ascii")
                    self._send(
                        Packet.build(
                            MessageType.SCREEN_FRAME,
                            sender_id=self.client_id,
                            payload={
                                "frame_b64": frame_b64,
                                "encoding": "jpeg-base64",
                                "fps": self.adaptive_fps,
                                "captured_at": time.time(),
                                "encoded_bytes": self.last_frame_bytes,
                                "jpeg_quality": int(self.adaptive_quality),
                            },
                        )
                    )
                except OSError:
                    break
                except Exception:
                    # Keep stream resilient to transient capture errors.
                    pass

                self._update_adaptation()
                # Limit streaming rate for stable low-latency streaming.
                time.sleep(1.0 / max(1.0, self.adaptive_fps))

    def _system_monitor_loop(self) -> None:
        while self.running:
            try:
                metrics = sample_metrics()
                cpu_pct = float(metrics.get("cpu_pct", 0.0))
                ram_pct = float(metrics.get("ram_pct", 0.0))
                self._send(
                    Packet.build(
                        MessageType.STATUS,
                        sender_id=self.client_id,
                        payload={
                            "ok": True,
                            "kind": "system_stats",
                            "cpu_pct": max(0.0, min(100.0, cpu_pct)),
                            "ram_pct": max(0.0, min(100.0, ram_pct)),
                            "sampled_at": time.time(),
                        },
                    )
                )
            except OSError:
                break
            except Exception:
                # Telemetry must never interrupt stream/chat command behavior.
                pass

            time.sleep(1.0)

    def _action_to_system_command(self, action: str):
        system_name = platform.system().lower()

        if action == "LOCK":
            if system_name == "windows":
                return ["rundll32.exe", "user32.dll,LockWorkStation"]
            if system_name == "linux":
                return ["loginctl", "lock-session"]
            if system_name == "darwin":
                # CGSession is deprecated/missing on modern macOS.
                # pmset displaysleepnow is the reliable cross-version approach.
                return ["pmset", "displaysleepnow"]

        if action == "SHUTDOWN":
            if system_name == "windows":
                return ["shutdown", "/s", "/t", "0"]
            if system_name in {"linux", "darwin"}:
                return ["shutdown", "-h", "now"]

        if action == "RESTART":
            if system_name == "windows":
                return ["shutdown", "/r", "/t", "0"]
            if system_name in {"linux", "darwin"}:
                return ["shutdown", "-r", "now"]

        return None

    def _execute_system_action(self, action: str) -> tuple[bool, str]:
        command = self._action_to_system_command(action)
        if command is None:
            return False, f"unsupported action '{action}' for platform"

        try:
            subprocess.Popen(command)
            return True, f"executed {action}"
        except Exception as exc:
            return False, f"execution failed: {exc}"

    def _execute_volume_command(self, cmd: str) -> tuple[bool, str]:
        """Execute a volume control command on the local machine."""
        system = platform.system().lower()
        try:
            if system == "darwin":
                scripts = {
                    "mute":   "set volume output muted true",
                    "unmute": "set volume output muted false",
                    "up":     "set volume output volume ((output volume of (get volume settings)) + 10)",
                    "down":   "set volume output volume ((output volume of (get volume settings)) - 10)",
                }
                if cmd not in scripts:
                    return False, f"unknown volume command: {cmd}"
                subprocess.run(["osascript", "-e", scripts[cmd]], check=False, timeout=5)
            elif system == "windows":
                cmds = {
                    "mute":   ["nircmd", "mutesysvolume", "1"],
                    "unmute": ["nircmd", "mutesysvolume", "0"],
                    "up":     ["nircmd", "changesysvolume", "6554"],
                    "down":   ["nircmd", "changesysvolume", "-6554"],
                }
                if cmd not in cmds:
                    return False, f"unknown volume command: {cmd}"
                subprocess.run(cmds[cmd], check=False, timeout=5)
            elif system == "linux":
                cmds = {
                    "mute":   ["amixer", "-D", "pulse", "set", "Master", "mute"],
                    "unmute": ["amixer", "-D", "pulse", "set", "Master", "unmute"],
                    "up":     ["amixer", "-D", "pulse", "set", "Master", "10%+"],
                    "down":   ["amixer", "-D", "pulse", "set", "Master", "10%-"],
                }
                if cmd not in cmds:
                    return False, f"unknown volume command: {cmd}"
                subprocess.run(cmds[cmd], check=False, timeout=5)
            else:
                return False, f"unsupported platform: {system}"
            return True, f"volume {cmd} executed"
        except Exception as exc:
            return False, f"volume {cmd} failed: {exc}"

    def _get_clipboard_text(self) -> str:
        """Read the local clipboard and return its text content."""
        system = platform.system().lower()
        try:
            if system == "darwin":
                res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
                return res.stdout
            elif system == "windows":
                import ctypes
                ctypes.windll.user32.OpenClipboard(0)  # type: ignore[attr-defined]
                data = ctypes.windll.user32.GetClipboardData(1)  # type: ignore[attr-defined]
                ctypes.windll.user32.CloseClipboard()  # type: ignore[attr-defined]
                return ctypes.c_char_p(data).value.decode("utf-8", errors="replace") if data else ""
            elif system == "linux":
                for tool in (["xclip", "-o", "-selection", "clipboard"], ["xsel", "--clipboard", "--output"]):
                    try:
                        res = subprocess.run(tool, capture_output=True, text=True, timeout=3)
                        if res.returncode == 0:
                            return res.stdout
                    except FileNotFoundError:
                        continue
        except Exception:
            pass
        return ""

    def _set_clipboard_text(self, text: str) -> None:
        """Write text to the local clipboard."""
        system = platform.system().lower()
        try:
            if system == "darwin":
                proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                proc.communicate(text.encode("utf-8"), timeout=3)
            elif system == "windows":
                import ctypes
                data = text.encode("utf-8") + b"\x00"
                h = ctypes.windll.kernel32.GlobalAlloc(0x0002, len(data))  # type: ignore[attr-defined]
                p = ctypes.windll.kernel32.GlobalLock(h)  # type: ignore[attr-defined]
                ctypes.memmove(p, data, len(data))
                ctypes.windll.kernel32.GlobalUnlock(h)  # type: ignore[attr-defined]
                ctypes.windll.user32.OpenClipboard(0)  # type: ignore[attr-defined]
                ctypes.windll.user32.EmptyClipboard()  # type: ignore[attr-defined]
                ctypes.windll.user32.SetClipboardData(1, h)  # type: ignore[attr-defined]
                ctypes.windll.user32.CloseClipboard()  # type: ignore[attr-defined]
            elif system == "linux":
                for tool in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                    try:
                        proc = subprocess.Popen(tool, stdin=subprocess.PIPE)
                        proc.communicate(text.encode("utf-8"), timeout=3)
                        return
                    except FileNotFoundError:
                        continue
        except Exception:
            pass

    def _gather_sysinfo(self) -> dict:
        """Collect a snapshot of local system information."""
        info: dict = {
            "kind": "sysinfo_response",
            "hostname": socket.gethostname(),
            "platform": platform.system(),
            "platform_version": platform.version(),
            "platform_release": platform.release(),
            "architecture": platform.machine(),
            "processor": platform.processor() or "unknown",
            "python_version": platform.python_version(),
            "gathered_at": time.time(),
        }
        try:
            metrics = sample_metrics()
            info["cpu_pct"] = float(metrics.get("cpu_pct", 0.0))
            info["ram_pct"] = float(metrics.get("ram_pct", 0.0))
        except Exception:
            pass
        try:
            import psutil
            info["cpu_count"] = psutil.cpu_count(logical=True)
            freq = psutil.cpu_freq()
            info["cpu_freq_mhz"] = round(freq.current, 1) if freq else 0
            vm = psutil.virtual_memory()
            info["ram_total_gb"] = round(vm.total / (1024 ** 3), 2)
            info["ram_used_pct"] = round(vm.percent, 1)
            du = psutil.disk_usage("/")
            info["disk_total_gb"] = round(du.total / (1024 ** 3), 2)
            info["disk_used_pct"] = round(du.percent, 1)
            info["uptime_s"] = round(time.time() - psutil.boot_time(), 1)
        except Exception:
            pass
        return info

    def _capture_screenshot(self, quality: int = 90, scale: float = 1.0) -> Optional[str]:
        """Grab the primary screen and return a base64-encoded JPEG string."""
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                shot = sct.grab(monitor)
                frame = np.array(shot)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            if scale < 1.0:
                frame_bgr = cv2.resize(
                    frame_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4
                )
            ok, encoded = cv2.imencode(
                ".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), min(95, max(50, quality))]
            )
            if not ok:
                return None
            return base64.b64encode(encoded.tobytes()).decode("ascii")
        except Exception:
            return None

    def connect(self, interactive: bool = True) -> bool:
        with self._connect_lock:
            if self.running:
                return True

            if self.sock is None:
                self._reset_socket()

            try:
                self.sock.connect((self.server_ip, self.server_port))
            except Exception as exc:
                if self.on_connection_changed:
                    self.on_connection_changed(False, f"Connect failed: {exc}")
                return False

            self.running = True
            print(f"[CLIENT] Connected to server at {self.server_ip}:{self.server_port}")
            if self.on_connection_changed:
                self.on_connection_changed(True, f"Connected to {self.server_ip}:{self.server_port}")

        self._send(
            Packet.build(
                MessageType.AUTH,
                sender_id=self.client_id,
                payload={"client_name": self.client_name, "password": self.password, "phase": 8},
            )
        )

        auth_reply = recv_packet(self.sock)
        if auth_reply is None:
            print("[CLIENT] Server closed during authentication")
            self.running = False
            self.disconnect()
            return False

        self.bytes_recv += int(getattr(auth_reply, "_wire_size", 0))
        if auth_reply.msg_type != MessageType.STATUS.value or not bool(auth_reply.payload.get("ok")):
            print(f"[CLIENT] Authentication failed: {auth_reply.payload}")
            self.running = False
            self.disconnect()
            return False

        print("[CLIENT] Authentication successful")

        receiver_thread = threading.Thread(target=self._receiver_loop, daemon=True)
        receiver_thread.start()

        screen_thread = threading.Thread(target=self._screen_stream_loop, daemon=True)
        screen_thread.start()

        monitor_thread = threading.Thread(target=self._system_monitor_loop, daemon=True)
        monitor_thread.start()

        if not interactive:
            return True

        print("[CLIENT] Chat ready. Send message to all: hello world")
        print("[CLIENT] Send private message: /to <client_id> <message>")
        print("[CLIENT] Stream control: /stream on|off")
        print("[CLIENT] Show stats: /stats")
        print("[CLIENT] Type /quit to disconnect")
        print(
            f"[CLIENT] Screen streaming active at {self.stream_fps:.1f} FPS, "
            f"Q={self.jpeg_quality}, scale={self.scale:.2f}"
        )

        try:
            while self.running:
                text = input("[YOU] ").strip()
                if not text:
                    continue

                if text.lower() == "/quit":
                    break

                if text == "/help":
                    self._print_help()
                    continue

                if text == "/stats":
                    self._print_stats()
                    continue

                if text.startswith("/stream "):
                    mode = text.split(maxsplit=1)[1].strip().lower()
                    if mode == "on":
                        self.screen_enabled = True
                        print("[CLIENT] Screen stream enabled")
                    elif mode == "off":
                        self.screen_enabled = False
                        print("[CLIENT] Screen stream disabled")
                    else:
                        print("[CLIENT] Usage: /stream on|off")
                    continue

                if text.startswith("/to "):
                    parts = text.split(maxsplit=2)
                    if len(parts) < 3:
                        print("[CLIENT] Usage: /to <client_id> <message>")
                        continue

                    target_client_id = parts[1].strip()
                    private_text = parts[2].strip()
                    if not private_text:
                        continue

                    self._send(
                        Packet.build(
                            MessageType.CHAT,
                            sender_id=self.client_id,
                            payload={"to": target_client_id, "text": private_text},
                        )
                    )
                    continue

                self._send(
                    Packet.build(
                        MessageType.CHAT,
                        sender_id=self.client_id,
                        payload={"to": "*", "text": text},
                    )
                )
        except KeyboardInterrupt:
            pass
        finally:
            self.disconnect()

        return True

    def send_chat_message(self, text: str, target: str = "*") -> bool:
        if not self.running:
            return False
        clean = str(text).strip()
        if not clean:
            return False
        self._send(
            Packet.build(
                MessageType.CHAT,
                sender_id=self.client_id,
                payload={"to": target, "text": clean},
            )
        )
        return True

    def set_stream_enabled(self, enabled: bool) -> None:
        self.screen_enabled = bool(enabled)

    def update_media_options(self, fps: float, jpeg_quality: int, scale: float) -> None:
        self.stream_fps = max(1.0, float(fps))
        self.jpeg_quality = min(90, max(25, int(jpeg_quality)))
        self.scale = min(1.0, max(0.25, float(scale)))
        self.adaptive_fps = self.stream_fps
        self.adaptive_quality = float(self.jpeg_quality)

    def reconnect(self, server_port: int, server_ip: Optional[str] = None) -> bool:
        with self._connect_lock:
            if server_ip:
                self.server_ip = server_ip
            self.server_port = int(server_port)

            self.running = False
            self.received_transfers.clear()

            old_sock = self.sock
            self.sock = None
            if old_sock is not None:
                try:
                    old_sock.close()
                except OSError:
                    pass

            self._reset_socket()

        if self.on_connection_changed:
            self.on_connection_changed(False, "Disconnected")

        return self.connect(interactive=False)

    def _receiver_loop(self) -> None:
        while self.running:
            try:
                if self.sock is None:
                    self.running = False
                    break
                packet = recv_packet(self.sock)
                if packet is None:
                    print("[CLIENT] Server closed the connection")
                    self.running = False
                    break
                self.bytes_recv += int(getattr(packet, "_wire_size", 0))

                if packet.msg_type == MessageType.STATUS.value:
                    print(f"[CLIENT] Server status: {packet.payload}")
                    if self.on_status_received:
                        self.on_status_received(dict(packet.payload))
                elif packet.msg_type == MessageType.CHAT.value:
                    from_client = packet.payload.get("from", "unknown")
                    chat_text = packet.payload.get("text", "")
                    target = packet.payload.get("to", "*")
                    if target == "*":
                        print(f"[CHAT][{from_client}] {chat_text}")
                    else:
                        print(f"[CHAT][{from_client} -> {target}] {chat_text}")
                    if self.on_chat_received:
                        self.on_chat_received(str(from_client), str(target), str(chat_text))
                elif packet.msg_type == MessageType.COMMAND.value:
                    action = str(packet.payload.get("action", "")).upper()
                    delay_s = max(0, int(packet.payload.get("delay_s", 0)))
                    warning_text = str(packet.payload.get("warning_text", ""))

                    if action not in {"LOCK", "SHUTDOWN", "RESTART"}:
                        print(f"[CLIENT] Unsupported command received: {action}")
                        self._send(
                            Packet.build(
                                MessageType.STATUS,
                                sender_id=self.client_id,
                                payload={
                                    "ok": False,
                                    "kind": "command_result",
                                    "action": action,
                                    "message": "unsupported command",
                                },
                            )
                        )
                        continue

                    print(f"[CLIENT] Command '{action}' received (delay={delay_s}s)")

                    # Notify UI / tray immediately
                    if self.on_command_received:
                        self.on_command_received(action, delay_s, warning_text)

                    # Execute (with optional countdown) in a background thread
                    def _exec_with_delay(
                        a: str, d: int, _warn: str,
                        _self=self,
                    ) -> None:
                        if d > 0:
                            # Notify at salient points: 75%, 50%, 25%, 10s, 5s, 3s, 1s
                            notif_points = sorted(
                                {max(1, d * 3 // 4), max(1, d // 2), max(1, d // 4), 10, 5, 3, 1},
                                reverse=True,
                            )
                            notif_points = [p for p in notif_points if p < d]
                            start = time.time()
                            last_notif = d
                            while True:
                                elapsed = time.time() - start
                                remaining = d - int(elapsed)
                                if remaining <= 0:
                                    break
                                if remaining < last_notif and remaining in notif_points:
                                    if _self.on_command_countdown:
                                        _self.on_command_countdown(a, remaining)
                                    print(f"[CLIENT] {a} in {remaining}s…")
                                    last_notif = remaining
                                time.sleep(0.5)

                        ok, msg = _self._execute_system_action(a)
                        try:
                            _self._send(
                                Packet.build(
                                    MessageType.STATUS,
                                    sender_id=_self.client_id,
                                    payload={
                                        "ok": ok,
                                        "kind": "command_result",
                                        "action": a,
                                        "message": msg,
                                    },
                                )
                            )
                        except Exception:
                            pass

                    threading.Thread(
                        target=_exec_with_delay,
                        args=(action, delay_s, warning_text),
                        daemon=True,
                    ).start()
                elif packet.msg_type == MessageType.PING.value:
                    ping_ts = float(packet.payload.get("ping_ts", packet.timestamp))
                    self.last_ping_ms = max(0.0, (time.time() - ping_ts) * 1000.0)
                    self._send(
                        Packet.build(
                            MessageType.PONG,
                            sender_id=self.client_id,
                            payload={"ping_ts": ping_ts},
                        )
                    )
                elif packet.msg_type == MessageType.VOLUME_CTRL.value:
                    cmd = str(packet.payload.get("cmd", "")).lower()
                    ok, message = self._execute_volume_command(cmd)
                    try:
                        self._send(
                            Packet.build(
                                MessageType.STATUS,
                                sender_id=self.client_id,
                                payload={"ok": ok, "kind": "volume_result", "cmd": cmd, "message": message},
                            )
                        )
                    except Exception:
                        pass
                elif packet.msg_type == MessageType.CLIPBOARD.value:
                    op = str(packet.payload.get("op", ""))
                    if op == "get":
                        text = self._get_clipboard_text()
                        self._send(
                            Packet.build(
                                MessageType.CLIPBOARD,
                                sender_id=self.client_id,
                                payload={"op": "response", "text": text},
                            )
                        )
                    elif op == "set":
                        self._set_clipboard_text(str(packet.payload.get("text", "")))
                elif packet.msg_type == MessageType.SYSINFO.value:
                    if str(packet.payload.get("op", "")) == "request":
                        info = self._gather_sysinfo()
                        self._send(Packet.build(MessageType.SYSINFO, sender_id=self.client_id, payload=info))
                elif packet.msg_type == MessageType.SCREENSHOT_REQ.value:
                    quality = int(packet.payload.get("quality", 90))
                    scale = float(packet.payload.get("scale", 1.0))
                    frame_b64 = self._capture_screenshot(quality=quality, scale=scale)
                    if frame_b64:
                        self._send(
                            Packet.build(
                                MessageType.SCREEN_FRAME,
                                sender_id=self.client_id,
                                payload={
                                    "frame_b64": frame_b64,
                                    "encoding": "jpeg-base64",
                                    "captured_at": time.time(),
                                    "encoded_bytes": len(frame_b64),
                                    "on_demand": True,
                                },
                            )
                        )
                elif packet.msg_type == MessageType.FILE_META.value:
                    transfer_id = str(packet.payload.get("transfer_id", ""))
                    file_name = str(packet.payload.get("name", "received_file"))
                    total_size = int(packet.payload.get("size", 0))
                    if not transfer_id:
                        continue
                    self.received_transfers[transfer_id] = {
                        "name": file_name,
                        "size": total_size,
                        "recv": 0,
                        "chunks": bytearray(),
                    }
                    print(f"[CLIENT] Receiving file: {file_name} ({total_size} bytes)")
                elif packet.msg_type == MessageType.FILE_CHUNK.value:
                    transfer_id = str(packet.payload.get("transfer_id", ""))
                    data_b64 = packet.payload.get("data", "")
                    state = self.received_transfers.get(transfer_id)
                    if state is None or not isinstance(data_b64, str):
                        continue
                    data = base64.b64decode(data_b64)
                    state["chunks"].extend(data)
                    state["recv"] += len(data)
                elif packet.msg_type == MessageType.FILE_END.value:
                    transfer_id = str(packet.payload.get("transfer_id", ""))
                    cancelled = bool(packet.payload.get("cancelled", False))
                    state = self.received_transfers.pop(transfer_id, None)
                    if state is None:
                        continue
                    if cancelled:
                        print(f"[CLIENT] File transfer cancelled: {state['name']}")
                        self._send(
                            Packet.build(
                                MessageType.STATUS,
                                sender_id=self.client_id,
                                payload={
                                    "ok": False,
                                    "kind": "file_cancelled",
                                    "name": state["name"],
                                    "bytes": state["recv"],
                                },
                            )
                        )
                        continue

                    file_bytes = bytes(state["chunks"])
                    if self.on_file_received:
                        self.on_file_received(str(state["name"]), file_bytes)

                    print(f"[CLIENT] File received in memory: {state['name']}")
                    self._send(
                        Packet.build(
                            MessageType.STATUS,
                            sender_id=self.client_id,
                            payload={
                                "ok": True,
                                "kind": "file_received",
                                "name": state["name"],
                                "awaiting_save": True,
                                "bytes": state["recv"],
                            },
                        )
                    )
                else:
                    print(f"[CLIENT] Received packet: {packet.msg_type} -> {packet.payload}")

            except OSError:
                self.running = False
                break

        if self.on_connection_changed:
            self.on_connection_changed(False, "Disconnected")

    def disconnect(self) -> None:
        with self._connect_lock:
            was_running = self.running
            self.running = False
            self.received_transfers.clear()
            old_sock = self.sock
            self.sock = None

        try:
            if old_sock is not None:
                old_sock.close()
        except OSError:
            pass

        if self.on_connection_changed:
            self.on_connection_changed(False, "Disconnected")

        if was_running:
            print("[CLIENT] Disconnected")


class ClientUiSignals(QObject):
    chat = pyqtSignal(str, str, str)
    status = pyqtSignal(str)
    connection = pyqtSignal(bool, str)


class ClientWindow(QMainWindow):
    def __init__(self, client: RemoteManagerClient) -> None:
        super().__init__()
        self.client = client
        self.signals = ClientUiSignals()
        self.connected_since_epoch: Optional[float] = None
        self._is_connected = False

        self.setWindowTitle("Remote Desktop Client")
        self.setMinimumSize(600, 500)
        self.resize(660, 540)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # ── Top Bar ───────────────────────────────────
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(16, 12, 16, 12)
        tb.setSpacing(12)

        self.status_label = QLabel("\u25CF Disconnected")
        self.status_label.setObjectName("TopStatus")
        self.status_label.setStyleSheet("color: #f87171; font-weight: 700; font-size: 13px;")
        tb.addWidget(self.status_label)

        tb.addStretch(1)

        self.connected_since_label = QLabel("Uptime: --")
        self.connected_since_label.setObjectName("ConnectedSince")
        tb.addWidget(self.connected_since_label)

        self.server_label = QLabel("")
        self.server_label.setObjectName("TopEndpoint")
        tb.addWidget(self.server_label)
        layout.addWidget(top_bar)

        # ── Connection Card ───────────────────────────
        connection_card = QFrame()
        connection_card.setObjectName("Card")
        cl = QVBoxLayout(connection_card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)

        conn_hdr = QLabel("CONNECTION")
        conn_hdr.setStyleSheet(
            "color: #6e6e76; font-size: 10px; font-weight: 700; "
            "letter-spacing: 1.2px; background: transparent; padding: 0;"
        )
        cl.addWidget(conn_hdr)

        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(8)

        port_lbl = QLabel("Port")
        port_lbl.setObjectName("FieldLabel")
        switch_row.addWidget(port_lbl)

        self.port_input = QLineEdit(str(self.client.server_port))
        self.port_input.setObjectName("PortInput")
        self.port_input.setFixedWidth(90)
        self.port_input.setFixedHeight(36)
        self.port_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.port_input.returnPressed.connect(self._switch_port)
        switch_row.addWidget(self.port_input)

        self.switch_btn = QPushButton("Switch")
        self.switch_btn.setObjectName("SecondaryBtn")
        self.switch_btn.setFixedSize(90, 36)
        self.switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switch_btn.clicked.connect(self._switch_port)
        switch_row.addWidget(self.switch_btn)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("PrimaryBtn")
        self.connect_btn.setFixedSize(100, 36)
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.clicked.connect(self._connect_now)
        self.connect_btn.setEnabled(False)
        switch_row.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("SecondaryBtn")
        self.disconnect_btn.setFixedSize(110, 36)
        self.disconnect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        switch_row.addWidget(self.disconnect_btn)

        switch_row.addStretch(1)
        cl.addLayout(switch_row)
        layout.addWidget(connection_card)

        # ── Stream Settings Card ──────────────────────
        stream_card = QFrame()
        stream_card.setObjectName("Card")
        sl = QVBoxLayout(stream_card)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.setSpacing(10)

        stream_hdr = QLabel("STREAM SETTINGS")
        stream_hdr.setStyleSheet(
            "color: #6e6e76; font-size: 10px; font-weight: 700; "
            "letter-spacing: 1.2px; background: transparent; padding: 0;"
        )
        sl.addWidget(stream_hdr)

        media_row = QHBoxLayout()
        media_row.setContentsMargins(0, 0, 0, 0)
        media_row.setSpacing(8)

        self.stream_btn = QPushButton("Stream: On")
        self.stream_btn.setObjectName("PrimaryBtn")
        self.stream_btn.setFixedSize(120, 36)
        self.stream_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stream_btn.clicked.connect(self._toggle_stream)
        self.stream_btn.setEnabled(False)
        media_row.addWidget(self.stream_btn)

        for label_text, default_val, width, attr_name in [
            ("FPS", f"{self.client.stream_fps:.1f}", 60, "fps_input"),
            ("Q", str(self.client.jpeg_quality), 55, "quality_input"),
            ("Scale", f"{self.client.scale:.2f}", 60, "scale_input"),
        ]:
            lbl = QLabel(label_text)
            lbl.setObjectName("FieldLabel")
            media_row.addWidget(lbl)
            inp = QLineEdit(default_val)
            inp.setObjectName("MediaInput")
            inp.setFixedSize(width, 36)
            inp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            setattr(self, attr_name, inp)
            media_row.addWidget(inp)

        self.apply_media_btn = QPushButton("Apply")
        self.apply_media_btn.setObjectName("SecondaryBtn")
        self.apply_media_btn.setFixedSize(90, 36)
        self.apply_media_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_media_btn.clicked.connect(self._apply_media)
        self.apply_media_btn.setEnabled(False)
        media_row.addWidget(self.apply_media_btn)

        media_row.addStretch(1)
        sl.addLayout(media_row)
        layout.addWidget(stream_card)

        # ── Activity Log Card ─────────────────────────
        log_card = QFrame()
        log_card.setObjectName("Card")
        ll = QVBoxLayout(log_card)
        ll.setContentsMargins(16, 14, 16, 14)
        ll.setSpacing(10)

        log_hdr = QLabel("ACTIVITY LOG")
        log_hdr.setStyleSheet(
            "color: #6e6e76; font-size: 10px; font-weight: 700; "
            "letter-spacing: 1.2px; background: transparent; padding: 0;"
        )
        ll.addWidget(log_hdr)

        self.messages = QTextEdit()
        self.messages.setObjectName("MessagePanel")
        self.messages.setReadOnly(True)
        ll.addWidget(self.messages, stretch=1)
        layout.addWidget(log_card, stretch=1)

        # ── Chat Input Card ──────────────────────────
        input_card = QFrame()
        input_card.setObjectName("Card")
        il = QVBoxLayout(input_card)
        il.setContentsMargins(16, 12, 16, 12)
        il.setSpacing(0)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(10)

        self.input_box = QLineEdit()
        self.input_box.setObjectName("InputBox")
        self.input_box.setPlaceholderText("Type message to server or all clients\u2026")
        self.input_box.setMinimumHeight(40)
        self.input_box.returnPressed.connect(self._send_message)
        input_row.addWidget(self.input_box, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("PrimaryBtn")
        self.send_btn.setFixedSize(90, 40)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._send_message)
        self.send_btn.setEnabled(False)
        input_row.addWidget(self.send_btn)

        il.addLayout(input_row)
        layout.addWidget(input_card)

        # ── Signal connections ────────────────────────
        self.signals.chat.connect(self._append_chat)
        self.signals.status.connect(self._append_status)
        self.signals.connection.connect(self._set_connection_state)

        self.client.on_chat_received = lambda f, t, m: self.signals.chat.emit(f, t, m)
        self.client.on_status_received = lambda s: self.signals.status.emit(str(s))
        self.client.on_connection_changed = lambda ok, text: self.signals.connection.emit(ok, text)
        self.client.on_command_received = self._on_remote_command
        self.client.on_command_countdown = self._on_command_countdown

        self.tray_icon: Optional[QSystemTrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation), self
            )
            self.tray_icon.setToolTip("Remote Desktop Client")
            self.tray_icon.show()

        # Connected time live timer
        self.connected_timer = QTimer(self)
        self.connected_timer.setInterval(1000)
        self.connected_timer.timeout.connect(self._update_connected_since_label)
        self.connected_timer.start()

        # ── Premium stylesheet ────────────────────────
        self.setStyleSheet("""
            QMainWindow {
                background: #0a0a0c;
            }
            QWidget {
                color: #f5f5f7;
                font-family: 'SF Pro Display', 'SF Pro Text', '-apple-system',
                             'Helvetica Neue', 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QLabel {
                color: #a1a1a8;
                font-size: 12px;
                background: transparent;
            }
            #TopBar {
                background: #101014;
                border: 1px solid #222228;
                border-radius: 14px;
            }
            #TopStatus {
                font-weight: 700;
                font-size: 13px;
                letter-spacing: -0.2px;
            }
            #TopEndpoint {
                color: #48484f;
                font-weight: 500;
                font-size: 11px;
                letter-spacing: 0.3px;
                font-family: 'SF Mono', 'JetBrains Mono', 'Menlo', monospace;
            }
            #ConnectedSince {
                color: #6e6e76;
                font-size: 11px;
                font-weight: 600;
                font-family: 'SF Mono', 'JetBrains Mono', 'Menlo', monospace;
                letter-spacing: 0.2px;
            }
            #Card {
                background: #18181c;
                border: 1px solid #222228;
                border-radius: 14px;
            }
            #FieldLabel {
                color: #6e6e76;
                font-weight: 600;
                font-size: 11px;
                letter-spacing: 0.5px;
            }
            #MessagePanel {
                background: #0e0e12;
                border: 1px solid #222228;
                border-radius: 10px;
                padding: 12px 14px;
                font-family: 'SF Mono', 'JetBrains Mono', 'Menlo',
                             'Fira Code', monospace;
                font-size: 11px;
                line-height: 1.5;
                color: #a1a1a8;
            }
            #InputBox {
                background: #0e0e12;
                border: 1px solid #222228;
                border-radius: 10px;
                padding: 10px 14px;
                color: #f5f5f7;
                font-size: 13px;
                selection-background-color: #5b5ff7;
            }
            #InputBox:focus {
                border-color: #5b5ff7;
            }
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                            stop:0 #5b5ff7, stop:1 #a855f7);
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px 18px;
                font-weight: 600;
                font-size: 12px;
                letter-spacing: -0.1px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                            stop:0 #7b7fff, stop:1 #c084fc);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                            stop:0 #4338ca, stop:1 #9333ea);
            }
            QPushButton:disabled {
                background: #18181c;
                color: #48484f;
                border: 1px solid #222228;
            }
            #SecondaryBtn {
                background: #18181c;
                border: 1px solid #222228;
                color: #a1a1a8;
            }
            #SecondaryBtn:hover {
                background: #28282f;
                color: #f5f5f7;
                border-color: #5b5ff7;
            }
            #SecondaryBtn:pressed {
                background: #1e1e23;
            }
            #SecondaryBtn:disabled {
                background: #18181c;
                color: #48484f;
                border: 1px solid #222228;
            }
            #PrimaryBtn {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                            stop:0 #5b5ff7, stop:1 #a855f7);
            }
            #PrimaryBtn:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                                            stop:0 #7b7fff, stop:1 #c084fc);
            }
            #PrimaryBtn:disabled {
                background: #18181c;
                color: #48484f;
                border: 1px solid #222228;
            }
            #PortInput,
            #MediaInput {
                background: #0e0e12;
                border: 1px solid #222228;
                border-radius: 8px;
                padding: 7px 10px;
                color: #f5f5f7;
                font-size: 12px;
                font-weight: 600;
                font-family: 'SF Mono', 'JetBrains Mono', monospace;
            }
            #PortInput:focus,
            #MediaInput:focus {
                border-color: #5b5ff7;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 4px 1px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #28282f;
                min-height: 32px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3a3a44;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical { background: transparent; }
            QScrollBar:horizontal { height: 0; }
        """)

        self._refresh_endpoint_label(False)
        self.input_box.setEnabled(False)
        self._start_connect_thread()

    def _start_connect_thread(self) -> None:
        self.switch_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)

        def _connect() -> None:
            try:
                ok = self.client.connect(interactive=False)
                if not ok:
                    self.signals.connection.emit(False, "Auth failed or disconnected")
            except Exception as exc:
                self.signals.connection.emit(False, f"Connection failed: {exc}")
            finally:
                self.signals.status.emit("__switch_ready__")

        threading.Thread(target=_connect, daemon=True).start()

    def _append_chat(self, from_id: str, to_id: str, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        target_suffix = "" if to_id == "*" else f" -> {to_id}"
        self.messages.append(
            f"<div><span style='color:#22d3ee;font-weight:700'>{from_id}{target_suffix}</span> "
            f"<span style='color:#94a3b8;font-size:10px'>{ts}</span><br>"
            f"<span style='color:#e5e7eb'>{text}</span></div>"
        )
        if self.tray_icon is not None:
            self.tray_icon.showMessage("New message", f"{from_id}{target_suffix}: {text}", QSystemTrayIcon.MessageIcon.Information, 3500)

    def _append_status(self, payload: str) -> None:
        if payload == "__switch_ready__":
            self.switch_btn.setEnabled(True)
            self.connect_btn.setEnabled(not self.client.running)
            return
        self.messages.append(f"<span style='color:#a78bfa'>[status]</span> <span style='color:#cbd5e1'>{payload}</span>")

    def _refresh_endpoint_label(self, connected: bool) -> None:
        self.server_label.setText(f"{self.client.server_ip}:{self.client.server_port}")

    def _set_connection_state(self, connected: bool, text: str) -> None:
        if connected and not self._is_connected:
            self.connected_since_epoch = time.time()
        if not connected:
            self.connected_since_epoch = None
        self._is_connected = connected

        self.status_label.setText("\u25CF Connected" if connected else "\u25CF Disconnected")
        self.status_label.setStyleSheet(
            "color: #22c55e; font-weight: 700; font-size: 13px;" if connected
            else "color: #f87171; font-weight: 700; font-size: 13px;"
        )
        self._refresh_endpoint_label(connected)
        self._update_connected_since_label()
        if text:
            self.messages.append(f"<span style='color:#93c5fd'>{text}</span>")
        # Keep disconnect available so users can always force a clean reset.
        self.disconnect_btn.setEnabled(True)
        self.connect_btn.setEnabled(not connected)
        self.send_btn.setEnabled(connected)
        self.input_box.setEnabled(connected)
        self.stream_btn.setEnabled(connected)
        self.apply_media_btn.setEnabled(connected)

    def _update_connected_since_label(self) -> None:
        if self.connected_since_epoch is None:
            self.connected_since_label.setText("Uptime: --")
            return

        elapsed = max(0, int(time.time() - self.connected_since_epoch))
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        if hours > 0:
            self.connected_since_label.setText(f"Uptime: {hours}h {minutes}m {seconds}s")
        elif minutes > 0:
            self.connected_since_label.setText(f"Uptime: {minutes}m {seconds}s")
        else:
            self.connected_since_label.setText(f"Uptime: {seconds}s")

    def _toggle_stream(self) -> None:
        enabled = not self.client.screen_enabled
        self.client.set_stream_enabled(enabled)
        self.stream_btn.setText("Stream: On" if enabled else "Stream: Off")
        self.messages.append(
            f"<span style='color:#93c5fd'>Streaming {'enabled' if enabled else 'paused'}.</span>"
        )

    def _apply_media(self) -> None:
        try:
            fps = float(self.fps_input.text().strip())
            quality = int(self.quality_input.text().strip())
            scale = float(self.scale_input.text().strip())
            if fps < 1.0 or quality < 25 or quality > 90 or scale < 0.25 or scale > 1.0:
                raise ValueError("out of range")
        except Exception:
            self.messages.append(
                "<span style='color:#f87171'>Invalid media values. FPS>=1, Q=25..90, Scale=0.25..1.0</span>"
            )
            return

        self.client.update_media_options(fps=fps, jpeg_quality=quality, scale=scale)
        self.messages.append(
            f"<span style='color:#93c5fd'>Media updated: FPS={fps:.1f}, Q={quality}, Scale={scale:.2f}</span>"
        )

    def _send_message(self) -> None:
        text = self.input_box.text().strip()
        if not text:
            return
        ok = self.client.send_chat_message(text, "*")
        if ok:
            self.input_box.clear()
            return
        self.messages.append("<span style='color:#f87171'>Cannot send: client is disconnected.</span>")

    def _disconnect(self) -> None:
        self.messages.append("<span style='color:#93c5fd'>Disconnect requested.</span>")
        self.client.disconnect()
        self.client._reset_socket()
        self._set_connection_state(False, "Disconnected")

    def _switch_port(self) -> None:
        raw = self.port_input.text().strip()
        try:
            port = int(raw)
            if port < 1 or port > 65535:
                raise ValueError("port out of range")
        except Exception:
            self.messages.append("<span style='color:#f87171'>Invalid port. Use 1-65535.</span>")
            return

        self.messages.append(f"<span style='color:#67e8f9'>Switching to port {port}...</span>")
        self.switch_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)

        def _reconnect() -> None:
            ok = self.client.reconnect(port)
            if not ok:
                self.signals.connection.emit(False, f"Failed to connect on port {port}")
            self.signals.status.emit("__switch_ready__")

        threading.Thread(target=_reconnect, daemon=True).start()

    def _connect_now(self) -> None:
        raw = self.port_input.text().strip()
        try:
            port = int(raw)
            if port < 1 or port > 65535:
                raise ValueError("port out of range")
        except Exception:
            self.messages.append("<span style='color:#f87171'>Invalid port. Use 1-65535.</span>")
            return

        self.messages.append(f"<span style='color:#67e8f9'>Connect requested on port {port}...</span>")
        self.connect_btn.setEnabled(False)
        self.switch_btn.setEnabled(False)

        def _reconnect() -> None:
            ok = self.client.reconnect(port)
            if not ok:
                self.signals.connection.emit(False, f"Failed to connect on port {port}")
            self.signals.status.emit("__switch_ready__")

        threading.Thread(target=_reconnect, daemon=True).start()

    def _on_remote_command(self, action: str, delay_s: int, warning_text: str) -> None:
        """Show a tray notification and log entry when a remote command is received."""
        msg = warning_text or f"Server is executing {action} on this machine."
        if self.tray_icon is not None:
            self.tray_icon.showMessage(
                f"\u26A0\uFE0F Remote Command: {action}",
                msg,
                QSystemTrayIcon.MessageIcon.Warning,
                max(5000, delay_s * 1000),
            )
        self.signals.status.emit(f"\u26A0\uFE0F {action} command received (delay={delay_s}s)")

    def _on_command_countdown(self, action: str, remaining: int) -> None:
        """Show a countdown tray balloon at each salient tick before command executes."""
        if self.tray_icon is not None:
            self.tray_icon.showMessage(
                f"\u23F1\uFE0F {action} in {remaining}s",
                "Save your work now!",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.client.disconnect()
        super().closeEvent(event)



def run_client_ui(client: RemoteManagerClient) -> None:
    app = QApplication([])
    app.setFont(QFont("SF Pro Display", 13))
    window = ClientWindow(client)
    window.show()
    app.exec()


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN Remote Desktop Manager Client - Phase 8")
    parser.add_argument("--server-ip", required=True, help="Server IP address")
    parser.add_argument("--server-port", type=int, default=5500, help="Server TCP port")
    parser.add_argument("--password", default="lan-demo-123", help="Shared authentication password")
    parser.add_argument("--name", default="client", help="Client display name")
    parser.add_argument("--fps", type=float, default=2.0, help="Screen stream FPS")
    parser.add_argument("--jpeg-quality", type=int, default=45, help="JPEG quality (25-90)")
    parser.add_argument("--scale", type=float, default=0.75, help="Frame scale (0.25-1.0)")
    parser.add_argument("--ui", action=argparse.BooleanOptionalAction, default=True, help="Run lightweight PyQt6 UI")
    args = parser.parse_args()

    client = RemoteManagerClient(
        args.server_ip,
        args.server_port,
        args.password,
        args.name,
        args.fps,
        args.jpeg_quality,
        args.scale,
    )
    if args.ui:
        run_client_ui(client)
    else:
        client.connect(interactive=True)


if __name__ == "__main__":
    main()
