"""
Cinematic dual-theme system — Remote Desktop Manager

Two complete themes (DARK / LIGHT) with Apple-grade palette.
Premium typography, refined spacing, glassmorphism, and micro-animations.
"""

from dataclasses import dataclass


@dataclass
class Theme:
    name: str
    # Backgrounds
    bg_root: str
    bg_sidebar: str
    bg_card: str
    bg_surface: str
    bg_hover: str
    bg_input: str
    bg_overlay: str
    # Borders
    border: str
    border_focus: str
    # Text
    text_primary: str
    text_secondary: str
    text_muted: str
    text_dim: str
    # Accents
    accent: str
    accent_hover: str
    accent_gradient_start: str
    accent_gradient_end: str
    success: str
    success_bg: str
    warning: str
    warning_bg: str
    danger: str
    danger_bg: str
    info: str
    info_bg: str
    # Scrollbar
    scrollbar_bg: str
    scrollbar_handle: str
    scrollbar_hover: str
    # Misc
    shadow: str
    tab_active_bg: str


DARK = Theme(
    name="dark",
    bg_root="#0a0a0c",
    bg_sidebar="#101014",
    bg_card="#18181c",
    bg_surface="#1e1e23",
    bg_hover="#28282f",
    bg_input="#0e0e12",
    bg_overlay="rgba(10, 10, 12, 0.88)",
    border="#222228",
    border_focus="#5b5ff7",
    text_primary="#f5f5f7",
    text_secondary="#a1a1a8",
    text_muted="#6e6e76",
    text_dim="#48484f",
    accent="#5b5ff7",
    accent_hover="#7b7fff",
    accent_gradient_start="#5b5ff7",
    accent_gradient_end="#a855f7",
    success="#34d399",
    success_bg="rgba(52,211,153,0.10)",
    warning="#fbbf24",
    warning_bg="rgba(251,191,36,0.10)",
    danger="#f87171",
    danger_bg="rgba(248,113,113,0.10)",
    info="#22d3ee",
    info_bg="rgba(34,211,238,0.10)",
    scrollbar_bg="transparent",
    scrollbar_handle="#28282f",
    scrollbar_hover="#3a3a44",
    shadow="rgba(0, 0, 0, 0.55)",
    tab_active_bg="#1e1e23",
)

LIGHT = Theme(
    name="light",
    bg_root="#f5f5f7",
    bg_sidebar="#ebebf0",
    bg_card="#ffffff",
    bg_surface="#f9f9fb",
    bg_hover="#e5e5ea",
    bg_input="#ffffff",
    bg_overlay="rgba(245, 245, 247, 0.92)",
    border="#d2d2d7",
    border_focus="#5b5ff7",
    text_primary="#1d1d1f",
    text_secondary="#6e6e73",
    text_muted="#86868b",
    text_dim="#aeaeb2",
    accent="#5b5ff7",
    accent_hover="#4b4fe0",
    accent_gradient_start="#5b5ff7",
    accent_gradient_end="#a855f7",
    success="#34d399",
    success_bg="rgba(52,211,153,0.10)",
    warning="#f59e0b",
    warning_bg="rgba(245,158,11,0.10)",
    danger="#ef4444",
    danger_bg="rgba(239,68,68,0.10)",
    info="#06b6d4",
    info_bg="rgba(6,182,212,0.10)",
    scrollbar_bg="transparent",
    scrollbar_handle="#c7c7cc",
    scrollbar_hover="#aeaeb2",
    shadow="rgba(0, 0, 0, 0.06)",
    tab_active_bg="#ffffff",
)

# Backward compat exports (dark as default)
BG_DEEPEST = DARK.bg_root
BG_DARKEST = DARK.bg_root
BG_DARK = DARK.bg_sidebar
BG_PANEL = DARK.bg_sidebar
BG_CARD = DARK.bg_card
BG_RAISED = DARK.bg_surface
BG_HOVER = DARK.bg_hover
BORDER = DARK.border
BORDER_ACCENT = DARK.border_focus
BORDER_GLOW = DARK.border
TEXT_PRIMARY = DARK.text_primary
TEXT_SECONDARY = DARK.text_secondary
TEXT_MUTED = DARK.text_muted
TEXT_DIM = DARK.text_dim
ACCENT_BLUE = DARK.accent
ACCENT_CYAN = DARK.info
ACCENT_GREEN = DARK.success
ACCENT_RED = DARK.danger
ACCENT_ORANGE = DARK.warning
ACCENT_PURPLE = "#a855f7"
GLOW_BLUE = DARK.accent


def get_stylesheet(theme: Theme = DARK) -> str:
    t = theme
    # Shared transition-like dynamic property (Qt doesn't support CSS transitions,
    # but we define consistent hover states for a polished feel)
    return f"""
    * {{
        font-family: 'SF Pro Display', 'SF Pro Text', '-apple-system', 'Helvetica Neue',
                     'Inter', 'Segoe UI', 'Roboto', sans-serif;
        outline: none;
    }}
    QMainWindow {{
        background-color: {t.bg_root};
        color: {t.text_primary};
    }}
    QWidget {{
        background-color: transparent;
        color: {t.text_primary};
        font-size: 13px;
    }}

    /* ═══ TOP BAR ═══ */
    #TopBar {{
        background-color: {t.bg_sidebar};
        border-bottom: 1px solid {t.border};
        min-height: 48px;
        max-height: 48px;
        padding: 0 24px;
    }}
    #TopBar QLabel {{
        color: {t.text_secondary};
        font-size: 12px;
        background: transparent;
    }}
    #ServerTitle {{
        color: {t.text_primary};
        font-weight: 600;
        font-size: 14px;
        letter-spacing: -0.4px;
    }}
    #StatusDot {{
        color: {t.success};
        font-size: 8px;
    }}
    #AddressLabel {{
        color: {t.text_dim};
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.2px;
    }}

    /* ═══ STAT BADGES ═══ */
    #StatsBadge {{
        background-color: {t.bg_card};
        border: 1px solid {t.border};
        border-radius: 18px;
        padding: 5px 16px;
        margin: 0 2px;
    }}
    #StatsBadgeLabel {{
        color: {t.text_dim};
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        background: transparent;
    }}
    #StatsBadgeValue {{
        font-weight: 700;
        font-size: 12px;
        padding: 0 0 0 6px;
        background: transparent;
    }}

    /* ═══ SIDEBAR ═══ */
    #Sidebar {{
        background-color: {t.bg_sidebar};
        border-right: 1px solid {t.border};
        min-width: 230px;
        max-width: 240px;
    }}
    #SidebarHeader {{
        color: {t.text_muted};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        padding: 18px 16px 10px 16px;
        background: transparent;
    }}
    #ClientCount {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_gradient_start},stop:1 {t.accent_gradient_end});
        color: white;
        font-size: 10px;
        font-weight: 700;
        border-radius: 9px;
        padding: 3px 10px;
        min-width: 14px;
    }}
    #ClientList {{
        background-color: transparent;
        border: none;
        outline: none;
        padding: 4px 8px;
    }}
    #ClientList::item {{
        border: none;
        border-radius: 10px;
        margin: 2px 0;
        padding: 0;
    }}
    #ClientList::item:selected {{
        background: {t.bg_hover};
    }}
    #ClientList::item:hover:!selected {{
        background: {t.bg_surface};
    }}

    #SidebarItem {{
        background: transparent;
        border: none;
        border-radius: 10px;
        padding: 8px 12px;
    }}
    #SidebarItem[selected="true"] {{
        background: {t.bg_hover};
    }}
    #SidebarItemIcon {{
        color: {t.accent};
        font-size: 7px;
        background: transparent;
    }}
    #SidebarItemName {{
        color: {t.text_primary};
        font-weight: 600;
        font-size: 13px;
        letter-spacing: -0.2px;
        background: transparent;
    }}
    #SidebarItemDot {{
        font-size: 8px;
        background: transparent;
    }}
    #SidebarItemMeta {{
        color: {t.text_dim};
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.1px;
        background: transparent;
    }}
    #SidebarItemTime {{
        color: {t.text_muted};
        font-size: 10px;
        font-weight: 600;
        font-family: 'SF Mono', 'JetBrains Mono', 'Menlo', monospace;
        background: transparent;
        letter-spacing: 0.2px;
    }}
    #EmptyPlaceholder {{
        color: {t.text_dim};
        font-size: 12px;
        padding: 20px 16px;
        background: transparent;
        line-height: 1.5;
    }}

    /* ═══ THEME TOGGLE ═══ */
    #ThemeToggle {{
        background: {t.bg_card};
        border: 1px solid {t.border};
        border-radius: 10px;
        padding: 8px 12px;
        margin: 12px 12px;
        font-size: 12px;
        font-weight: 500;
        color: {t.text_secondary};
    }}
    #ThemeToggle:hover {{
        background: {t.bg_hover};
        border-color: {t.border_focus};
        color: {t.text_primary};
    }}

    /* ═══ SCREEN VIEWER ═══ */
    #ScreenViewer {{
        background-color: {t.bg_root};
        border-radius: 14px;
        border: 1px solid {t.border};
        margin: 6px;
    }}
    #PlaceholderLabel {{
        color: {t.text_secondary};
        font-size: 18px;
        font-weight: 600;
        letter-spacing: -0.4px;
        background: transparent;
    }}
    #PlaceholderSub {{
        color: {t.text_dim};
        font-size: 12px;
        font-weight: 400;
        padding-top: 4px;
        background: transparent;
        line-height: 1.4;
    }}
    #PlaceholderIcon {{
        background: transparent;
    }}

    #StreamOverlay {{
        background-color: {t.bg_overlay};
        border: 1px solid {t.border};
        border-radius: 10px;
        padding: 8px 14px;
        font-size: 11px;
        font-family: 'SF Mono', 'JetBrains Mono', 'Menlo', 'Fira Code', monospace;
    }}
    #OverlayClient {{
        color: {t.text_primary};
        font-weight: 600;
        font-size: 11px;
        letter-spacing: -0.1px;
    }}
    #OverlayMetric {{
        color: {t.text_secondary};
        font-size: 10px;
        font-weight: 600;
    }}

    /* ═══ RIGHT PANEL ═══ */
    #RightPanel {{
        background-color: {t.bg_sidebar};
        border-left: 1px solid {t.border};
        min-width: 290px;
    }}
    #RightTabs {{
        background: {t.bg_sidebar};
        border: none;
    }}
    #RightTabs::pane {{
        border: none;
        border-top: 1px solid {t.border};
        background: {t.bg_sidebar};
    }}
    #RightTabs QTabBar {{
        background: {t.bg_sidebar};
    }}
    #RightTabs QTabBar::tab {{
        background: transparent;
        color: {t.text_dim};
        border: none;
        border-bottom: 2px solid transparent;
        padding: 10px 14px;
        margin: 0;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }}
    #RightTabs QTabBar::tab:selected {{
        color: {t.text_primary};
        border-bottom: 2px solid {t.accent};
    }}
    #RightTabs QTabBar::tab:hover:!selected {{
        color: {t.text_secondary};
    }}
    #RightTabScroll {{
        background: transparent;
        border: none;
    }}
    #RightTabScroll > QWidget > QWidget {{
        background: transparent;
    }}

    #SectionHeader {{
        color: {t.text_muted};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        padding: 14px 12px 8px 12px;
        background: transparent;
    }}

    /* ═══ CHAT ═══ */
    #ChatPanel {{ background: transparent; border: none; }}
    #ChatHistory {{
        background: transparent;
        border: none;
        color: {t.text_primary};
        font-size: 12px;
        padding: 8px 14px;
        line-height: 1.5;
    }}
    #ChatInput {{
        background-color: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 10px;
        color: {t.text_primary};
        padding: 10px 14px;
        font-size: 13px;
        margin: 0 12px 12px 12px;
        selection-background-color: {t.accent};
    }}
    #ChatInput:focus {{
        border-color: {t.accent};
    }}

    /* ═══ CONTROLS ═══ */
    #ControlPanel {{ padding: 4px 8px 12px 8px; }}
    #NetworkGraph {{
        background: {t.bg_card};
        border: 1px solid {t.border};
        border-radius: 12px;
        margin: 4px 8px;
    }}

    /* ═══ TRANSFER ═══ */
    #TransferPanel {{ background: transparent; border: none; }}
    #TransferStatus {{
        color: {t.text_secondary};
        font-size: 12px;
        padding: 0 8px;
    }}
    #TransferQueueTable {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 10px;
        gridline-color: {t.border};
        selection-background-color: {t.bg_hover};
        font-size: 11px;
        color: {t.text_primary};
        margin: 0 8px;
    }}
    #TransferQueueTable QHeaderView::section {{
        background: {t.bg_card};
        color: {t.text_dim};
        border: none;
        border-bottom: 1px solid {t.border};
        padding: 7px 8px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}

    /* ═══ SCANNER ═══ */
    #NetworkScannerPanel {{ background: transparent; border: none; }}
    #ScannerSubnetInput, #ScannerPortFilter {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 8px;
        color: {t.text_primary};
        padding: 8px 12px;
        font-size: 12px;
    }}
    #ScannerSubnetInput:focus, #ScannerPortFilter:focus {{
        border-color: {t.accent};
    }}
    #ScannerHistoryCombo {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 8px;
        color: {t.text_primary};
        padding: 6px 10px;
    }}
    #ScannerActiveOnly {{
        color: {t.text_secondary};
        font-size: 12px;
        spacing: 6px;
    }}
    #ScannerActiveOnly::indicator {{
        width: 16px; height: 16px;
        border-radius: 5px;
        border: 1.5px solid {t.border};
        background: {t.bg_input};
    }}
    #ScannerActiveOnly::indicator:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {t.accent_gradient_start},stop:1 {t.accent_gradient_end});
        border: none;
    }}
    #ScannerNote {{
        color: {t.text_dim};
        font-size: 11px;
        padding: 0 4px;
    }}
    #ScannerStatus {{
        color: {t.text_secondary};
        font-size: 11px;
        font-weight: 600;
    }}
    #ScannerTable {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 10px;
        gridline-color: {t.border};
        selection-background-color: {t.bg_hover};
        font-size: 12px;
        color: {t.text_primary};
    }}
    #ScannerTable QHeaderView::section {{
        background: {t.bg_card};
        color: {t.text_dim};
        border: none;
        border-bottom: 1px solid {t.border};
        padding: 7px 8px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}

    /* ═══ AUDIT ═══ */
    #AuditLogPanel {{ background: transparent; border: none; }}
    #AuditLogView {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 10px;
        color: {t.text_primary};
        font-size: 11px;
        padding: 10px 12px;
        margin: 0 8px 8px 8px;
        font-family: 'SF Mono', 'JetBrains Mono', 'Menlo', 'Fira Code', monospace;
        line-height: 1.5;
    }}

    /* ═══ PROGRESS BAR (gradient) ═══ */
    QProgressBar {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 7px;
        min-height: 14px;
        max-height: 14px;
        text-align: center;
        color: {t.text_primary};
        font-size: 9px;
        font-weight: 600;
        margin: 0 8px 8px 8px;
    }}
    QProgressBar::chunk {{
        border-radius: 6px;
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_gradient_start},stop:1 {t.accent_gradient_end});
    }}

    /* ═══ BUTTONS (PRIMARY) ═══ */
    QPushButton {{
        border: none;
        border-radius: 8px;
        padding: 9px 18px;
        font-weight: 600;
        font-size: 13px;
        color: white;
        min-height: 20px;
        letter-spacing: -0.1px;
    }}
    QPushButton:disabled {{
        background: {t.bg_card};
        color: {t.text_dim};
        border: 1px solid {t.border};
    }}

    /* Lock — warm amber */
    QPushButton#BtnLock {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f59e0b,stop:1 #f97316);
    }}
    QPushButton#BtnLock:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #fbbf24,stop:1 #fb923c);
    }}
    QPushButton#BtnLock:pressed {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #d97706,stop:1 #ea580c);
    }}

    /* Shutdown — vivid red */
    QPushButton#BtnShutdown {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ef4444,stop:1 #f43f5e);
    }}
    QPushButton#BtnShutdown:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f87171,stop:1 #fb7185);
    }}
    QPushButton#BtnShutdown:pressed {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #dc2626,stop:1 #e11d48);
    }}

    /* Restart — indigo→purple */
    QPushButton#BtnRestart {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_gradient_start},stop:1 {t.accent_gradient_end});
    }}
    QPushButton#BtnRestart:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_hover},stop:1 #c084fc);
    }}
    QPushButton#BtnRestart:pressed {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4338ca,stop:1 #9333ea);
    }}

    /* Send button */
    QPushButton#BtnSend {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_gradient_start},stop:1 {t.accent_gradient_end});
    }}
    QPushButton#BtnSend:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_hover},stop:1 #c084fc);
    }}

    /* Scanner start */
    QPushButton#BtnScannerStart {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_gradient_start},stop:1 {t.accent_gradient_end});
        color: white;
        padding: 8px 16px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#BtnScannerStart:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {t.accent_hover},stop:1 #c084fc);
    }}

    /* ═══ SECONDARY BUTTONS ═══ */
    QPushButton#BtnTransferCancel, QPushButton#BtnTransferRetry,
    QPushButton#BtnTransferAdd,
    QPushButton#BtnScannerExport, QPushButton#BtnScannerStop {{
        background: {t.bg_card};
        border: 1px solid {t.border};
        color: {t.text_secondary};
        padding: 8px 16px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#BtnTransferCancel:hover, QPushButton#BtnTransferRetry:hover,
    QPushButton#BtnTransferAdd:hover,
    QPushButton#BtnScannerExport:hover, QPushButton#BtnScannerStop:hover {{
        background: {t.bg_hover};
        color: {t.text_primary};
        border-color: {t.border_focus};
    }}

    /* ═══ PHASE 2: VOLUME / CLIPBOARD / SYSTEM BUTTONS ═══ */
    QPushButton#BtnVolMute, QPushButton#BtnVolDown,
    QPushButton#BtnVolUp, QPushButton#BtnVolUnmute {{
        background: {t.bg_card};
        border: 1px solid {t.border};
        color: {t.text_secondary};
        padding: 7px 0;
        border-radius: 8px;
        font-size: 11px;
        font-weight: 600;
        min-width: 0;
    }}
    QPushButton#BtnVolMute:hover, QPushButton#BtnVolDown:hover,
    QPushButton#BtnVolUp:hover, QPushButton#BtnVolUnmute:hover {{
        background: {t.bg_hover};
        color: {t.text_primary};
        border-color: {t.border_focus};
    }}

    QPushButton#BtnClipGet, QPushButton#BtnClipPush,
    QPushButton#BtnSysRefresh, QPushButton#BtnSysScreenshot {{
        background: {t.bg_card};
        border: 1px solid {t.border};
        color: {t.text_secondary};
        padding: 7px 16px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#BtnClipGet:hover, QPushButton#BtnClipPush:hover,
    QPushButton#BtnSysRefresh:hover, QPushButton#BtnSysScreenshot:hover {{
        background: {t.bg_hover};
        color: {t.text_primary};
        border-color: {t.border_focus};
    }}

    /* ═══ PHASE 2: INPUTS / VIEWS ═══ */
    #ClipboardView {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 10px;
        color: {t.text_primary};
        font-size: 12px;
        padding: 8px 10px;
        margin: 0;
    }}
    #SysInfoView {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 10px;
        color: {t.text_primary};
        font-size: 12px;
        padding: 10px 12px;
    }}
    #CommandDelayInput {{
        background: {t.bg_input};
        border: 1px solid {t.border};
        border-radius: 7px;
        padding: 5px 8px;
        color: {t.text_primary};
        font-size: 12px;
        font-weight: 600;
    }}
    #CommandDelayInput:focus {{
        border-color: {t.accent};
    }}
    QCheckBox#WarnCheckbox, QCheckBox#BroadcastCheckbox {{
        color: {t.text_secondary};
        font-size: 11px;
        font-weight: 500;
        spacing: 5px;
    }}
    QCheckBox#WarnCheckbox::indicator, QCheckBox#BroadcastCheckbox::indicator {{
        width: 15px; height: 15px;
        border-radius: 4px;
        border: 1.5px solid {t.border};
        background: {t.bg_input};
    }}
    QCheckBox#WarnCheckbox::indicator:checked, QCheckBox#BroadcastCheckbox::indicator:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {t.accent_gradient_start},stop:1 {t.accent_gradient_end});
        border: none;
    }}

    /* ═══ COLLAPSE TOGGLE ═══ */
    #CollapseToggle {{
        background: {t.bg_card};
        border: 1px solid {t.border};
        border-radius: 7px;
        color: {t.text_dim};
        font-size: 13px;
        padding: 4px 6px;
        min-width: 24px; max-width: 24px;
        min-height: 24px; max-height: 24px;
    }}
    #CollapseToggle:hover {{
        background: {t.bg_hover};
        color: {t.accent};
        border-color: {t.accent};
    }}

    /* ═══ SCROLLBARS (thin, elegant) ═══ */
    QScrollBar:vertical {{
        background: {t.scrollbar_bg};
        width: 6px;
        margin: 4px 1px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.scrollbar_handle};
        min-height: 32px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.scrollbar_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ height: 0; }}

    /* ═══ SPLITTER ═══ */
    QSplitter {{ background-color: {t.bg_root}; }}
    QSplitter::handle {{ background-color: {t.border}; width: 1px; }}

    /* ═══ TOOLTIPS ═══ */
    QToolTip {{
        background: {t.bg_card};
        color: {t.text_primary};
        border: 1px solid {t.border};
        border-radius: 8px;
        padding: 8px 14px;
        font-size: 12px;
    }}

    /* ═══ DIALOGS ═══ */
    QMessageBox {{
        background: {t.bg_sidebar};
    }}
    QMessageBox QLabel {{
        color: {t.text_primary};
        font-size: 13px;
        padding: 10px;
        background: transparent;
    }}
    QMessageBox QPushButton {{
        background: {t.bg_card};
        border: 1px solid {t.border};
        min-width: 88px;
        padding: 8px 22px;
    }}
    QMessageBox QPushButton:hover {{
        background: {t.bg_hover};
        border-color: {t.accent};
    }}
    """
