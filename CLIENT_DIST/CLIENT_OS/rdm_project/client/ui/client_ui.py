"""Client dashboard UI for the Remote Desktop Manager."""

import socket
import threading
from datetime import datetime

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rdm_project.client.core.client import RemoteManagerClient


class UiSignals(QObject):
    connection = pyqtSignal(bool, str)
    chat = pyqtSignal(str, str, str)
    status = pyqtSignal(str)
    file_received = pyqtSignal(str, object)


class ClientDashboard(QMainWindow):
    def __init__(self, client: RemoteManagerClient, auto_connect: bool = False) -> None:
        super().__init__()
        self.client = client
        self.signals = UiSignals()
        self._connect_attempt_in_progress = False

        self.setWindowTitle("RDM Client")
        self.resize(920, 650)

        root = QWidget()
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(20, 20, 20, 20)
        page.setSpacing(14)

        top_card = QFrame()
        top_card.setObjectName("Card")
        top = QHBoxLayout(top_card)
        top.setContentsMargins(16, 14, 16, 14)
        top.setSpacing(10)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("StatusDotOffline")
        top.addWidget(self.status_dot)

        self.status_label = QLabel("Disconnected")
        self.status_label.setObjectName("StatusText")
        top.addWidget(self.status_label)

        top.addStretch(1)

        self.endpoint_label = QLabel(self._endpoint_text())
        self.endpoint_label.setObjectName("Endpoint")
        top.addWidget(self.endpoint_label)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._connect)
        top.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        top.addWidget(self.disconnect_btn)

        page.addWidget(top_card)

        connection_card = QFrame()
        connection_card.setObjectName("Card")
        connection_layout = QGridLayout(connection_card)
        connection_layout.setContentsMargins(16, 14, 16, 14)
        connection_layout.setHorizontalSpacing(12)
        connection_layout.setVerticalSpacing(10)

        connection_layout.addWidget(QLabel("Connection Panel"), 0, 0, 1, 6)

        connection_layout.addWidget(QLabel("Server IP"), 1, 0)
        self.ip_input = QLineEdit(self.client.server_ip)
        connection_layout.addWidget(self.ip_input, 1, 1, 1, 2)

        connection_layout.addWidget(QLabel("Port"), 1, 3)
        self.port_input = QLineEdit(str(self.client.server_port))
        connection_layout.addWidget(self.port_input, 1, 4)

        self.reconnect_btn = QPushButton("Reconnect")
        self.reconnect_btn.clicked.connect(self._reconnect)
        connection_layout.addWidget(self.reconnect_btn, 1, 5)

        page.addWidget(connection_card)

        stream_card = QFrame()
        stream_card.setObjectName("Card")
        stream_layout = QGridLayout(stream_card)
        stream_layout.setContentsMargins(16, 14, 16, 14)
        stream_layout.setHorizontalSpacing(12)
        stream_layout.setVerticalSpacing(10)

        stream_layout.addWidget(QLabel("Stream Settings"), 0, 0, 1, 6)

        stream_layout.addWidget(QLabel("FPS"), 1, 0)
        self.fps_input = QLineEdit(f"{self.client.stream_fps:.1f}")
        stream_layout.addWidget(self.fps_input, 1, 1)

        stream_layout.addWidget(QLabel("Quality"), 1, 2)
        self.quality_input = QLineEdit(str(self.client.jpeg_quality))
        stream_layout.addWidget(self.quality_input, 1, 3)

        stream_layout.addWidget(QLabel("Scale"), 1, 4)
        self.scale_input = QLineEdit(f"{self.client.scale:.2f}")
        stream_layout.addWidget(self.scale_input, 1, 5)

        self.apply_stream_btn = QPushButton("Apply")
        self.apply_stream_btn.clicked.connect(self._apply_stream)
        self.apply_stream_btn.setEnabled(False)
        stream_layout.addWidget(self.apply_stream_btn, 2, 5)

        page.addWidget(stream_card)

        log_card = QFrame()
        log_card.setObjectName("Card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 14, 16, 14)
        log_layout.setSpacing(10)
        log_layout.addWidget(QLabel("Activity Log"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        log_layout.addWidget(self.log)
        page.addWidget(log_card, stretch=1)

        chat_card = QFrame()
        chat_card.setObjectName("Card")
        chat_layout = QHBoxLayout(chat_card)
        chat_layout.setContentsMargins(16, 14, 16, 14)
        chat_layout.setSpacing(10)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message...")
        self.chat_input.returnPressed.connect(self._send_chat)
        self.chat_input.setEnabled(False)
        chat_layout.addWidget(self.chat_input, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_chat)
        self.send_btn.setEnabled(False)
        chat_layout.addWidget(self.send_btn)

        page.addWidget(chat_card)

        self.signals.connection.connect(self._on_connection_changed)
        self.signals.chat.connect(self._on_chat_received)
        self.signals.status.connect(self._append_status)
        self.signals.file_received.connect(self._on_file_received)

        self.client.on_connection_changed = lambda ok, txt: self.signals.connection.emit(ok, txt)
        self.client.on_chat_received = lambda f, t, m: self.signals.chat.emit(f, t, m)
        self.client.on_status_received = lambda payload: self.signals.status.emit(str(payload))
        self.client.on_file_received = lambda name, data: self.signals.file_received.emit(name, data)

        self.setStyleSheet(
            """
            QMainWindow { background: #f4f7fb; }
            QWidget { color: #0f172a; font-size: 13px; }
            #Card {
                background: #ffffff;
                border: 1px solid #dce4ef;
                border-radius: 12px;
            }
            #StatusText { font-weight: 700; }
            #StatusDotOffline { color: #ef4444; font-size: 18px; }
            #StatusDotOnline { color: #16a34a; font-size: 18px; }
            #Endpoint { color: #475569; font-weight: 600; }
            QLineEdit {
                background: #fbfdff;
                border: 1px solid #cdd7e4;
                border-radius: 8px;
                padding: 8px 10px;
            }
            QTextEdit {
                background: #fbfdff;
                border: 1px solid #cdd7e4;
                border-radius: 10px;
                padding: 8px;
            }
            QPushButton {
                background: #111827;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                font-weight: 700;
            }
            QPushButton:disabled {
                background: #9ca3af;
            }
            """
        )

        if auto_connect:
            self._connect()

    def _endpoint_text(self) -> str:
        return f"{self.client.server_ip}:{self.client.server_port}"

    def _append_log(self, text: str) -> None:
        self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

    def _set_connect_attempt(self, active: bool) -> None:
        self._connect_attempt_in_progress = bool(active)
        if active:
            self.connect_btn.setEnabled(False)
            self.reconnect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(False)

    def _on_connection_changed(self, connected: bool, message: str) -> None:
        self._set_connect_attempt(False)
        self.status_label.setText("Connected" if connected else "Disconnected")
        self.status_dot.setObjectName("StatusDotOnline" if connected else "StatusDotOffline")
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)
        self.endpoint_label.setText(self._endpoint_text())
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.reconnect_btn.setEnabled(True)
        self.send_btn.setEnabled(connected)
        self.chat_input.setEnabled(connected)
        self.apply_stream_btn.setEnabled(connected)
        if message:
            self._append_log(message)

    def _on_chat_received(self, from_id: str, to_id: str, text: str) -> None:
        self._append_log(f"{from_id} -> {to_id}: {text}")

    def _append_status(self, text: str) -> None:
        self._append_log(f"status: {text}")

    def _on_file_received(self, file_name: str, file_data: object) -> None:
        self._append_log(f"Incoming file: {file_name}. Choose where to save it.")
        suggested_name = file_name if file_name.strip() else "received_file"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Received File",
            suggested_name,
            "All Files (*)",
        )
        if not save_path:
            self._append_log(f"Save cancelled for {suggested_name}")
            return

        try:
            with open(save_path, "wb") as fp:
                fp.write(bytes(file_data))
            self._append_log(f"Saved file to: {save_path}")
        except Exception as exc:
            self._append_log(f"Failed to save {suggested_name}: {exc}")

    def _tcp_preflight(self, ip: str, port: int, timeout_sec: float = 2.0) -> tuple[bool, str]:
        try:
            with socket.create_connection((ip, int(port)), timeout=float(timeout_sec)):
                return True, ""
        except Exception as exc:
            return False, f"Cannot reach {ip}:{port} ({exc})"

    def _connect(self) -> None:
        if self._connect_attempt_in_progress:
            return

        self.client.server_ip = self.ip_input.text().strip() or self.client.server_ip
        try:
            self.client.server_port = int(self.port_input.text().strip())
        except Exception:
            self._append_log("Invalid port")
            return

        self._set_connect_attempt(True)

        def _run() -> None:
            try:
                ok_net, message = self._tcp_preflight(self.client.server_ip, self.client.server_port)
                if not ok_net:
                    self.signals.connection.emit(False, message)
                    return

                self.client.connect(interactive=False)
            except Exception as exc:
                self.signals.connection.emit(False, f"Connect failed: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def _disconnect(self) -> None:
        self.client.disconnect()

    def _reconnect(self) -> None:
        if self._connect_attempt_in_progress:
            return

        ip = self.ip_input.text().strip() or self.client.server_ip
        try:
            port = int(self.port_input.text().strip())
        except Exception:
            self._append_log("Invalid port")
            return

        self._set_connect_attempt(True)

        def _run() -> None:
            try:
                ok_net, message = self._tcp_preflight(ip, port)
                if not ok_net:
                    self.signals.connection.emit(False, message)
                    return

                self.client.reconnect(port, ip)
            except Exception as exc:
                self.signals.connection.emit(False, f"Reconnect failed: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def _apply_stream(self) -> None:
        try:
            fps = float(self.fps_input.text().strip())
            quality = int(self.quality_input.text().strip())
            scale = float(self.scale_input.text().strip())
        except Exception:
            self._append_log("Invalid stream settings")
            return

        self.client.update_media_options(fps=fps, jpeg_quality=quality, scale=scale)
        self._append_log(f"Stream updated: fps={fps:.1f}, quality={quality}, scale={scale:.2f}")

    def _send_chat(self) -> None:
        text = self.chat_input.text().strip()
        if not text:
            return
        if self.client.send_chat_message(text, "*"):
            self.chat_input.clear()
        else:
            self._append_log("Cannot send message: disconnected")


def run_dashboard(client: RemoteManagerClient, auto_connect: bool = False) -> None:
    app = QApplication([])
    window = ClientDashboard(client=client, auto_connect=auto_connect)
    window.show()
    app.exec()
