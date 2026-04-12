"""
Thread-safe bridge between RemoteManagerServer internals and the PyQt6 UI.

Polls the server's shared dictionaries and emits Qt signals so the UI can
react without touching sockets or threading primitives directly.
"""

import base64
import os
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QImage

from rdm_project.server.core.server import RemoteManagerServer


@dataclass
class _TransferTask:
    task_id: str
    target_client_id: str
    file_path: str
    file_name: str
    total_bytes: int
    status: str = "queued"
    percent: int = 0
    speed_bps: float = 0.0
    eta_s: float = 0.0
    error: str = ""


class ServerBridge(QObject):
    """Adapter that reads server state and emits UI-friendly signals."""

    # ── Signals ──────────────────────────────────────────────────────────────
    clients_changed = pyqtSignal(list)            # [client_id, …]
    frame_received = pyqtSignal(str, QImage)       # (client_id, frame)
    chat_received = pyqtSignal(str, str, str)      # (from, to, text)
    stats_updated = pyqtSignal(dict)               # {client_id: {fps, latency, …}}
    client_disconnected = pyqtSignal(str)          # client_id
    file_transfer_progress = pyqtSignal(str, int, str)  # (client_id, percent, label)
    file_transfer_done = pyqtSignal(bool, str)          # (ok, message)
    session_summary = pyqtSignal(dict)                 # summary payload
    transfer_queue_updated = pyqtSignal(list)          # [{task state}, ...]
    # Phase 2 extended signals
    command_result = pyqtSignal(str, str, bool, str)   # (client_id, action, ok, message)
    sysinfo_received = pyqtSignal(str, dict)            # (client_id, info_dict)
    clipboard_received = pyqtSignal(str, str)           # (client_id, text)
    screenshot_received = pyqtSignal(str, bytes)        # (client_id, jpeg_bytes)

    def __init__(self, server: RemoteManagerServer, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.server = server

        self._prev_client_ids: List[str] = []
        self._chat_log: List[Tuple[str, str, str]] = []  # (from, to, text)
        self._last_frame_ts: Dict[str, float] = {}
        self._last_stats_signature: Optional[tuple] = None

        # Transfer queue state
        self._queue_lock = threading.Lock()
        self._tasks: Dict[str, _TransferTask] = {}
        self._queue: List[str] = []
        self._active_task_id: Optional[str] = None
        self._completed_recent: Deque[str] = deque(maxlen=50)
        self._cancel_active = threading.Event()
        self._stop_queue = threading.Event()
        self._queue_thread = threading.Thread(target=self._transfer_queue_loop, daemon=True)
        self._queue_thread.start()

        # Polling timer — runs on the Qt main thread
        self._timer = QTimer(self)
        self._timer.setInterval(100)  # 100 ms
        self._timer.timeout.connect(self._poll)

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin polling the server for state changes."""
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._stop_queue.set()
        self._cancel_active.set()

    def get_clients(self) -> List[str]:
        """Return a snapshot of current client IDs."""
        with self.server.clients_lock:
            return list(self.server.clients.keys())

    def select_client(self, client_id: Optional[str]) -> None:
        self.server._set_selected_client(client_id)

    def get_selected_client(self) -> Optional[str]:
        return self.server._get_selected_client()

    def send_command(self, client_id: str, action: str) -> bool:
        """Send a command (LOCK / SHUTDOWN / RESTART) to a client."""
        return self.server._send_command(target_client_id=client_id, action=action)

    def send_command_with_options(
        self,
        client_id: str,
        action: str,
        delay_s: int = 0,
        send_warning: bool = True,
    ) -> bool:
        """Send a command with an optional delay and pre-execution warning message."""
        warning = ""
        if send_warning:
            if delay_s > 0:
                warning = (
                    f"\u26a0\ufe0f Server is executing {action} on this machine "
                    f"in {delay_s} seconds. Save your work!"
                )
            else:
                warning = f"\u26a0\ufe0f Server is executing {action} on this machine immediately."
        return self.server._send_command(
            target_client_id=client_id, action=action, delay_s=delay_s, warning_text=warning
        )

    def broadcast_command(
        self,
        action: str,
        delay_s: int = 0,
        send_warning: bool = True,
    ) -> int:
        """Send a command to ALL connected clients. Returns count delivered."""
        warning = ""
        if send_warning:
            if delay_s > 0:
                warning = (
                    f"\u26a0\ufe0f Server is broadcasting {action} to ALL machines "
                    f"in {delay_s} seconds. Save your work!"
                )
            else:
                warning = f"\u26a0\ufe0f Server is broadcasting {action} to ALL machines immediately."
        return self.server.send_command_all(action=action, delay_s=delay_s, warning_text=warning)

    def set_volume(self, client_id: str, cmd: str) -> bool:
        """Send volume command (mute/unmute/up/down) to client."""
        return self.server._send_volume_ctrl(client_id, cmd)

    def request_clipboard(self, client_id: str) -> bool:
        """Request clipboard content from a client."""
        return self.server._request_clipboard(client_id)

    def push_clipboard(self, client_id: str, text: str) -> bool:
        """Push text to a client's clipboard."""
        return self.server._push_clipboard(client_id, text)

    def request_sysinfo(self, client_id: str) -> bool:
        """Request a full system-info snapshot from a client."""
        return self.server._request_sysinfo(client_id)

    def request_screenshot(self, client_id: str) -> bool:
        """Request a high-quality on-demand screenshot from a client."""
        return self.server._request_screenshot(client_id)

    def send_chat(self, text: str, target: str = "*") -> None:
        """Send a chat message from the server to a client (or broadcast)."""
        if target == "*":
            self.server._broadcast_chat(from_client_id="server", text=text)
        else:
            self.server._send_chat(
                target_client_id=target,
                from_client_id="server",
                text=text,
            )
        # Record our own outgoing message for the local chat log
        self._chat_log.append(("server", target, text))
        self.chat_received.emit("server", target, text)

    def send_file_async(self, target_client_id: str, file_path: str) -> None:
        self.enqueue_files(target_client_id, [file_path])

    def enqueue_files(self, target_client_id: str, file_paths: List[str]) -> int:
        added = 0
        with self._queue_lock:
            for path in file_paths:
                file_path = str(path)
                if not file_path:
                    continue
                file_name = os.path.basename(file_path) or "file"
                total = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
                task_id = str(uuid.uuid4())
                task = _TransferTask(
                    task_id=task_id,
                    target_client_id=target_client_id,
                    file_path=file_path,
                    file_name=file_name,
                    total_bytes=total,
                )
                self._tasks[task_id] = task
                self._queue.append(task_id)
                added += 1
        if added:
            self.transfer_queue_updated.emit(self._snapshot_transfer_tasks())
        return added

    def cancel_transfer(self, task_id: str) -> bool:
        queued_cancelled = False
        cancelled_name = ""
        with self._queue_lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False

            if self._active_task_id == task_id and task.status == "in_progress":
                self._cancel_active.set()
                return True

            if task.status == "queued" and task_id in self._queue:
                self._queue.remove(task_id)
                task.status = "cancelled"
                task.error = "Cancelled before start"
                self._completed_recent.appendleft(task_id)
                queued_cancelled = True
                cancelled_name = task.file_name

        if queued_cancelled:
            self.transfer_queue_updated.emit(self._snapshot_transfer_tasks())
            self.file_transfer_done.emit(False, f"Transfer cancelled: {cancelled_name}")
            return True
        return False

    def retry_transfer(self, task_id: str) -> bool:
        with self._queue_lock:
            old = self._tasks.get(task_id)
            if old is None or old.status not in {"failed", "cancelled"}:
                return False

            new_id = str(uuid.uuid4())
            task = _TransferTask(
                task_id=new_id,
                target_client_id=old.target_client_id,
                file_path=old.file_path,
                file_name=old.file_name,
                total_bytes=os.path.getsize(old.file_path) if os.path.isfile(old.file_path) else 0,
            )
            self._tasks[new_id] = task
            self._queue.append(new_id)
        self.transfer_queue_updated.emit(self._snapshot_transfer_tasks())
        return True

    def _snapshot_transfer_tasks(self) -> List[dict]:
        with self._queue_lock:
            ordered_ids: List[str] = []
            if self._active_task_id:
                ordered_ids.append(self._active_task_id)
            ordered_ids.extend([tid for tid in self._queue if tid not in ordered_ids])
            ordered_ids.extend([tid for tid in self._completed_recent if tid not in ordered_ids])

            rows: List[dict] = []
            for tid in ordered_ids[:40]:
                task = self._tasks.get(tid)
                if task is None:
                    continue
                rows.append(
                    {
                        "task_id": task.task_id,
                        "client_id": task.target_client_id,
                        "file_name": task.file_name,
                        "file_path": task.file_path,
                        "status": task.status,
                        "percent": task.percent,
                        "speed_bps": task.speed_bps,
                        "eta_s": task.eta_s,
                        "error": task.error,
                    }
                )
            return rows

    def _transfer_queue_loop(self) -> None:
        while not self._stop_queue.is_set():
            task: Optional[_TransferTask] = None

            with self._queue_lock:
                if self._active_task_id is None and self._queue:
                    task_id = self._queue.pop(0)
                    task = self._tasks.get(task_id)
                    if task is not None:
                        task.status = "in_progress"
                        task.percent = 0
                        task.error = ""
                        self._active_task_id = task_id
                        self._cancel_active.clear()

            if task is None:
                time.sleep(0.08)
                continue

            self.transfer_queue_updated.emit(self._snapshot_transfer_tasks())
            if not os.path.isfile(task.file_path):
                task.status = "failed"
                task.error = "File not found"
                with self._queue_lock:
                    self._completed_recent.appendleft(task.task_id)
                    self._active_task_id = None
                self.transfer_queue_updated.emit(self._snapshot_transfer_tasks())
                self.file_transfer_done.emit(False, f"File missing: {task.file_name}")
                continue

            start_ts = time.time()

            def _progress(done: int, total: int) -> None:
                elapsed = max(0.001, time.time() - start_ts)
                task.percent = int((done / total) * 100.0) if total > 0 else 0
                task.speed_bps = float(done) / elapsed
                remaining = max(0, total - done)
                task.eta_s = float(remaining) / task.speed_bps if task.speed_bps > 0 else 0.0
                self.file_transfer_progress.emit(
                    task.target_client_id,
                    task.percent,
                    f"{done}/{total} bytes @ {self._human_rate(task.speed_bps)} ETA {task.eta_s:.1f}s",
                )
                self.transfer_queue_updated.emit(self._snapshot_transfer_tasks())

            ok = False
            error = ""
            try:
                ok = self.server._send_file(
                    task.target_client_id,
                    task.file_path,
                    progress_callback=_progress,
                    should_cancel=self._cancel_active.is_set,
                )
            except Exception as exc:
                ok = False
                error = str(exc)

            with self._queue_lock:
                cancelled = self._cancel_active.is_set()
                self._cancel_active.clear()
                self._active_task_id = None
                if cancelled and not ok:
                    task.status = "cancelled"
                    task.error = "Cancelled by user"
                elif ok:
                    task.status = "done"
                    task.percent = 100
                    task.eta_s = 0.0
                else:
                    task.status = "failed"
                    task.error = error or "Transfer failed"
                self._completed_recent.appendleft(task.task_id)

            self.transfer_queue_updated.emit(self._snapshot_transfer_tasks())
            if task.status == "done":
                self.file_transfer_done.emit(True, f"File sent: {task.file_name} -> {task.target_client_id}")
            elif task.status == "cancelled":
                self.file_transfer_done.emit(False, f"Transfer cancelled: {task.file_name}")
            else:
                self.file_transfer_done.emit(False, f"Transfer failed: {task.file_name} ({task.error})")

    def _human_rate(self, bps: float) -> str:
        value = max(0.0, float(bps))
        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        idx = 0
        while value >= 1024.0 and idx < len(units) - 1:
            value /= 1024.0
            idx += 1
        return f"{value:.1f} {units[idx]}"

    # ── Polling ──────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        # Unhandled exceptions in PyQt timer slots can terminate the app.
        for step in (
            self._poll_clients,
            self._poll_chat,
            self._poll_frame,
            self._poll_stats,
            self._poll_command_acks,
            self._poll_sysinfo,
            self._poll_clipboard,
            self._poll_screenshots,
        ):
            try:
                step()
            except Exception:
                traceback.print_exc()

    def _poll_chat(self) -> None:
        try:
            events = self.server.pop_chat_events()
        except Exception:
            return

        for from_id, to_id, text in events:
            item = (str(from_id), str(to_id), str(text))
            if item in self._chat_log:
                continue
            self._chat_log.append(item)
            self.chat_received.emit(item[0], item[1], item[2])

    def _poll_clients(self) -> None:
        with self.server.clients_lock:
            current = list(self.server.clients.keys())

        if current != self._prev_client_ids:
            # Check for disconnections
            for cid in self._prev_client_ids:
                if cid not in current:
                    self.client_disconnected.emit(cid)
                    summary = self.server.pop_completed_session_summary(cid)
                    if summary is not None:
                        self.session_summary.emit(summary)
            self._prev_client_ids = current
            self.clients_changed.emit(current)

    def _poll_frame(self) -> None:
        selected = self.server._get_selected_client()
        if not selected:
            return

        with self.server.stream_lock:
            frame_b64 = self.server.latest_frames.get(selected)
            frame_ts = float(self.server.stream_stats.get(selected, {}).get("last_frame_at", 0.0))

        if frame_b64 is None:
            return

        if self._last_frame_ts.get(selected) == frame_ts:
            return

        try:
            raw = base64.b64decode(frame_b64)
            img = QImage.fromData(raw)
            if not img.isNull():
                self._last_frame_ts[selected] = frame_ts
                self.frame_received.emit(selected, img)
        except Exception:
            pass

    def _poll_stats(self) -> None:
        with self.server.clients_lock:
            client_ids = list(self.server.clients.keys())

        combined: Dict[str, dict] = {}
        with self.server.stream_lock:
            for cid in client_ids:
                s = self.server.stream_stats.get(cid, {})
                combined[cid] = {
                    "fps": s.get("fps", 0.0),
                    "stream_latency_ms": s.get("latency_ms", 0.0),
                    "encoded_bytes": s.get("encoded_bytes", 0.0),
                    "last_seen": s.get("last_frame_at", 0.0),
                }

        with self.server.net_lock:
            for cid in client_ids:
                n = self.server.net_stats.get(cid, {})
                entry = combined.get(cid, {})
                entry["ping_ms"] = n.get("latency_ms", 0.0)
                entry["bytes_sent"] = n.get("bytes_sent", 0.0)
                entry["bytes_recv"] = n.get("bytes_recv", 0.0)
                entry["cpu_pct"] = n.get("cpu_pct", 0.0)
                entry["ram_pct"] = n.get("ram_pct", 0.0)
                if float(entry.get("last_seen", 0.0)) <= 0.0:
                    entry["last_seen"] = n.get("connected_at", 0.0)
                combined[cid] = entry

        signature = tuple(
            (cid,
             round(combined[cid].get("fps", 0.0), 2),
             round(combined[cid].get("stream_latency_ms", 0.0), 1),
             round(combined[cid].get("ping_ms", 0.0), 1),
             round(combined[cid].get("cpu_pct", 0.0), 1),
             round(combined[cid].get("ram_pct", 0.0), 1),
             int(combined[cid].get("bytes_sent", 0.0) // 64),
             int(combined[cid].get("bytes_recv", 0.0) // 64),
             int(combined[cid].get("encoded_bytes", 0.0) // 32))
            for cid in sorted(combined.keys())
        )
        if signature == self._last_stats_signature:
            return

        self._last_stats_signature = signature
        self.stats_updated.emit(combined)

    # ── Chat log access ──────────────────────────────────────────────────────

    @property
    def chat_history(self) -> List[Tuple[str, str, str]]:
        return list(self._chat_log)

    # ── Extended polling ─────────────────────────────────────────────────────

    def _poll_command_acks(self) -> None:
        acks = self.server.pop_command_acks()
        for ack in acks:
            self.command_result.emit(
                str(ack.get("client_id", "")),
                str(ack.get("action", "")),
                bool(ack.get("ok", False)),
                str(ack.get("message", "")),
            )

    def _poll_sysinfo(self) -> None:
        data = self.server.pop_sysinfo()
        for client_id, info in data.items():
            self.sysinfo_received.emit(str(client_id), dict(info))

    def _poll_clipboard(self) -> None:
        data = self.server.pop_clipboard()
        for client_id, text in data.items():
            self.clipboard_received.emit(str(client_id), str(text))

    def _poll_screenshots(self) -> None:
        data = self.server.pop_screenshots()
        for client_id, b64_str in data.items():
            try:
                raw = base64.b64decode(b64_str)
                self.screenshot_received.emit(str(client_id), raw)
            except Exception:
                pass
