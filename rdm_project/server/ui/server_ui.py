#!/usr/bin/env python3
"""
Remote Desktop Manager — Premium Server UI

Apple-grade dual-theme PyQt6 dashboard.
All backend logic in MainWindow is preserved; only presentation rebuilt.
"""

import argparse, csv, ipaddress, json, os, socket, subprocess, sys
import threading, time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap, QFont, QColor, QPainter, QPen, QIcon
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHeaderView, QHBoxLayout, QCheckBox, QComboBox,
    QFileDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QProgressBar, QScrollArea, QSizePolicy,
    QSplitter, QStyle, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from rdm_project.server.core.server import RemoteManagerServer
from rdm_project.server.ui.ui_copy import UI_COPY
from rdm_project.server.ui.ui_bridge import ServerBridge
from rdm_project.server.ui.theme import (
    DARK, LIGHT, Theme, get_stylesheet,
    ACCENT_BLUE, ACCENT_CYAN, ACCENT_GREEN, ACCENT_ORANGE, ACCENT_RED,
    ACCENT_PURPLE, BG_CARD, BG_DARK, BG_DARKEST, BG_DEEPEST, BG_PANEL,
    BG_RAISED, BG_HOVER, BORDER, BORDER_ACCENT, TEXT_DIM, TEXT_MUTED,
    TEXT_PRIMARY, TEXT_SECONDARY,
)

# ─── Global theme state ──────────────────────────────────────────────────────
_current_theme: Theme = DARK

def current_theme() -> Theme:
    return _current_theme

# ─── Utilities ────────────────────────────────────────────────────────────────
def _latency_color(ms: float) -> str:
    t = current_theme()
    if ms < 50: return t.success
    if ms <= 100: return t.warning
    return t.danger

def _fps_color(fps: float) -> str:
    t = current_theme()
    if fps > 3: return t.success
    if fps >= 1: return t.warning
    return t.danger

def _human_bytes(n: int) -> str:
    v = float(max(0, n))
    for u in ["B", "KB", "MB", "GB"]:
        if v < 1024: return f"{int(v)} {u}" if u == "B" else f"{v:.1f} {u}"
        v /= 1024
    return f"{v:.1f} TB"

def _format_transfer_label(label: str) -> str:
    if label.endswith(" bytes") and "/" in label:
        try:
            d, t = label[:-6].strip().split("/", 1)
            return f"{_human_bytes(int(d.strip()))} / {_human_bytes(int(t.strip()))}"
        except Exception: pass
    return label

def _format_transfer_rate(bps: float) -> str:
    v = max(0.0, float(bps))
    for u in ["B/s", "KB/s", "MB/s", "GB/s"]:
        if v < 1024: return f"{v:.1f} {u}"
        v /= 1024
    return f"{v:.1f} TB/s"

def _audit_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _icons_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "icons")

def _icon(name: str) -> QIcon:
    path = os.path.join(_icons_dir(), f"{name}.svg")
    if os.path.isfile(path):
        return QIcon(path)
    return QIcon()

def _elapsed_str(epoch: float) -> str:
    """Return human-readable elapsed time string."""
    if epoch <= 0:
        return "--"
    dt = max(0, int(time.time() - epoch))
    if dt < 60:
        return f"{dt}s"
    if dt < 3600:
        return f"{dt // 60}m {dt % 60}s"
    h, rem = divmod(dt, 3600)
    return f"{h}h {rem // 60}m"


# ═══════════════════════════════════════════════════════════════════════════════
#  StatsBadge — Compact chip in the status bar
# ═══════════════════════════════════════════════════════════════════════════════
class StatsBadge(QFrame):
    def __init__(self, label: str, initial: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("StatsBadge")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._label = QLabel(label)
        self._label.setObjectName("StatsBadgeLabel")
        lay.addWidget(self._label)
        self._value = QLabel(initial)
        self._value.setObjectName("StatsBadgeValue")
        lay.addWidget(self._value)

    def set_value(self, text: str, color: str = ""):
        self._value.setText(text)
        if color:
            self._value.setStyleSheet(f"color: {color}; background: transparent;")
        else:
            self._value.setStyleSheet("background: transparent;")


# ═══════════════════════════════════════════════════════════════════════════════
#  StatsBar — Top status strip
# ═══════════════════════════════════════════════════════════════════════════════
class StatsBar(QFrame):
    def __init__(self, host: str, port: int, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(16)

        title = QLabel("Remote Desktop Manager")
        title.setObjectName("ServerTitle")
        lay.addWidget(title)

        dot = QLabel("●")
        dot.setObjectName("StatusDot")
        dot.setFixedWidth(12)
        lay.addWidget(dot)

        addr = QLabel(f"{host}:{port}")
        addr.setObjectName("AddressLabel")
        lay.addWidget(addr)
        lay.addStretch()

        self.chip_clients = StatsBadge(UI_COPY["clients"], "0")
        self.chip_fps    = StatsBadge(UI_COPY["fps"], "—")
        self.chip_latency = StatsBadge(UI_COPY["latency"], "—")
        self.chip_rx     = StatsBadge(UI_COPY["rx"], "0 KB")
        self.chip_tx     = StatsBadge(UI_COPY["tx"], "0 KB")
        for c in [self.chip_clients, self.chip_fps, self.chip_latency, self.chip_rx, self.chip_tx]:
            lay.addWidget(c)

    def update_stats(self, stats: Dict[str, dict], selected: Optional[str] = None):
        t = current_theme()
        self.chip_clients.set_value(str(len(stats)), t.accent)
        if not selected or selected not in stats:
            return
        s = stats[selected]
        fps = float(s.get("fps", 0))
        lat = float(s.get("ping_ms", 0))
        self.chip_fps.set_value(f"{fps:.1f}", _fps_color(fps))
        self.chip_latency.set_value(f"{lat:.0f} ms", _latency_color(lat))
        self.chip_rx.set_value(_human_bytes(int(s.get("bytes_recv", 0))))
        self.chip_tx.set_value(_human_bytes(int(s.get("bytes_sent", 0))))


# ═══════════════════════════════════════════════════════════════════════════════
#  SidebarItem — Individual client card in the sidebar
# ═══════════════════════════════════════════════════════════════════════════════
class SidebarItem(QFrame):
    def __init__(self, client_id: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarItem")
        self.client_id = client_id
        self._created_at = time.time()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        # Status dot
        self._dot = QLabel("●")
        self._dot.setObjectName("SidebarItemDot")
        self._dot.setFixedWidth(10)
        lay.addWidget(self._dot)

        # Info column
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)

        self.name_label = QLabel(client_id)
        self.name_label.setObjectName("SidebarItemName")
        info.addWidget(self.name_label)

        self.meta_label = QLabel("—")
        self.meta_label.setObjectName("SidebarItemMeta")
        info.addWidget(self.meta_label)

        lay.addLayout(info, stretch=1)

        # Connected time label
        self.time_label = QLabel("0s")
        self.time_label.setObjectName("SidebarItemTime")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.time_label)

    def set_metrics(self, cpu: float, ram: float, ping: float, online: bool):
        t = current_theme()
        self._dot.setStyleSheet(f"color: {t.success if online else t.text_dim}; font-size: 8px; background: transparent;")
        self.meta_label.setText(f"CPU {cpu:.0f}%  ·  RAM {ram:.0f}%  ·  {ping:.0f}ms")
        self.time_label.setText(_elapsed_str(self._created_at))

    def set_selected(self, selected: bool):
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


# ═══════════════════════════════════════════════════════════════════════════════
#  ClientListPanel — Left sidebar
# ═══════════════════════════════════════════════════════════════════════════════
class ClientListPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header row
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(16, 16, 16, 12)
        hdr_row.setSpacing(6)
        hdr = QLabel("ENDPOINTS")
        hdr.setObjectName("SidebarHeader")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        self._count_badge = QLabel("0")
        self._count_badge.setObjectName("ClientCount")
        self._count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr_row.addWidget(self._count_badge)
        lay.addLayout(hdr_row)

        # Client list
        self.client_list = QListWidget()
        self.client_list.setObjectName("ClientList")
        self.client_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        lay.addWidget(self.client_list, stretch=1)

        # Empty placeholder
        self._empty = QLabel("Listening for connections…\nDevices will appear here.")
        self._empty.setObjectName("EmptyPlaceholder")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        lay.addWidget(self._empty)
        self._empty.setVisible(True)

        self._last_clients: List[str] = []
        self._card_by_client: Dict[str, SidebarItem] = {}
        self._client_health: Dict[str, dict] = {}
        # Track when each client was first seen
        self._connect_times: Dict[str, float] = {}

    def update_clients(self, client_ids: List[str], selected: Optional[str] = None):
        if sorted(client_ids) == sorted(self._last_clients):
            self._refresh(selected)
            return
        self._last_clients = list(client_ids)
        self._count_badge.setText(str(len(client_ids)))
        self._empty.setVisible(len(client_ids) == 0)
        self.client_list.setVisible(len(client_ids) > 0)
        self.client_list.blockSignals(True)
        self.client_list.clear()
        self._card_by_client.clear()

        # Track connection times for new clients
        for cid in client_ids:
            if cid not in self._connect_times:
                self._connect_times[cid] = time.time()
        # Clean up disconnected
        for old_cid in [k for k in self._connect_times if k not in client_ids]:
            del self._connect_times[old_cid]

        for cid in client_ids:
            card = SidebarItem(cid)
            card._created_at = self._connect_times.get(cid, time.time())
            card.set_selected(cid == selected)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cid)
            item.setSizeHint(QSize(0, 62))
            self.client_list.addItem(item)
            self.client_list.setItemWidget(item, card)
            self._card_by_client[cid] = card
            if cid == selected:
                self.client_list.setCurrentItem(item)
        self.client_list.blockSignals(False)
        self._refresh(selected)

    def update_health(self, stats: Dict[str, dict], selected: Optional[str] = None):
        self._client_health = dict(stats)
        self._refresh(selected)

    def _refresh(self, selected=None):
        for cid in self._last_clients:
            h = self._client_health.get(cid, {})
            card = self._card_by_client.get(cid)
            if not card: continue
            card.set_metrics(
                float(h.get("cpu_pct", 0)), float(h.get("ram_pct", 0)),
                float(h.get("ping_ms", 0)),
                float(h.get("last_seen", 0)) > 0 and (time.time() - float(h.get("last_seen", 0))) < 5.0)
            card.set_selected(cid == selected)


# ═══════════════════════════════════════════════════════════════════════════════
#  StreamOverlay + ScreenViewer
# ═══════════════════════════════════════════════════════════════════════════════
class StreamOverlay(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StreamOverlay")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        self.client_label = QLabel("—")
        self.client_label.setObjectName("OverlayClient")
        lay.addWidget(self.client_label)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.fps_label = QLabel("FPS: —")
        self.fps_label.setObjectName("OverlayMetric")
        row.addWidget(self.fps_label)
        self.latency_label = QLabel("RTT: —")
        self.latency_label.setObjectName("OverlayMetric")
        row.addWidget(self.latency_label)
        lay.addLayout(row)

    def update_stats(self, client_id: str, fps: float, latency_ms: float):
        self.client_label.setText(client_id)
        fc, lc = _fps_color(fps), _latency_color(latency_ms)
        self.fps_label.setText(f"FPS: <span style='color:{fc};font-weight:700'>{fps:.1f}</span>")
        self.latency_label.setText(f"RTT: <span style='color:{lc};font-weight:700'>{latency_ms:.0f}ms</span>")


class ScreenViewer(QFrame):
    file_dropped = pyqtSignal(str)
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ScreenViewer")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # HUD overlay
        orow = QHBoxLayout()
        orow.setContentsMargins(12, 12, 12, 0)
        self.hud_overlay = StreamOverlay()
        self.hud_overlay.setVisible(False)
        orow.addWidget(self.hud_overlay, alignment=Qt.AlignmentFlag.AlignLeft)
        orow.addStretch(1)
        lay.addLayout(orow)

        # Stream image
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(320, 240)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self.image_label, stretch=1)

        # Placeholder
        pc = QVBoxLayout()
        pc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pc.setSpacing(16)

        self.placeholder_icon = QLabel("◉")
        self.placeholder_icon.setObjectName("PlaceholderIcon")
        self.placeholder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_icon.setStyleSheet("font-size: 42px; color: #3a3a44; background: transparent;")
        pc.addWidget(self.placeholder_icon, alignment=Qt.AlignmentFlag.AlignCenter)

        self.placeholder = QLabel(UI_COPY["empty_title"])
        self.placeholder.setObjectName("PlaceholderLabel")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pc.addWidget(self.placeholder)

        self.placeholder_sub = QLabel(UI_COPY["empty_subtitle"])
        self.placeholder_sub.setObjectName("PlaceholderSub")
        self.placeholder_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pc.addWidget(self.placeholder_sub)

        self._placeholder_widget = QWidget()
        self._placeholder_widget.setLayout(pc)
        lay.addWidget(self._placeholder_widget, stretch=1)

        self.image_label.setVisible(False)
        self._placeholder_widget.setVisible(True)
        self.setAcceptDrops(True)

    def show_frame(self, img: QImage):
        self._placeholder_widget.setVisible(False)
        self.image_label.setVisible(True)
        self.hud_overlay.setVisible(True)
        scaled = QPixmap.fromImage(img).scaled(
            self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)

    def update_hud(self, client_id: str, fps: float, latency_ms: float):
        self.hud_overlay.update_stats(client_id, fps, latency_ms)

    def clear_frame(self):
        self.image_label.clear()
        self.image_label.setVisible(False)
        self.hud_overlay.setVisible(False)
        self._placeholder_widget.setVisible(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile() and os.path.isfile(urls[0].toLocalFile()):
                event.acceptProposedAction(); return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls: event.ignore(); return
        paths = [u.toLocalFile() for u in urls if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
        if paths:
            self.file_dropped.emit(paths[0])
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else: event.ignore()


# ═══════════════════════════════════════════════════════════════════════════════
#  NetworkGraph — Live latency sparkline
# ═══════════════════════════════════════════════════════════════════════════════
class NetworkGraph(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NetworkGraph")
        self.setMinimumHeight(110)
        self._values = []
        self._max_points = 90

    def clear(self):
        self._values.clear(); self.update()

    def add_point(self, value: float):
        self._values.append(max(0.0, float(value)))
        if len(self._values) > self._max_points:
            self._values = self._values[-self._max_points:]
        self.update()

    def paintEvent(self, event):
        t = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = self.rect().adjusted(12, 8, -12, -8)
        plot = outer.adjusted(0, 18, 0, -2)
        max_val = max(120.0, max(self._values) * 1.1) if self._values else 120.0

        # Title
        painter.setPen(QColor(t.text_dim))
        tf = QFont("SF Pro Display", 9)
        tf.setBold(True)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(tf)
        painter.drawText(outer.left(), outer.top() + 12, "LATENCY")

        # Grid lines
        painter.setPen(QPen(QColor(t.border), 1))
        for step in range(4):
            y = plot.top() + int((plot.height() * step) / 3)
            painter.drawLine(plot.left(), y, plot.right(), y)

        # Scale labels
        lf = QFont("SF Mono", 8)
        painter.setFont(lf)
        painter.setPen(QColor(t.text_dim))
        painter.drawText(plot.right() - 42, plot.top() + 10, f"{int(max_val)}")
        painter.drawText(plot.right() - 42, plot.top() + int(plot.height()/2) + 4, f"{int(max_val/2)}")
        painter.drawText(plot.right() - 20, plot.bottom() - 2, "0")

        if len(self._values) < 2:
            painter.setPen(QColor(t.text_dim))
            painter.drawText(plot.left() + 6, plot.center().y(), "Waiting for data…")
            painter.end(); return

        w, h = max(1, plot.width()), max(1, plot.height())
        dx = w / max(1, len(self._values) - 1)
        latest = self._values[-1]
        color = QColor(_latency_color(latest))
        painter.setPen(QPen(color, 2.0))

        px, py = plot.left(), plot.bottom() - int((self._values[0] / max_val) * h)
        for i in range(1, len(self._values)):
            x = plot.left() + int(i * dx)
            y = plot.bottom() - int((self._values[i] / max_val) * h)
            painter.drawLine(px, py, x, y)
            px, py = x, y

        # Current value
        vf = QFont("SF Mono", 9)
        vf.setBold(True)
        painter.setFont(vf); painter.setPen(color)
        painter.drawText(plot.right() - 92, outer.top() + 12, f"{latest:.0f} ms")
        painter.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  TransferPanel
# ═══════════════════════════════════════════════════════════════════════════════
class TransferPanel(QFrame):
    files_selected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TransferPanel")
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(10)

        hdr = QLabel("TRANSFER QUEUE")
        hdr.setObjectName("SectionHeader")
        lay.addWidget(hdr)
        self.status = QLabel(UI_COPY["file_drop"])
        self.status.setObjectName("TransferStatus")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100); self.progress.setValue(0)
        lay.addWidget(self.progress)

        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setObjectName("TransferQueueTable")
        self.queue_table.setHorizontalHeaderLabels(["File", "Status", "%", "Speed", "ETA"])
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.queue_table.setMinimumHeight(120)
        hv = self.queue_table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5): hv.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.queue_table)

        br = QHBoxLayout()
        br.setContentsMargins(0, 0, 0, 0); br.setSpacing(8)
        self.add_files_btn = QPushButton("Add Files")
        self.add_files_btn.setObjectName("BtnTransferAdd")
        self.add_files_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_files_btn.clicked.connect(self._pick_files)
        br.addWidget(self.add_files_btn)
        self.cancel_btn = QPushButton(UI_COPY["cancel_task"])
        self.cancel_btn.setObjectName("BtnTransferCancel")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        br.addWidget(self.cancel_btn)
        self.retry_btn = QPushButton(UI_COPY["retry_task"])
        self.retry_btn.setObjectName("BtnTransferRetry")
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        br.addWidget(self.retry_btn)
        lay.addLayout(br)

    def set_idle(self):
        self.status.setText(UI_COPY["file_drop"]); self.progress.setValue(0)

    def set_progress(self, percent: int, text: str):
        self.status.setText(text)
        self.progress.setValue(max(0, min(100, int(percent))))

    def selected_task_id(self) -> Optional[str]:
        row = self.queue_table.currentRow()
        if row < 0: return None
        item = self.queue_table.item(row, 0)
        if not item: return None
        tid = item.data(Qt.ItemDataRole.UserRole)
        return str(tid) if tid else None

    def update_queue(self, tasks: List[dict]):
        t = current_theme()
        self.queue_table.setRowCount(0)
        for task in tasks:
            row = self.queue_table.rowCount()
            self.queue_table.insertRow(row)
            fi = QTableWidgetItem(str(task.get("file_name", "")))
            fi.setData(Qt.ItemDataRole.UserRole, str(task.get("task_id", "")))
            self.queue_table.setItem(row, 0, fi)
            st = str(task.get("status", "queued"))
            si = QTableWidgetItem(st)
            cm = {"done": t.success, "in_progress": t.info, "failed": t.danger, "cancelled": t.danger}
            si.setForeground(QColor(cm.get(st, t.text_secondary)))
            self.queue_table.setItem(row, 1, si)
            self.queue_table.setItem(row, 2, QTableWidgetItem(str(int(task.get("percent", 0)))))
            spd = float(task.get("speed_bps", 0))
            self.queue_table.setItem(row, 3, QTableWidgetItem("—" if spd <= 0 else _format_transfer_rate(spd)))
            eta = float(task.get("eta_s", 0))
            self.queue_table.setItem(row, 4, QTableWidgetItem("—" if eta <= 0 else f"{eta:.1f}s"))

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to transfer")
        if paths:
            self.files_selected.emit([str(p) for p in paths if p])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if any(os.path.isfile(p) for p in paths):
                event.acceptProposedAction(); return
        event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls(): event.ignore(); return
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
        if paths:
            self.files_selected.emit(paths)
            event.acceptProposedAction(); return
        event.ignore()


# ═══════════════════════════════════════════════════════════════════════════════
#  NetworkScannerPanel
# ═══════════════════════════════════════════════════════════════════════════════
class NetworkScannerPanel(QFrame):
    _row_ready = pyqtSignal(str, str, str)
    _scan_finished = pyqtSignal(str)
    audit_event = pyqtSignal(str)
    COMMON_PORTS = (22, 80, 443, 3389)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NetworkScannerPanel")
        self._scan_thread = None
        self._cancel = threading.Event()
        self._scan_rows = []
        self._history = deque(maxlen=8)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(10)
        hdr = QLabel("NETWORK SCANNER")
        hdr.setObjectName("SectionHeader")
        lay.addWidget(hdr)

        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0); ctrl.setSpacing(8)
        self.subnet_input = QLineEdit()
        self.subnet_input.setObjectName("ScannerSubnetInput")
        self.subnet_input.setPlaceholderText("192.168.1.0/24")
        self.subnet_input.setText(self._default_subnet())
        ctrl.addWidget(self.subnet_input, stretch=1)
        self.scan_btn = QPushButton(UI_COPY["scan"])
        self.scan_btn.setObjectName("BtnScannerStart")
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ctrl.addWidget(self.scan_btn)
        self.stop_btn = QPushButton(UI_COPY["stop"])
        self.stop_btn.setObjectName("BtnScannerStop")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        ctrl.addWidget(self.stop_btn)
        lay.addLayout(ctrl)

        self.note = QLabel(UI_COPY["scanner_note"])
        self.note.setObjectName("ScannerNote"); self.note.setWordWrap(True)
        lay.addWidget(self.note)

        filt = QHBoxLayout()
        filt.setContentsMargins(0, 0, 0, 0); filt.setSpacing(8)
        self.active_only = QCheckBox(UI_COPY["active_only"])
        self.active_only.setObjectName("ScannerActiveOnly")
        filt.addWidget(self.active_only)
        self.port_filter = QLineEdit()
        self.port_filter.setObjectName("ScannerPortFilter")
        self.port_filter.setPlaceholderText(UI_COPY["filter_port"])
        filt.addWidget(self.port_filter, stretch=1)
        lay.addLayout(filt)

        er = QHBoxLayout()
        er.setContentsMargins(0, 0, 0, 0); er.setSpacing(8)
        self.export_csv_btn = QPushButton(UI_COPY["export_csv"])
        self.export_csv_btn.setObjectName("BtnScannerExport")
        er.addWidget(self.export_csv_btn)
        self.export_json_btn = QPushButton(UI_COPY["export_json"])
        self.export_json_btn.setObjectName("BtnScannerExport")
        er.addWidget(self.export_json_btn)
        lay.addLayout(er)

        hr = QHBoxLayout()
        hr.setContentsMargins(0, 0, 0, 0); hr.setSpacing(8)
        self.history_combo = QComboBox()
        self.history_combo.setObjectName("ScannerHistoryCombo")
        self.history_combo.addItem(UI_COPY["latest_run"])
        hr.addWidget(self.history_combo, stretch=1)
        self.compare_btn = QPushButton(UI_COPY["compare_runs"])
        self.compare_btn.setObjectName("BtnScannerExport")
        hr.addWidget(self.compare_btn)
        lay.addLayout(hr)

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("ScannerTable")
        self.table.setHorizontalHeaderLabels(["IP", "Status", "Open Ports"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(160)
        self.table.setSortingEnabled(True)
        thv = self.table.horizontalHeader()
        thv.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        thv.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        thv.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)

        self.status = QLabel(UI_COPY["ready_scan"])
        self.status.setObjectName("ScannerStatus")
        lay.addWidget(self.status)

        self.scan_btn.clicked.connect(self.start_scan)
        self.stop_btn.clicked.connect(self.stop_scan)
        self._row_ready.connect(self._add_row)
        self._scan_finished.connect(self._on_scan_finished)
        self.active_only.toggled.connect(self._apply_filters)
        self.port_filter.textChanged.connect(self._apply_filters)
        self.export_csv_btn.clicked.connect(lambda: self._export_results("csv"))
        self.export_json_btn.clicked.connect(lambda: self._export_results("json"))
        self.compare_btn.clicked.connect(self._compare_with_history)

    def _default_subnet(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
            p = ip.split(".")
            if len(p) == 4: return f"{p[0]}.{p[1]}.{p[2]}.0/24"
        except Exception: pass
        return "192.168.1.0/24"

    def _validate_lan(self, cidr):
        net = ipaddress.ip_network(cidr, strict=False)
        if net.version != 4: raise ValueError("IPv4 only")
        if not net.is_private: raise ValueError("LAN only")
        if net.prefixlen < 24: raise ValueError("/24 or smaller")
        return net

    def start_scan(self):
        if self._scan_thread and self._scan_thread.is_alive(): return
        try: net = self._validate_lan(self.subnet_input.text().strip())
        except Exception as e: QMessageBox.warning(self, UI_COPY["invalid_subnet"], str(e)); return
        self.table.setRowCount(0); self._scan_rows = []
        self.status.setText(f"Scanning {net.with_prefixlen}…")
        self.audit_event.emit(f"scan_start subnet={net.with_prefixlen}")
        self.scan_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.subnet_input.setEnabled(False); self._cancel.clear()
        self._scan_thread = threading.Thread(target=self._scan_worker, args=(net,), daemon=True)
        self._scan_thread.start()

    def stop_scan(self):
        self._cancel.set(); self.status.setText(UI_COPY["stopping_scan"])
        self.stop_btn.setEnabled(False)
        self.audit_event.emit("scan_stop")

    def _scan_worker(self, net):
        hosts = [str(ip) for ip in net.hosts()][:254]
        found, processed = 0, 0
        with ThreadPoolExecutor(max_workers=24) as pool:
            futures = {pool.submit(self._scan_host, ip): ip for ip in hosts}
            for f in as_completed(futures):
                if self._cancel.is_set(): break
                try: ip, st, ports = f.result()
                except Exception: continue
                processed += 1
                if st == "Active": found += 1
                self._row_ready.emit(ip, st, ports)
        prefix = "Stopped" if self._cancel.is_set() else "Complete"
        self._scan_finished.emit(f"{prefix}. {processed} hosts, {found} active.")

    def _scan_host(self, ip):
        open_ports, active = [], False
        for port in self.COMMON_PORTS:
            if self._cancel.is_set(): break
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.25)
                if s.connect_ex((ip, port)) == 0: open_ports.append(port); active = True
        if not active and not self._cancel.is_set(): active = self._ping(ip)
        st = "Active" if active else "No response"
        pt = ", ".join(str(p) for p in open_ports) if open_ports else ("None" if active else "—")
        return ip, st, pt

    def _ping(self, ip):
        system = platform.system().lower()
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", "1000", ip]
        elif system == "darwin":
            cmd = ["ping", "-c", "1", "-W", "1000", ip]
        else: # linux
            cmd = ["ping", "-c", "1", "-W", "1", ip]
        try:
            return subprocess.run(cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.5, check=False).returncode == 0
        except Exception: return False

    def _add_row(self, ip, status, ports):
        t = current_theme()
        self._scan_rows.append({"ip": ip, "status": status, "open_ports": ports})
        row = self.table.rowCount(); self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(ip))
        si = QTableWidgetItem(status)
        si.setForeground(QColor(t.success if status == "Active" else t.text_dim))
        self.table.setItem(row, 1, si)
        self.table.setItem(row, 2, QTableWidgetItem(ports))
        self._apply_filters()

    def _on_scan_finished(self, summary):
        self.scan_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        self.subnet_input.setEnabled(True); self.status.setText(summary)
        snap = {"timestamp": _audit_ts(), "subnet": self.subnet_input.text().strip(), "rows": list(self._scan_rows)}
        self._history.appendleft(snap); self._refresh_history_combo()
        self.audit_event.emit(f"scan_done {summary}")

    def _refresh_history_combo(self):
        self.history_combo.clear()
        self.history_combo.addItem(UI_COPY["latest_run"], None)
        for i, item in enumerate(self._history):
            self.history_combo.addItem(f"{i+1}. {item['timestamp']} ({item['subnet']})", i)

    def _apply_filters(self):
        ao, pt = self.active_only.isChecked(), self.port_filter.text().strip()
        for row in range(self.table.rowCount()):
            si, pi = self.table.item(row, 1), self.table.item(row, 2)
            st = si.text() if si else ""
            ports = pi.text() if pi else ""
            self.table.setRowHidden(row, (ao and st != "Active") or (pt and (ports in {"—", "None"} or pt not in ports)))

    def _visible_rows(self):
        return [{"ip": (self.table.item(r, 0).text() if self.table.item(r, 0) else ""),
                 "status": (self.table.item(r, 1).text() if self.table.item(r, 1) else ""),
                 "open_ports": (self.table.item(r, 2).text() if self.table.item(r, 2) else "")}
                for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]

    def _export_results(self, fmt):
        rows = self._visible_rows()
        if not rows: QMessageBox.information(self, UI_COPY["no_data"], UI_COPY["no_visible_rows"]); return
        path, _ = QFileDialog.getSaveFileName(self, "Export", f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}")
        if not path: return
        try:
            if fmt == "csv":
                with open(path, "w", newline="", encoding="utf-8") as fp:
                    w = csv.DictWriter(fp, fieldnames=["ip", "status", "open_ports"]); w.writeheader(); w.writerows(rows)
            else:
                with open(path, "w", encoding="utf-8") as fp: json.dump(rows, fp, indent=2)
            self.audit_event.emit(f"scan_export {fmt} {path}")
            self.status.setText(f"Exported {len(rows)} rows")
        except Exception as e: QMessageBox.warning(self, UI_COPY["export_failed"], str(e))

    def _compare_with_history(self):
        idx = self.history_combo.currentData()
        if idx is None: QMessageBox.information(self, UI_COPY["history"], UI_COPY["history_select"]); return
        if idx < 0 or idx >= len(self._history): return
        sel = self._history[idx]
        cur, prev = {r["ip"]: r for r in self._scan_rows}, {r["ip"]: r for r in sel["rows"]}
        added = [ip for ip in cur if ip not in prev]
        removed = [ip for ip in prev if ip not in cur]
        changed = [ip for ip in cur.keys() & prev.keys() if cur[ip].get("open_ports") != prev[ip].get("open_ports")]
        QMessageBox.information(self, UI_COPY["scan_comparison"],
            f"vs {sel['timestamp']}\nAdded: {len(added)}\nRemoved: {len(removed)}\nChanged: {len(changed)}")
        self.audit_event.emit(f"compare +{len(added)} -{len(removed)} ~{len(changed)}")

    def shutdown(self): self._cancel.set()


# ═══════════════════════════════════════════════════════════════════════════════
#  ChatPanel
# ═══════════════════════════════════════════════════════════════════════════════
class ChatPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        hdr = QLabel("MESSAGES")
        hdr.setObjectName("SectionHeader")
        lay.addWidget(hdr)

        self.history = QTextEdit()
        self.history.setObjectName("ChatHistory"); self.history.setReadOnly(True)
        lay.addWidget(self.history, stretch=1)

        ir = QHBoxLayout()
        ir.setContentsMargins(12, 10, 12, 14); ir.setSpacing(8)
        self.input_field = QLineEdit()
        self.input_field.setObjectName("ChatInput")
        self.input_field.setPlaceholderText(UI_COPY["chat_placeholder"])
        self.input_field.setMinimumHeight(38)
        ir.addWidget(self.input_field)
        self.send_btn = QPushButton(UI_COPY["send"])
        self.send_btn.setObjectName("BtnSend")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setFixedSize(68, 38)
        ir.addWidget(self.send_btn)
        lay.addLayout(ir)

    def append_message(self, from_id: str, text: str):
        t = current_theme()
        ts = datetime.now().strftime("%H:%M:%S")
        color_map = {"server": t.accent, "system": ACCENT_PURPLE}
        nc = color_map.get(from_id, t.success)
        self.history.append(
            f'<div style="margin:3px 0;padding:8px 12px;border-radius:10px;'
            f'background:{t.bg_card};border:1px solid {t.border};">'
            f'<span style="color:{nc};font-weight:600;font-size:12px;">{from_id}</span>'
            f'<span style="color:{t.text_dim};font-size:10px;padding-left:8px;">{ts}</span>'
            f'<div style="color:{t.text_primary};font-size:12px;margin-top:4px;line-height:1.45;">{text}</div>'
            f'</div>')
        self.history.verticalScrollBar().setValue(self.history.verticalScrollBar().maximum())


# ═══════════════════════════════════════════════════════════════════════════════
#  ControlPanel — Actions, volume, clipboard
# ═══════════════════════════════════════════════════════════════════════════════
class ControlPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ControlPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 12)
        lay.setSpacing(8)

        # ── Actions ──────────────────────────────
        hdr = QLabel("ACTIONS")
        hdr.setObjectName("SectionHeader")
        lay.addWidget(hdr)

        # Options row
        opts = QHBoxLayout()
        opts.setContentsMargins(0, 0, 0, 0); opts.setSpacing(12)
        self.broadcast_chk = QCheckBox("Broadcast")
        self.broadcast_chk.setObjectName("BroadcastCheckbox")
        opts.addWidget(self.broadcast_chk)
        self.warn_chk = QCheckBox("Warn first")
        self.warn_chk.setObjectName("WarnCheckbox")
        opts.addWidget(self.warn_chk)
        opts.addStretch()
        delay_lbl = QLabel("Delay")
        delay_lbl.setObjectName("SectionHeader")
        delay_lbl.setStyleSheet("padding: 0; font-size: 10px;")
        opts.addWidget(delay_lbl)
        self.delay_input = QLineEdit("0")
        self.delay_input.setObjectName("CommandDelayInput")
        self.delay_input.setFixedWidth(50)
        self.delay_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        opts.addWidget(self.delay_input)
        sec_lbl = QLabel("sec")
        sec_lbl.setStyleSheet("color: #6e6e76; font-size: 11px; background: transparent; padding: 0;")
        opts.addWidget(sec_lbl)
        lay.addLayout(opts)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0); btn_row.setSpacing(8)
        self.btn_lock = QPushButton(UI_COPY["lock"])
        self.btn_lock.setObjectName("BtnLock")
        self.btn_lock.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.btn_lock)
        self.btn_shutdown = QPushButton(UI_COPY["shutdown"])
        self.btn_shutdown.setObjectName("BtnShutdown")
        self.btn_shutdown.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.btn_shutdown)
        self.btn_restart = QPushButton(UI_COPY["restart"])
        self.btn_restart.setObjectName("BtnRestart")
        self.btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.btn_restart)
        lay.addLayout(btn_row)

        # ── Volume ──────────────────────────────
        vol_hdr = QLabel("VOLUME")
        vol_hdr.setObjectName("SectionHeader")
        lay.addWidget(vol_hdr)
        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(6)
        self.btn_mute = QPushButton("Mute")
        self.btn_mute.setObjectName("BtnVolMute")
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        vol_row.addWidget(self.btn_mute)
        self.btn_vol_down = QPushButton("Vol \u2212")
        self.btn_vol_down.setObjectName("BtnVolDown")
        self.btn_vol_down.setCursor(Qt.CursorShape.PointingHandCursor)
        vol_row.addWidget(self.btn_vol_down)
        self.btn_vol_up = QPushButton("Vol +")
        self.btn_vol_up.setObjectName("BtnVolUp")
        self.btn_vol_up.setCursor(Qt.CursorShape.PointingHandCursor)
        vol_row.addWidget(self.btn_vol_up)
        self.btn_unmute = QPushButton("Unmute")
        self.btn_unmute.setObjectName("BtnVolUnmute")
        self.btn_unmute.setCursor(Qt.CursorShape.PointingHandCursor)
        vol_row.addWidget(self.btn_unmute)
        lay.addLayout(vol_row)

        # ── Clipboard ──────────────────────────
        clip_hdr = QLabel("CLIPBOARD")
        clip_hdr.setObjectName("SectionHeader")
        lay.addWidget(clip_hdr)
        self.clipboard_view = QTextEdit()
        self.clipboard_view.setObjectName("ClipboardView")
        self.clipboard_view.setPlaceholderText("Click 'Get' to fetch remote clipboard…")
        self.clipboard_view.setMaximumHeight(72)
        lay.addWidget(self.clipboard_view)
        clip_row = QHBoxLayout()
        clip_row.setContentsMargins(0, 0, 0, 0)
        clip_row.setSpacing(6)
        self.btn_get_clip = QPushButton("Get")
        self.btn_get_clip.setObjectName("BtnClipGet")
        self.btn_get_clip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_get_clip.setToolTip("Fetch selected client\u2019s clipboard text")
        clip_row.addWidget(self.btn_get_clip)
        self.btn_push_clip = QPushButton("Push")
        self.btn_push_clip.setObjectName("BtnClipPush")
        self.btn_push_clip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_push_clip.setToolTip("Push text to client\u2019s clipboard")
        clip_row.addWidget(self.btn_push_clip)
        clip_row.addStretch(1)
        lay.addLayout(clip_row)

    def set_enabled(self, enabled: bool):
        for btn in [self.btn_lock, self.btn_shutdown, self.btn_restart,
                    self.btn_mute, self.btn_vol_down, self.btn_vol_up, self.btn_unmute,
                    self.btn_get_clip, self.btn_push_clip]:
            btn.setEnabled(enabled)

    def set_clipboard_text(self, text: str):
        self.clipboard_view.setPlainText(text)

    def get_delay_seconds(self) -> int:
        try:
            return max(0, int(self.delay_input.text().strip()))
        except (ValueError, TypeError):
            return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  AuditLogPanel
# ═══════════════════════════════════════════════════════════════════════════════
class AuditLogPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AuditLogPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(8)

        hdr = QLabel("EVENT LOG")
        hdr.setObjectName("SectionHeader")
        lay.addWidget(hdr)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("AuditLogView")
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view, stretch=1)

    def append_event(self, category: str, message: str):
        t = current_theme()
        ts = _audit_ts()
        cat_colors = {
            "SYSTEM": t.info, "COMMAND": t.warning, "BROADCAST": t.danger,
            "TRANSFER": t.success, "SCAN": t.accent, "ACK": t.success,
            "CLIPBOARD": t.info, "VOLUME": t.warning, "SCREENSHOT": t.accent,
        }
        cc = cat_colors.get(category, t.text_secondary)
        self.log_view.append(
            f'<span style="color:{t.text_dim};font-size:10px;">{ts}</span> '
            f'<span style="color:{cc};font-weight:600;font-size:11px;">[{category}]</span> '
            f'<span style="color:{t.text_primary};font-size:11px;">{message}</span>')
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())


# ═══════════════════════════════════════════════════════════════════════════════
#  SystemInfoPanel
# ═══════════════════════════════════════════════════════════════════════════════
class SystemInfoPanel(QFrame):
    refresh_requested = pyqtSignal()
    screenshot_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SystemInfoPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(10)

        hdr = QLabel("SYSTEM INFO")
        hdr.setObjectName("SectionHeader")
        lay.addWidget(hdr)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("BtnSysRefresh")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        btn_row.addWidget(self.refresh_btn)
        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.setObjectName("BtnSysScreenshot")
        self.screenshot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.screenshot_btn.clicked.connect(self.screenshot_requested.emit)
        btn_row.addWidget(self.screenshot_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.info_view = QTextEdit()
        self.info_view.setObjectName("SysInfoView")
        self.info_view.setReadOnly(True)
        lay.addWidget(self.info_view, stretch=1)
        self._set_placeholder()

    def set_enabled(self, enabled: bool):
        self.refresh_btn.setEnabled(enabled)
        self.screenshot_btn.setEnabled(enabled)

    def _set_placeholder(self):
        t = current_theme()
        self.info_view.setHtml(
            f'<div style="color:{t.text_dim};font-size:12px;padding:16px;text-align:center;">'
            f'Select a client and click Refresh</div>')

    def update_info(self, info: dict):
        t = current_theme()
        skip = {"_client_id"}
        rows = []
        for k, v in info.items():
            if k in skip: continue
            label = k.replace("_", " ").title()
            rows.append(
                f'<tr>'
                f'<td style="color:{t.text_dim};font-weight:600;font-size:11px;padding:5px 10px 5px 0;'
                f'vertical-align:top;white-space:nowrap;">{label}</td>'
                f'<td style="color:{t.text_primary};font-size:11px;padding:5px 0;">{v}</td>'
                f'</tr>')
        self.info_view.setHtml(
            f'<table style="border-collapse:collapse;width:100%;">{"".join(rows)}</table>')


# ═══════════════════════════════════════════════════════════════════════════════
#  TabPanel — Right-side tabbed container
# ═══════════════════════════════════════════════════════════════════════════════
class TabPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RightPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("RightTabs")
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs, stretch=1)

        self.chat = ChatPanel()
        self.tabs.addTab(self._wrap(self.chat), "Chat")

        self.graph = NetworkGraph()
        self.controls = ControlPanel()
        ct = QWidget()
        cl = QVBoxLayout(ct)
        cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(6)
        cl.addWidget(self.graph)
        cl.addWidget(self.controls)
        cl.addStretch(1)
        self.tabs.addTab(self._wrap(ct), "Controls")

        self.transfer = TransferPanel()
        self.tabs.addTab(self._wrap(self.transfer), "Transfer")

        self.scanner = NetworkScannerPanel()
        self.tabs.addTab(self._wrap(self.scanner), "Scanner")

        self.audit = AuditLogPanel()
        self.tabs.addTab(self._wrap(self.audit), "Logs")

        self.sysinfo = SystemInfoPanel()
        self.tabs.addTab(self._wrap(self.sysinfo), "System")

    def _wrap(self, widget):
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll = QScrollArea()
        scroll.setObjectName("RightTabScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll


# ═══════════════════════════════════════════════════════════════════════════════
#  DashboardLayout — 3-zone splitter + theme toggle
# ═══════════════════════════════════════════════════════════════════════════════
class DashboardLayout(QWidget):
    theme_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)

        self.sidebar = ClientListPanel()
        self.sidebar.setFixedWidth(240)

        # Theme toggle at bottom of sidebar
        self._theme_btn = QPushButton()
        self._theme_btn.setObjectName("ThemeToggle")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.setText("\u2600  Light Mode")
        self._theme_btn.clicked.connect(self.theme_toggled.emit)
        self.sidebar.layout().addWidget(self._theme_btn)

        self.splitter.addWidget(self.sidebar)

        self.viewer = ScreenViewer()
        self.splitter.addWidget(self.viewer)

        self.right_panel = TabPanel()
        self.right_panel.setMinimumWidth(300)
        self.splitter.addWidget(self.right_panel)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, True)
        self.splitter.setSizes([240, 860, 320])

        self._collapsed = False
        self._collapse_btn = QPushButton("\u25C2")
        self._collapse_btn.setObjectName("CollapseToggle")
        self._collapse_btn.setToolTip("Toggle panel")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.clicked.connect(self._toggle_right)
        self._collapse_btn.setParent(self)
        self._collapse_btn.raise_()

        lay.addWidget(self.splitter, stretch=1)

    def update_theme_btn(self, theme: Theme):
        if theme.name == "dark":
            self._theme_btn.setText("\u2600  Light Mode")
        else:
            self._theme_btn.setText("\u263D  Dark Mode")

    def _toggle_right(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._saved = self.splitter.sizes()
            s = self.splitter.sizes(); s[2] = 0; self.splitter.setSizes(s)
            self._collapse_btn.setText("\u25B8")
        else:
            self.splitter.setSizes(getattr(self, '_saved', [240, 860, 320]))
            self._collapse_btn.setText("\u25C2")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._collapse_btn.move(self.width() - self._collapse_btn.width() - 8, 8)

DashboardBody = DashboardLayout


# ═══════════════════════════════════════════════════════════════════════════════
#  MainWindow — ALL BACKEND LOGIC PRESERVED EXACTLY
# ═══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self, bridge: ServerBridge, host: str, port: int):
        super().__init__()
        global _current_theme
        self.bridge = bridge
        self._selected_client: Optional[str] = None
        self._current_fps = 0.0
        self._current_latency = 0.0
        self._latest_stats: Dict[str, dict] = {}

        self.setWindowTitle("Remote Desktop Manager")
        self.setMinimumSize(1100, 700)
        self.resize(1440, 880)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        self.top_bar = StatsBar(host, port)
        root.addWidget(self.top_bar)

        self.dashboard = DashboardLayout()
        self.sidebar = self.dashboard.sidebar
        self.viewer = self.dashboard.viewer
        self.right_panel = self.dashboard.right_panel
        root.addWidget(self.dashboard, stretch=1)

        # Theme toggle
        self.dashboard.theme_toggled.connect(self._toggle_theme)

        # Wire signals — existing
        self.bridge.clients_changed.connect(self._on_clients_changed)
        self.bridge.frame_received.connect(self._on_frame)
        self.bridge.stats_updated.connect(self._on_stats)
        self.bridge.chat_received.connect(self._on_chat)
        self.bridge.client_disconnected.connect(self._on_client_disconnected)
        self.bridge.file_transfer_progress.connect(self._on_transfer_progress)
        self.bridge.file_transfer_done.connect(self._on_transfer_done)
        self.bridge.session_summary.connect(self._on_session_summary)
        self.bridge.transfer_queue_updated.connect(self._on_transfer_queue_updated)
        # Wire signals — phase 2
        self.bridge.command_result.connect(self._on_command_result)
        self.bridge.sysinfo_received.connect(self._on_sysinfo_received)
        self.bridge.clipboard_received.connect(self._on_clipboard_received)
        self.bridge.screenshot_received.connect(self._on_screenshot_received)

        self.sidebar.client_list.currentItemChanged.connect(self._on_client_selected)
        self.right_panel.chat.send_btn.clicked.connect(self._on_send_chat)
        self.right_panel.chat.input_field.returnPressed.connect(self._on_send_chat)
        self.right_panel.controls.btn_lock.clicked.connect(lambda: self._send_command("LOCK"))
        self.right_panel.controls.btn_shutdown.clicked.connect(lambda: self._send_command("SHUTDOWN"))
        self.right_panel.controls.btn_restart.clicked.connect(lambda: self._send_command("RESTART"))
        # Volume
        self.right_panel.controls.btn_mute.clicked.connect(lambda: self._send_volume("mute"))
        self.right_panel.controls.btn_vol_down.clicked.connect(lambda: self._send_volume("down"))
        self.right_panel.controls.btn_vol_up.clicked.connect(lambda: self._send_volume("up"))
        self.right_panel.controls.btn_unmute.clicked.connect(lambda: self._send_volume("unmute"))
        # Clipboard
        self.right_panel.controls.btn_get_clip.clicked.connect(self._get_clipboard)
        self.right_panel.controls.btn_push_clip.clicked.connect(self._push_clipboard)
        # System info
        self.right_panel.sysinfo.refresh_requested.connect(self._refresh_sysinfo)
        self.right_panel.sysinfo.screenshot_requested.connect(self._request_screenshot)
        # File transfer / network
        self.viewer.files_dropped.connect(self._on_files_dropped)
        self.right_panel.transfer.files_selected.connect(self._on_files_dropped)
        self.right_panel.transfer.cancel_btn.clicked.connect(self._on_cancel_transfer)
        self.right_panel.transfer.retry_btn.clicked.connect(self._on_retry_transfer)
        self.right_panel.scanner.audit_event.connect(lambda msg: self._log_audit("SCAN", msg))

        self.right_panel.controls.set_enabled(False)
        self.right_panel.sysinfo.set_enabled(False)
        self._apply_theme(_current_theme)
        self._log_audit("SYSTEM", "UI initialized")

    def _toggle_theme(self):
        global _current_theme
        _current_theme = LIGHT if _current_theme.name == "dark" else DARK
        self._apply_theme(_current_theme)

    def _apply_theme(self, theme: Theme):
        QApplication.instance().setStyleSheet(get_stylesheet(theme))
        self.centralWidget().setStyleSheet(f"background-color: {theme.bg_root};")
        self.dashboard.update_theme_btn(theme)

    def _on_clients_changed(self, client_ids):
        self.sidebar.update_clients(client_ids, self._selected_client)
        if self._selected_client and self._selected_client not in client_ids:
            self._selected_client = None
            self.viewer.clear_frame(); self.right_panel.graph.clear()
            self.right_panel.controls.set_enabled(False)
            self.right_panel.sysinfo.set_enabled(False)
            self.right_panel.sysinfo._set_placeholder()

    def _on_client_selected(self, current, _prev):
        if current is None:
            self._selected_client = None
            self.viewer.clear_frame(); self.right_panel.graph.clear()
            self.right_panel.controls.set_enabled(False)
            self.right_panel.sysinfo.set_enabled(False)
            self.right_panel.sysinfo._set_placeholder()
            return
        cid = current.data(Qt.ItemDataRole.UserRole)
        self._selected_client = cid
        self.bridge.select_client(cid)
        self.right_panel.controls.set_enabled(True)
        self.right_panel.sysinfo.set_enabled(True)

    def _on_frame(self, client_id, img):
        if client_id == self._selected_client:
            self.viewer.show_frame(img)
            self.viewer.update_hud(client_id, self._current_fps, self._current_latency)

    def _on_stats(self, stats):
        self._latest_stats = dict(stats)
        self.top_bar.update_stats(stats, self._selected_client)
        self.sidebar.update_health(stats, self._selected_client)
        if self._selected_client and self._selected_client in stats:
            self._current_fps = stats[self._selected_client].get("fps", 0.0)
            self._current_latency = stats[self._selected_client].get("ping_ms", 0.0)
            self.viewer.update_hud(self._selected_client, self._current_fps, self._current_latency)
            self.right_panel.graph.add_point(self._current_latency)

    def _on_chat(self, from_id, _to, text):
        self.right_panel.chat.append_message(from_id, text)

    def _on_client_disconnected(self, client_id):
        self.right_panel.chat.append_message("system", f"{client_id} disconnected")

    def _on_transfer_progress(self, client_id, percent, label):
        if self._selected_client == client_id:
            self.right_panel.transfer.set_progress(percent, f"{percent:>3}% \u2192 {client_id}  |  {_format_transfer_label(label)}")

    def _on_transfer_done(self, ok, message):
        tag = "OK" if ok else "FAIL"
        self.right_panel.chat.append_message("system", f"[{tag}] {message}")
        self._log_audit("TRANSFER", message)
        self.right_panel.transfer.set_progress(100 if ok else 0, "Complete" if ok else "Failed")

    def _on_transfer_queue_updated(self, tasks):
        self.right_panel.transfer.update_queue(tasks)

    def _on_session_summary(self, summary):
        cid = summary.get("client_id", "?")
        dur = float(summary.get("duration_s", 0))
        tx = float(summary.get("bytes_sent", 0)) / 1048576
        rx = float(summary.get("bytes_recv", 0)) / 1048576
        self.right_panel.chat.append_message("system",
            f"Session: {cid} \u2014 {dur:.1f}s, TX {tx:.2f}MB, RX {rx:.2f}MB")
        self._log_audit("SYSTEM", f"session {cid} {dur:.1f}s")

    def _on_send_chat(self):
        text = self.right_panel.chat.input_field.text().strip()
        if not text: return
        self.bridge.send_chat(text, self._selected_client or "*")
        self.right_panel.chat.input_field.clear()

    def _on_files_dropped(self, file_paths):
        if not self._selected_client:
            QMessageBox.information(self, UI_COPY["no_client_selected"], UI_COPY["no_client_selected_msg"]); return
        clean = [str(p) for p in file_paths if isinstance(p, str) and p]
        if not clean: return
        added = self.bridge.enqueue_files(self._selected_client, clean)
        if added <= 0: self.right_panel.transfer.set_progress(0, "No files added"); return
        first = os.path.basename(clean[0])
        self.right_panel.transfer.set_progress(0, f"Queued {first}" + ("" if added == 1 else f" (+{added-1})"))
        self._log_audit("TRANSFER", f"queued {added} file(s) \u2192 {self._selected_client}")

    def _on_cancel_transfer(self):
        tid = self.right_panel.transfer.selected_task_id()
        if tid and self.bridge.cancel_transfer(tid): self._log_audit("TRANSFER", f"cancel {tid[:8]}")

    def _on_retry_transfer(self):
        tid = self.right_panel.transfer.selected_task_id()
        if tid and self.bridge.retry_transfer(tid): self._log_audit("TRANSFER", f"retry {tid[:8]}")

    def _log_audit(self, category, message):
        self.right_panel.audit.append_event(category, message)

    # ── Remote command actions ──────────────────────────────────────────────

    def _send_command(self, action: str) -> None:
        """Send LOCK / SHUTDOWN / RESTART with optional delay, warning, broadcast."""
        t = current_theme()
        controls = self.right_panel.controls
        delay_s = controls.get_delay_seconds()
        send_warn = controls.warn_chk.isChecked()
        broadcast = controls.broadcast_chk.isChecked()
        labels = {"LOCK": UI_COPY["lock"], "SHUTDOWN": UI_COPY["shutdown"], "RESTART": UI_COPY["restart"]}
        label = labels.get(action, action)
        delay_suffix = f" in {delay_s}s" if delay_s > 0 else ""

        if broadcast:
            with self.bridge.server.clients_lock:
                client_count = len(self.bridge.server.clients)
            if action in {"SHUTDOWN", "RESTART"}:
                reply = QMessageBox.question(
                    self, f"Broadcast {label}",
                    f"<p style='font-size:13px;'>Send <b>{label}</b> to all "
                    f"{client_count} connected client(s){delay_suffix}?</p>"
                    f"<p style='color:{t.text_muted};font-size:12px;'>This cannot be undone.</p>",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            count = self.bridge.broadcast_command(action, delay_s=delay_s, send_warning=send_warn)
            self.right_panel.chat.append_message(
                "system", f"[BROADCAST] {label} sent to {count} client(s){delay_suffix}"
            )
            self._log_audit("BROADCAST", f"{action} -> {count} clients{delay_suffix}")
            return

        if not self._selected_client:
            return

        if action in {"SHUTDOWN", "RESTART"}:
            reply = QMessageBox.question(
                self, f"Confirm {label}",
                f"<p style='font-size:13px;'>{label} <b>{self._selected_client}</b>{delay_suffix}?</p>"
                f"<p style='color:{t.text_muted};font-size:12px;'>This action cannot be undone.</p>",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        ok = self.bridge.send_command_with_options(
            self._selected_client, action, delay_s=delay_s, send_warning=send_warn
        )
        tag = "OK" if ok else "FAIL"
        self.right_panel.chat.append_message(
            "system",
            f"[{tag}] {label} -> {self._selected_client}{delay_suffix}",
        )
        self._log_audit(
            "COMMAND",
            f"{action} -> {self._selected_client}{delay_suffix}" if ok
            else f"FAILED {action} -> {self._selected_client}",
        )

    def _on_command_result(self, client_id: str, action: str, ok: bool, message: str) -> None:
        tag = "OK" if ok else "FAIL"
        self.right_panel.chat.append_message(
            "system", f"[{tag}] [{client_id}] {action}: {message}",
        )
        self._log_audit("ACK", f"{action} {tag} <- {client_id}: {message}")

    def _on_sysinfo_received(self, client_id: str, info: dict) -> None:
        if client_id == self._selected_client:
            self.right_panel.sysinfo.update_info(info)

    def _on_clipboard_received(self, client_id: str, text: str) -> None:
        if client_id == self._selected_client:
            self.right_panel.controls.set_clipboard_text(text)
            self.right_panel.chat.append_message(
                "system", f"Clipboard from {client_id} ({len(text)} chars)"
            )

    def _send_volume(self, cmd: str) -> None:
        if not self._selected_client:
            return
        ok = self.bridge.set_volume(self._selected_client, cmd)
        label = {
            "mute": "Muted", "unmute": "Unmuted",
            "up": "Volume Up", "down": "Volume Down",
        }.get(cmd, cmd)
        if ok:
            self.right_panel.chat.append_message("system", f"{label} -> {self._selected_client}")
            self._log_audit("VOLUME", f"{cmd} -> {self._selected_client}")

    def _get_clipboard(self) -> None:
        if not self._selected_client:
            return
        ok = self.bridge.request_clipboard(self._selected_client)
        if ok:
            self.right_panel.chat.append_message(
                "system", f"Clipboard requested from {self._selected_client}"
            )

    def _push_clipboard(self) -> None:
        if not self._selected_client:
            return
        text = self.right_panel.controls.clipboard_view.toPlainText()
        if not text:
            return
        ok = self.bridge.push_clipboard(self._selected_client, text)
        if ok:
            self.right_panel.chat.append_message(
                "system", f"Clipboard pushed to {self._selected_client} ({len(text)} chars)"
            )
            self._log_audit("CLIPBOARD", f"push {len(text)} chars -> {self._selected_client}")

    def _refresh_sysinfo(self) -> None:
        if not self._selected_client:
            return
        if self.bridge.request_sysinfo(self._selected_client):
            self.right_panel.chat.append_message(
                "system", f"System info requested from {self._selected_client}"
            )

    def _request_screenshot(self) -> None:
        if not self._selected_client:
            return
        if self.bridge.request_screenshot(self._selected_client):
            self.right_panel.chat.append_message(
                "system", f"Screenshot requested from {self._selected_client}"
            )
            self._log_audit("SCREENSHOT", f"requested from {self._selected_client}")

    def _on_screenshot_received(self, client_id: str, jpeg_bytes: bytes) -> None:
        """Save screenshot JPEG to disk."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"screenshot_{client_id}_{ts}.jpg"
        desktop = os.path.expanduser("~/Desktop")
        default_path = os.path.join(desktop, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", default_path, "JPEG Images (*.jpg);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(jpeg_bytes)
            size_kb = len(jpeg_bytes) / 1024
            self.right_panel.chat.append_message(
                "system", f"Screenshot saved: {os.path.basename(path)} ({size_kb:.0f} KB)"
            )
            self._log_audit("SCREENSHOT", f"saved {os.path.basename(path)} ({size_kb:.0f} KB)")
        except Exception as exc:
            self.right_panel.chat.append_message(
                "system", f"Failed to save screenshot: {exc}"
            )

    def closeEvent(self, event):
        self.right_panel.scanner.stop_scan()
        super().closeEvent(event)


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Remote Desktop Manager \u2014 GUI Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5500)
    parser.add_argument("--password", default="lan-demo-123")
    args = parser.parse_args()

    server = RemoteManagerServer(args.host, args.port, args.password)
    server._screen_display_loop = lambda: None
    server.console_enabled = False

    threading.Thread(target=server.start, daemon=True).start()

    app = QApplication(sys.argv)
    app.setStyleSheet(get_stylesheet(DARK))
    app.setFont(QFont("SF Pro Display", 13))

    bridge = ServerBridge(server)
    bridge.start()
    window = MainWindow(bridge, args.host, args.port)
    window.show()

    exit_code = app.exec()
    bridge.stop()
    server.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
