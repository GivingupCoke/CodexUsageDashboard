from __future__ import annotations

import math
import queue
import sys
import threading
import tkinter as tk
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import ttk
from typing import Any

from usage_core import (
    BEIJING,
    ModelUsage,
    PRICE_CHECKED_ON,
    UsageReport,
    collect_history,
    collect_usage,
    format_tokens,
)

BG = "#0b0d12"
TITLE_BG = "#0e1118"
PANEL = "#11151d"
CARD = "#151a24"
BORDER = "#252b38"
TEXT = "#f4f6f8"
MUTED = "#929aa8"
SUBTLE = "#697180"
ACCENT = "#7c8cff"
ACCENT_HOVER = "#8f9cff"
ACCENT_PRESSED_BG = "#6675e8"
SUCCESS = "#55cda5"
ERROR = "#f29a9a"
WARNING_BG = "#2a2118"
ACTION_PRESSED_BG = "#1d2330"

ICON_FONT = "Segoe MDL2 Assets"
UI_FONT = "Segoe UI Variable Text"
DISPLAY_FONT = "Segoe UI Variable Display"
APP_NAME = "Codex Usage"
APP_VERSION = "1.1"
APP_DISPLAY_NAME = f"{APP_NAME} v{APP_VERSION}"
APP_ICON_ICO = Path("assets") / "codex_usage_dashboard.ico"
APP_ICON_PNG = Path("assets") / "codex_usage_dashboard.png"
CAPTION_HOVER_BG = "#29344a"
WINDOWS_APP_USER_MODEL_ID = "LiHua.CodexUsageDashboard"
SINGLE_INSTANCE_MUTEX_NAME = "Local\\LiHua.CodexUsageDashboard.SingleInstance"
PIN_ICON = "\ue718"
COLLAPSE_ICON = "\ue70e"
EXPAND_ICON = "\ue70d"
MINIMIZE_ICON = "\ue921"
MAXIMIZE_ICON = "\ue922"
RESTORE_ICON = "\ue923"
CLOSE_ICON = "\ue8bb"
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9
ERROR_ALREADY_EXISTS = 183
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_CAPTION = 0x00C00000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE
ALL_MODELS_LABEL = "全部模型"

MAIN_WINDOW_GEOMETRY = "430x480"
MAIN_WINDOW_MIN_WIDTH = 380
MAIN_WINDOW_MIN_HEIGHT = 460

_instance_mutex_handle: int | None = None


def _resource_path(relative_path: str | Path) -> Path:
    """Resolve an asset both from source checkout and a PyInstaller bundle."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def _activate_existing_instance() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = user32.FindWindowW(None, f"{APP_DISPLAY_NAME} · 今日用量")
        if not handle:
            return
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, SW_RESTORE)
        else:
            user32.ShowWindow(handle, SW_SHOW)
        user32.BringWindowToTop(handle)
        user32.SetForegroundWindow(handle)
    except (AttributeError, OSError):
        return


def _acquire_single_instance() -> bool:
    """Keep one dashboard process and focus it when launched again."""
    global _instance_mutex_handle
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            _activate_existing_instance()
            return False
        _instance_mutex_handle = int(handle)
        return True
    except (AttributeError, OSError):
        return True


@dataclass(frozen=True)
class WorkerResult:
    request_id: int
    value: Any | None
    error: Exception | None


class LatestResultQueue:
    """A thread-safe queue that only returns the newest request's result."""

    def __init__(self) -> None:
        self._queue: queue.Queue[WorkerResult] = queue.Queue()
        self._current_request = 0

    def begin(self) -> int:
        self._current_request += 1
        return self._current_request

    def put(self, result: WorkerResult) -> None:
        self._queue.put(result)

    def get_current_nowait(self) -> WorkerResult | None:
        current: WorkerResult | None = None
        while True:
            try:
                candidate = self._queue.get_nowait()
            except queue.Empty:
                return current
            if candidate.request_id == self._current_request:
                current = candidate


def tick_positions(count: int, max_ticks: int = 7) -> list[int]:
    if count <= 0 or max_ticks <= 0:
        return []
    if count <= max_ticks:
        return list(range(count))
    if max_ticks == 1:
        return [count - 1]
    step = math.ceil((count - 1) / (max_ticks - 1))
    positions = list(range(0, count, step))
    if positions[-1] != count - 1:
        positions.append(count - 1)
    return positions[-max_ticks:]


def model_options(reports: Iterable[UsageReport]) -> tuple[str, ...]:
    totals: dict[str, int] = {}
    for report in reports:
        for model, usage in report.by_model.items():
            totals[model] = totals.get(model, 0) + usage.total_tokens
    ordered = sorted(totals, key=lambda model: (-totals[model], model.casefold()))
    return (ALL_MODELS_LABEL, *ordered)


def usage_for_model(report: UsageReport, model: str) -> ModelUsage:
    if model == ALL_MODELS_LABEL:
        return report
    return report.by_model.get(model, ModelUsage())


def _cost_for_model(report: UsageReport, model: str) -> float:
    if model == ALL_MODELS_LABEL:
        return report.cost_usd
    return usage_for_model(report, model).estimated_cost_usd


def _unpriced_models_for_selection(report: UsageReport, model: str) -> tuple[str, ...]:
    if model == ALL_MODELS_LABEL:
        return report.unpriced_models
    usage = usage_for_model(report, model)
    return (model,) if usage.total_tokens and model in report.unpriced_models else ()


def _rate_limit_label(window_minutes: int | None) -> str:
    if window_minutes == 10_080:
        return "周额度"
    if window_minutes and window_minutes % 60 == 0:
        return f"{window_minutes // 60} 小时额度"
    return "额度"


def _quota_lines(report: UsageReport) -> list[tuple[str, float | None, datetime | None]]:
    """Return the two account-global Codex quota windows explicitly."""
    has_weekly_window = report._weekly_rate_limit_observed_at is not None or report.rate_limit_window_minutes == 10_080
    weekly_used_percent = report.weekly_used_percent if has_weekly_window else None
    weekly_reset_at = report.weekly_reset_at if has_weekly_window else None
    return [
        ("5 小时额度（全局）", report.five_hour_used_percent, report.five_hour_reset_at),
        ("一周额度（全局）", weekly_used_percent, weekly_reset_at),
    ]


def _quota_bar(used_percent: float | None) -> str:
    if used_percent is None:
        return "░" * 10
    filled = max(0, min(10, round(used_percent / 10)))
    return "█" * filled + "░" * (10 - filled)


def _tray_tooltip(report: UsageReport) -> str:
    quota_by_label = {label: used_percent for label, used_percent, _reset_at in _quota_lines(report)}

    def percent(label: str) -> str:
        value = quota_by_label.get(label)
        return "未知" if value is None else f"{value:.0f}%"

    tooltip = (
        f"{APP_DISPLAY_NAME} · 今日 {format_tokens(report.total_tokens)} · "
        f"5小时 {percent('5 小时额度（全局）')} · 一周 {percent('一周额度（全局）')}"
    )
    # Windows NOTIFYICONDATA.szTip is WCHAR[128], including the null terminator.
    return tooltip[:127]


def _set_native_titlebar_dark(window: tk.Misc) -> None:
    if sys.platform != "win32" or not window.winfo_exists():
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = user32.GetParent(window.winfo_id()) or window.winfo_id()
        enabled = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
    except (AttributeError, OSError, tk.TclError):
        return


class UsageDashboard(tk.Tk):
    def __init__(self) -> None:
        self._set_windows_app_identity()
        super().__init__()
        self.title(f"{APP_DISPLAY_NAME} · 今日用量")
        self.geometry(MAIN_WINDOW_GEOMETRY)
        self.minsize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        self.configure(bg=BG)
        self._set_app_icon()
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        self.sessions_root = Path.home() / ".codex" / "sessions"
        self._topmost = tk.BooleanVar(value=True)
        self.model_var = tk.StringVar(value=ALL_MODELS_LABEL)
        self._collapsed = False
        self._maximized = False
        self._expanded_geometry = MAIN_WINDOW_GEOMETRY
        self._restore_geometry = self._expanded_geometry
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._window_handle: int | None = None
        self._taskbar_registration_forced = False
        self._taskbar_registration_attempts = 0
        self._tray_icon: Any | None = None
        self._tray_status_lines = [
            "今日总 Token：读取中…",
            "API 参考估算：读取中…",
            "输入 Token：读取中…",
            "输出 Token：读取中…",
            "缓存率：读取中…",
            "5 小时额度：读取中…",
            "一周额度：读取中…",
            "未计价：读取中…",
        ]
        self._tray_status = "\n".join(self._tray_status_lines)
        self._tray_tooltip = f"{APP_DISPLAY_NAME} · 正在读取用量"
        self._last_report: UsageReport | None = None
        self._history_window: HistoryWindow | None = None
        self._refresh_results = LatestResultQueue()
        self._refresh_running = False
        self._refresh_poll_after: str | None = None
        self._build_ui()
        self._apply_windows_window_style()
        self.after_idle(self._apply_windows_window_style)
        self.after(800, self._register_taskbar_window)
        self.protocol("WM_DELETE_WINDOW", self._close_to_tray)
        self._set_summary("正在读取今日日志…")
        self.refresh()
        self.after(60_000, self._scheduled_refresh)

    @staticmethod
    def _set_windows_app_identity() -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            set_app_id.argtypes = [ctypes.c_wchar_p]
            set_app_id.restype = ctypes.c_long
            set_app_id(WINDOWS_APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            return

    def _set_app_icon(self) -> None:
        ico_path = _resource_path(APP_ICON_ICO)
        png_path = _resource_path(APP_ICON_PNG)
        try:
            if ico_path.exists():
                self.iconbitmap(default=str(ico_path))
                # Keep the Windows taskbar/window icon sourced from the same
                # ICO that PyInstaller embeds as the EXE file icon.  Calling
                # iconphoto afterwards would replace it with the PNG source.
                if sys.platform == "win32":
                    return
        except tk.TclError:
            pass
        try:
            if png_path.exists():
                self._app_icon_image = tk.PhotoImage(file=str(png_path))
                self.iconphoto(True, self._app_icon_image)
        except tk.TclError:
            pass

    def _setup_tray(self) -> None:
        if sys.platform != "win32" or self._tray_icon is not None:
            return
        try:
            import pystray
            from PIL import Image

            with Image.open(_resource_path(APP_ICON_PNG)) as source:
                tray_image = source.convert("RGBA")
            status_items = [
                pystray.MenuItem(
                    lambda item, index=index: self._tray_status_text(index, item),
                    None,
                    enabled=False,
                )
                for index in range(len(self._tray_status_lines))
            ]
            menu = pystray.Menu(
                *status_items,
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "进入主界面",
                    lambda _icon, _item: self.after(0, self._show_main_window),
                    default=True,
                ),
                pystray.MenuItem("刷新", lambda _icon, _item: self.after(0, self.refresh)),
                pystray.MenuItem("历史记录", lambda _icon, _item: self.after(0, self._open_history_from_tray)),
                pystray.MenuItem("退出", lambda _icon, _item: self.after(0, self._exit_application)),
            )
            self._tray_icon = pystray.Icon(
                "CodexUsageDashboard",
                tray_image,
                self._tray_tooltip,
                menu,
            )
            self._tray_icon.run_detached()
        except (ImportError, OSError, tk.TclError):
            self._tray_icon = None

    def _tray_status_text(self, index: int, _item=None) -> str:
        return self._tray_status_lines[index]

    def _update_tray_status(self, report: UsageReport) -> None:
        suffix = "*" if report.cost_is_partial else ""
        unpriced = ", ".join(report.unpriced_models) if report.cost_is_partial else "无"
        self._tray_status_lines = [
            f"今日总 Token：{format_tokens(report.total_tokens)}",
            f"API 参考估算：${report.cost_usd:,.4f}{suffix}",
            f"输入 Token：{format_tokens(report.input_tokens)}",
            f"输出 Token：{format_tokens(report.output_tokens)}",
            f"缓存率：{report.cache_rate:.1%}",
            *[
                f"{label}：{('未知' if used_percent is None else f'{used_percent:.0f}%')}，下次重置 "
                f"{reset_at.strftime('%m-%d %H:%M') if reset_at else '未知'}"
                for label, used_percent, reset_at in _quota_lines(report)
            ],
            f"未计价：{unpriced}",
        ]
        self._tray_status = "\n".join(self._tray_status_lines)
        self._tray_tooltip = _tray_tooltip(report)
        if self._tray_icon is not None:
            try:
                self._tray_icon.title = self._tray_tooltip
                self._tray_icon.update_menu()
            except (OSError, ValueError):
                pass

    def _show_main_window(self) -> None:
        if not self.winfo_exists():
            return
        self.deiconify()
        self._apply_windows_window_style()
        self.after_idle(self._apply_windows_window_style)
        self.lift()
        self.attributes("-topmost", self._topmost.get())
        self.focus_force()

    def _open_history_from_tray(self) -> None:
        self._show_main_window()
        self.open_history()

    def _close_to_tray(self) -> None:
        if self._tray_icon is None:
            self._setup_tray()
            if self._tray_icon is None:
                self._minimize_window()
                return
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.withdraw()
        self.withdraw()

    def _exit_application(self) -> None:
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window._close()
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.destroy()

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Panel.TFrame", background=BG)
        style.configure("Surface.TFrame", background=PANEL)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(UI_FONT, 9))
        style.configure(
            "Secondary.TButton",
            background=CARD,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=CARD,
            darkcolor=CARD,
            font=(UI_FONT, 9),
            padding=(11, 6),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", BORDER), ("disabled", PANEL)],
            foreground=[("disabled", SUBTLE)],
        )
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            bordercolor=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            font=(UI_FONT, 9, "bold"),
            padding=(11, 6),
        )
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", BORDER)])
        style.configure(
            "Filter.TCombobox",
            fieldbackground=CARD,
            background=CARD,
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=CARD,
            darkcolor=CARD,
            padding=(7, 3),
        )
        style.map(
            "Filter.TCombobox",
            fieldbackground=[("readonly", CARD)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", CARD)],
            selectforeground=[("readonly", TEXT)],
        )

        self._build_titlebar()
        self.content = ttk.Frame(self, style="Panel.TFrame", padding=(16, 12, 16, 14))
        self.content.pack(fill="both", expand=True)
        meta = ttk.Frame(self.content, style="Panel.TFrame")
        meta.pack(fill="x", pady=(0, 8))
        self.connection_label = ttk.Label(meta, text="北京时间 · 本地日志", style="Muted.TLabel")
        self.connection_label.pack(side="left")
        self.model_filter = ttk.Combobox(
            meta,
            textvariable=self.model_var,
            values=(ALL_MODELS_LABEL,),
            state="readonly",
            width=18,
            style="Filter.TCombobox",
        )
        self.model_filter.pack(side="right")
        self.model_filter.bind("<<ComboboxSelected>>", self._on_model_selected)
        self.body = ttk.Frame(self.content, style="Panel.TFrame")
        self.body.pack(fill="both", expand=True)
        self.summary = tk.Text(
            self.body,
            height=15,
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#4454ad",
            selectforeground="#ffffff",
            font=(UI_FONT, 10),
            wrap="none",
            undo=False,
        )
        self.summary.pack(fill="both", expand=True)
        self.summary.configure(padx=14, pady=12, tabs=("2.25i",))
        self.summary.bind("<KeyPress>", self._block_summary_edits)
        controls = ttk.Frame(self.body, style="Panel.TFrame")
        controls.pack(fill="x", pady=(10, 0))
        self.history_button = tk.Button(
            controls,
            text="历史记录",
            command=self.open_history,
            bg=CARD,
            fg=TEXT,
            activebackground=ACTION_PRESSED_BG,
            activeforeground=TEXT,
            disabledforeground=SUBTLE,
            font=(UI_FONT, 9),
            relief="flat",
            bd=0,
            padx=11,
            pady=4,
            highlightthickness=0,
            takefocus=False,
            cursor="hand2",
        )
        self.history_button.pack(side="left")
        self._bind_action_button_feedback(
            self.history_button,
            normal_bg=CARD,
            hover_bg=BORDER,
            pressed_bg=ACTION_PRESSED_BG,
        )
        self.refresh_button = tk.Button(
            controls,
            text="刷新",
            command=self.refresh,
            bg=ACCENT,
            fg="#ffffff",
            activebackground=ACCENT_PRESSED_BG,
            activeforeground="#ffffff",
            disabledforeground="#d8dcff",
            font=(UI_FONT, 9, "bold"),
            relief="flat",
            bd=0,
            padx=11,
            pady=4,
            highlightthickness=0,
            takefocus=False,
            cursor="hand2",
        )
        self.refresh_button.pack(side="left", padx=(8, 0))
        self._bind_action_button_feedback(
            self.refresh_button,
            normal_bg=ACCENT,
            hover_bg=ACCENT_HOVER,
            pressed_bg=ACCENT_PRESSED_BG,
        )
        ttk.Label(controls, text="每 60 秒自动更新", style="Muted.TLabel").pack(side="right")
        self.summary.tag_configure("eyebrow", foreground=ACCENT, font=(UI_FONT, 9, "bold"))
        self.summary.tag_configure("label", foreground=MUTED, font=(UI_FONT, 9))
        self.summary.tag_configure("hero", foreground=TEXT, font=("Cascadia Mono", 20, "bold"), spacing3=3)
        self.summary.tag_configure("hero_cost", foreground=TEXT, font=("Cascadia Mono", 15, "bold"), spacing3=3)
        self.summary.tag_configure("value", foreground=TEXT, font=("Cascadia Mono", 11, "bold"))
        self.summary.tag_configure("accent", foreground=ACCENT, font=("Cascadia Mono", 10, "bold"))
        self.summary.tag_configure("success", foreground=SUCCESS, font=("Cascadia Mono", 10, "bold"))
        self.summary.tag_configure("divider", foreground=BORDER)
        self.summary.tag_configure("error", foreground=ERROR, background=WARNING_BG, font=(UI_FONT, 9))

    def _build_titlebar(self) -> None:
        self.titlebar = tk.Frame(self, bg=TITLE_BG, height=40, highlightthickness=0)
        self.titlebar.pack(fill="x")
        self.titlebar.pack_propagate(False)
        brand = tk.Frame(self.titlebar, bg=TITLE_BG)
        brand.pack(side="left", fill="y", padx=(12, 0))
        mark = tk.Label(
            brand,
            text="C",
            bg=ACCENT,
            fg="#ffffff",
            font=(DISPLAY_FONT, 8, "bold"),
            width=2,
            height=1,
        )
        mark.pack(side="left", pady=10)
        self.app_title_label = tk.Label(
            brand,
            text=APP_DISPLAY_NAME,
            bg=TITLE_BG,
            fg=TEXT,
            font=(DISPLAY_FONT, 10, "bold"),
            padx=8,
        )
        self.app_title_label.pack(side="left", fill="y")
        self.collapse_button = self._caption_button(
            brand,
            COLLAPSE_ICON,
            self.toggle_collapsed,
            width=3,
            hover_bg=PANEL,
        )
        self.collapse_button.pack(side="left", fill="y")

        self.caption_controls = tk.Frame(self.titlebar, bg=TITLE_BG)
        self.caption_controls.pack(side="right", fill="y")
        self.pin_button = self._caption_button(self.caption_controls, PIN_ICON, self._toggle_topmost)
        self.minimize_button = self._caption_button(
            self.caption_controls,
            MINIMIZE_ICON,
            self._minimize_window,
        )
        self.maximize_button = self._caption_button(
            self.caption_controls,
            MAXIMIZE_ICON,
            self._toggle_maximize,
        )
        self.close_button = self._caption_button(
            self.caption_controls,
            CLOSE_ICON,
            self._close_to_tray,
            hover_bg="#c42b1c",
        )
        for button in (self.pin_button, self.minimize_button, self.maximize_button, self.close_button):
            button.pack(side="left", fill="y")
        self._sync_pin_button()

        for widget in (self.titlebar, brand, mark, self.app_title_label):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag_window)
            widget.bind("<Double-Button-1>", lambda _event: self._toggle_maximize())
            widget.bind("<Button-3>", self._show_system_menu)

    def _caption_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        width: int = 5,
        hover_bg: str = CAPTION_HOVER_BG,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bd=0,
            relief="flat",
            bg=TITLE_BG,
            fg=TEXT,
            activebackground=hover_bg,
            activeforeground="#ffffff",
            font=(ICON_FONT, 10),
            cursor="hand2",
            highlightthickness=0,
            takefocus=True,
        )
        button.bind("<Enter>", lambda _event: button.configure(bg=hover_bg))
        button.bind("<Motion>", lambda _event: button.configure(bg=hover_bg))
        button.bind("<Leave>", lambda _event: self._reset_caption_button(button))
        return button

    def _reset_caption_button(self, button: tk.Button) -> None:
        if button is self.pin_button and self._topmost.get():
            button.configure(bg=ACCENT)
        else:
            button.configure(bg=TITLE_BG)

    @staticmethod
    def _set_action_button_background(button: tk.Button, color: str) -> None:
        if str(button.cget("state")) != "disabled":
            button.configure(bg=color)

    def _bind_action_button_feedback(
        self,
        button: tk.Button,
        *,
        normal_bg: str,
        hover_bg: str,
        pressed_bg: str,
    ) -> None:
        set_background = self._set_action_button_background
        button.bind("<Enter>", lambda _event: set_background(button, hover_bg))
        button.bind("<Motion>", lambda _event: set_background(button, hover_bg))
        button.bind("<Leave>", lambda _event: set_background(button, normal_bg))
        button.bind("<ButtonPress-1>", lambda _event: set_background(button, pressed_bg))
        button.bind("<ButtonRelease-1>", lambda _event: set_background(button, hover_bg))

    @staticmethod
    def _block_summary_edits(event):
        if (event.state & 0x4) and event.keysym.lower() in {"a", "c"}:
            return None
        return "break"

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._expanded_geometry = self.geometry()
            self.content.pack_forget()
            self.collapse_button.configure(text=EXPAND_ICON)
            self.minsize(MAIN_WINDOW_MIN_WIDTH, 40)
            self.geometry(f"{max(MAIN_WINDOW_MIN_WIDTH, self.winfo_width())}x40+{self.winfo_x()}+{self.winfo_y()}")
        else:
            self.content.pack(fill="both", expand=True)
            self.collapse_button.configure(text=COLLAPSE_ICON)
            self.minsize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
            self.geometry(self._expanded_geometry)

    def _toggle_topmost(self) -> None:
        self._topmost.set(not self._topmost.get())
        self.attributes("-topmost", self._topmost.get())
        self._sync_pin_button()

    def _sync_pin_button(self) -> None:
        active = self._topmost.get()
        self.pin_button.configure(
            bg=ACCENT if active else TITLE_BG,
            activebackground=ACCENT_HOVER if active else PANEL,
        )

    def _register_taskbar_window(self) -> None:
        if not self.winfo_exists() or self.state() == "withdrawn":
            return
        self._taskbar_registration_attempts += 1
        if not self.winfo_viewable():
            if self._taskbar_registration_attempts < 20:
                self.after(250, self._register_taskbar_window)
            return
        # The initial Tk window can be visible before Explorer has observed
        # its final styles. Repeat the hide/show transition after startup so
        # the shell creates a persistent taskbar button.
        self._taskbar_registration_forced = False
        self._apply_windows_window_style()
        if not self._taskbar_registration_forced and self._taskbar_registration_attempts < 20:
            self.after(250, self._register_taskbar_window)

    def _apply_windows_window_style(self) -> None:
        if sys.platform != "win32" or not self.winfo_exists():
            return
        try:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hwnd_type = ctypes.c_void_p
            long_ptr_type = ctypes.c_ssize_t
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.FindWindowW.restype = hwnd_type
            user32.GetAncestor.argtypes = [hwnd_type, ctypes.c_uint]
            user32.GetAncestor.restype = hwnd_type
            user32.GetParent.argtypes = [hwnd_type]
            user32.GetParent.restype = hwnd_type
            user32.GetWindowLongPtrW.argtypes = [hwnd_type, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = long_ptr_type
            user32.SetWindowLongPtrW.argtypes = [hwnd_type, ctypes.c_int, long_ptr_type]
            user32.SetWindowLongPtrW.restype = long_ptr_type
            user32.SetWindowPos.argtypes = [
                hwnd_type,
                hwnd_type,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = ctypes.c_bool
            inner_handle = self.winfo_id()
            handle = (
                user32.FindWindowW(None, self.title())
                or user32.GetAncestor(inner_handle, 2)
                or user32.GetParent(inner_handle)
                or inner_handle
            )
            handle = ctypes.c_void_p(handle)
            self._window_handle = handle.value
            get_window_long = user32.GetWindowLongPtrW
            set_window_long = user32.SetWindowLongPtrW
            style = get_window_long(handle, -16)
            # Keep the native system commands available to the custom
            # caption buttons, but do not ask Windows for a resize frame.
            # The frame is rendered as a light border around the otherwise
            # borderless Tk window on some Windows themes.
            style &= ~(WS_CAPTION | WS_BORDER | WS_DLGFRAME | WS_THICKFRAME)
            style |= WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
            set_window_long(handle, -16, style)
            ex_style = get_window_long(handle, -20)
            ex_style = (ex_style & ~0x00000080) | 0x00040000
            set_window_long(handle, -20, ex_style)
            # A borderless Tk window may retain an owner and then disappear
            # from the taskbar. Make the root a normal app window explicitly.
            user32.SetWindowLongPtrW(handle, -8, 0)
            window_was_visible = bool(user32.IsWindowVisible(handle))
            if not self._taskbar_registration_forced and window_was_visible:
                # Tk's overrideredirect window is initially omitted from the
                # taskbar. A hide/show transition after the final style change
                # forces Explorer to create the taskbar button immediately.
                user32.ShowWindow(handle, SW_HIDE)
            user32.SetWindowPos(
                handle,
                ctypes.c_void_p(0),
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0004 | 0x0020 | SWP_SHOWWINDOW,
            )
            try:
                # Windows 11 otherwise draws a 1px light border even for a
                # popup window. DWMWA_COLOR_NONE suppresses that DWM border
                # while keeping the custom title bar and rounded corners.
                border_color = ctypes.c_uint(DWMWA_COLOR_NONE)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    handle,
                    DWMWA_BORDER_COLOR,
                    ctypes.byref(border_color),
                    ctypes.sizeof(border_color),
                )
            except (AttributeError, OSError):
                pass
            if window_was_visible:
                user32.ShowWindow(handle, SW_SHOW)
                self._taskbar_registration_forced = True
            try:
                corner_preference = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    handle,
                    33,
                    ctypes.byref(corner_preference),
                    ctypes.sizeof(corner_preference),
                )
            except (AttributeError, OSError):
                pass
        except (AttributeError, OSError, tk.TclError):
            self._window_handle = None

    def _start_drag(self, event) -> None:
        if self._maximized:
            pointer_ratio = event.x_root / max(1, self.winfo_screenwidth())
            self._toggle_maximize()
            self.update_idletasks()
            new_x = int(event.x_root - self.winfo_width() * pointer_ratio)
            new_y = max(0, event.y_root - 18)
            self.geometry(f"+{new_x}+{new_y}")

        if sys.platform == "win32" and self._window_handle:
            try:
                import ctypes

                # Let Windows run its native move loop.  Repositioning a
                # borderless Tk window from every <B1-Motion> event can leave
                # stale DWM/Tk frames visible while the window is moving.
                self._drag_origin = None
                user32 = ctypes.windll.user32
                user32.ReleaseCapture()
                user32.SendMessageW(self._window_handle, WM_NCLBUTTONDOWN, HTCAPTION, 0)
                return "break"
            except (AttributeError, OSError):
                pass

        self._drag_origin = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def _drag_window(self, event) -> None:
        if self._drag_origin is None:
            return
        start_x, start_y, window_x, window_y = self._drag_origin
        self.geometry(f"+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}")

    def _minimize_window(self) -> None:
        if sys.platform == "win32" and self._window_handle:
            try:
                import ctypes

                ctypes.windll.user32.ShowWindow(self._window_handle, 6)
                return
            except (AttributeError, OSError):
                pass
        self.overrideredirect(False)
        self.iconify()
        self.after(100, lambda: self.overrideredirect(True))

    def _toggle_maximize(self) -> None:
        was_withdrawn = self.state() == "withdrawn"
        if not self._maximized:
            self._restore_geometry = self.geometry()
            self._maximized = True
            command = 3
        else:
            self._maximized = False
            command = 9
        self.maximize_button.configure(text=RESTORE_ICON if self._maximized else MAXIMIZE_ICON)
        if was_withdrawn:
            return
        if sys.platform == "win32" and self._window_handle:
            try:
                import ctypes

                ctypes.windll.user32.ShowWindow(self._window_handle, command)
                return
            except (AttributeError, OSError):
                pass
        if self._maximized:
            self.state("zoomed")
        else:
            self.state("normal")
            self.geometry(self._restore_geometry)

    def _show_system_menu(self, event) -> None:
        if sys.platform != "win32" or not self._window_handle:
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            menu = user32.GetSystemMenu(self._window_handle, False)
            command = user32.TrackPopupMenu(
                menu, 0x0100 | 0x0002, event.x_root, event.y_root, 0, self._window_handle, None
            )
            if command:
                user32.PostMessageW(self._window_handle, 0x0112, command, 0)
        except (AttributeError, OSError):
            return

    def _scheduled_refresh(self) -> None:
        self.refresh()
        self.after(60_000, self._scheduled_refresh)

    def refresh(self) -> None:
        if self._refresh_running:
            return
        self._refresh_running = True
        request_id = self._refresh_results.begin()
        self.refresh_button.configure(text="刷新中…", state="disabled", bg=BORDER)
        threading.Thread(target=self._refresh_worker, args=(request_id,), daemon=True).start()
        if self._refresh_poll_after is None:
            self._refresh_poll_after = self.after(50, self._poll_refresh_result)

    def _refresh_worker(self, request_id: int) -> None:
        try:
            report = collect_usage(self.sessions_root, datetime.now(BEIJING).date())
            result = WorkerResult(request_id, report, None)
        except Exception as exc:
            result = WorkerResult(request_id, None, exc)
        self._refresh_results.put(result)

    def _poll_refresh_result(self) -> None:
        self._refresh_poll_after = None
        result = self._refresh_results.get_current_nowait()
        if result is None:
            self._refresh_poll_after = self.after(50, self._poll_refresh_result)
            return
        self._refresh_running = False
        self.refresh_button.configure(text="刷新", state="normal", bg=ACCENT)
        if result.error is not None:
            self._set_summary(f"读取失败：{result.error}\n请点击“立即刷新”重试。")
            return
        report = result.value
        if isinstance(report, UsageReport):
            self._last_report = report
            self._sync_model_options(report)
            self._update_tray_status(report)
            self._render_summary(report)

    def _set_summary(self, text: str) -> None:
        self.summary.configure(state="normal")
        self.summary.delete("1.0", tk.END)
        self.summary.insert("1.0", text)
        self.summary.configure(state="disabled")

    def _sync_model_options(self, report: UsageReport) -> None:
        options = model_options((report,))
        self.model_filter.configure(values=options)
        if self.model_var.get() not in options:
            self.model_var.set(ALL_MODELS_LABEL)

    def _on_model_selected(self, _event=None) -> None:
        if self._last_report is not None:
            self._render_summary(self._last_report)

    def _render_summary(self, report: UsageReport) -> None:
        now = datetime.now(BEIJING)
        selected_model = self.model_var.get()
        usage = usage_for_model(report, selected_model)
        cache_rate_value = usage.cached_input_tokens / usage.input_tokens if usage.input_tokens else 0.0
        cache_rate = f"{cache_rate_value:.1%}"
        unpriced_models = _unpriced_models_for_selection(report, selected_model)
        cost_suffix = "*" if unpriced_models else ""
        token_label = "今日总 Token" if selected_model == ALL_MODELS_LABEL else "今日模型 Token"
        self.summary.configure(state="normal")
        self.summary.delete("1.0", tk.END)
        self.summary.insert(tk.END, f"更新于 {now:%H:%M:%S}  ·  {now:%Y-%m-%d}\n", "label")
        self.summary.insert(tk.END, f"\n{token_label}\tAPI 参考估算\n", "label")
        self.summary.insert(tk.END, format_tokens(usage.total_tokens), "hero")
        self.summary.insert(tk.END, "\t")
        self.summary.insert(tk.END, f"${_cost_for_model(report, selected_model):,.4f}{cost_suffix}\n", "hero_cost")
        self.summary.insert(tk.END, "────────────────────────────────────\n", "divider")
        self.summary.insert(tk.END, "输入 Token\t缓存输入 Token\n", "label")
        self.summary.insert(
            tk.END,
            f"{format_tokens(usage.input_tokens)}\t{format_tokens(usage.cached_input_tokens)}\n",
            "value",
        )
        self.summary.insert(tk.END, "\n输出 Token\t缓存率\n", "label")
        self.summary.insert(
            tk.END,
            f"{format_tokens(usage.output_tokens)}\t{cache_rate}\n",
            "value",
        )
        for label, used_percent, reset_at in _quota_lines(report):
            used = "未知" if used_percent is None else f"{used_percent:.0f}%"
            reset = reset_at.strftime("%m-%d %H:%M") if reset_at else "未知"
            self.summary.insert(tk.END, f"\n{label}   {_quota_bar(used_percent)}  {used}\n", "accent")
            self.summary.insert(tk.END, f"下次重置 {reset}\n", "label")
        self.summary.insert(
            tk.END,
            f"扫描 {report.files_with_usage}/{report.sessions_scanned} 个会话  ·  价格核对 {PRICE_CHECKED_ON:%Y-%m-%d}\n",
            "label",
        )
        if unpriced_models:
            self.summary.insert(tk.END, f"* 未计价模型：{', '.join(unpriced_models)}\n", "error")
        if report.parse_errors:
            self.summary.insert(tk.END, f"日志警告：{report.parse_errors} 条记录未能解析\n", "error")
        self.summary.configure(state="disabled")

    def open_history(self) -> None:
        if self._history_window is not None and self._history_window.winfo_exists():
            self._history_window.deiconify()
            self._history_window.lift()
            self._history_window.focus_force()
            return
        self._history_window = HistoryWindow(self, self.sessions_root, self._last_report)


class HistoryWindow(tk.Toplevel):
    def __init__(self, parent: UsageDashboard, sessions_root: Path, current: UsageReport | None):
        super().__init__(parent)
        self.parent = parent
        self.title(f"{APP_DISPLAY_NAME} · 历史用量")
        self.geometry("900x650")
        self.minsize(720, 520)
        self.configure(bg=BG)
        self.transient(parent)
        self.sessions_root = sessions_root
        self.current = current
        self.queue = LatestResultQueue()
        self.days_var = tk.StringVar(value="最近 7 天")
        self.model_var = tk.StringVar(value=ALL_MODELS_LABEL)
        self._reports: list[UsageReport] = []
        self._poll_after: str | None = None
        self._figure: Any | None = None
        self._build_ui()
        self.after_idle(lambda: _set_native_titlebar_dark(self))
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.load_history()

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.configure("History.TFrame", background=BG)
        style.configure("HistorySurface.TFrame", background=PANEL)
        style.configure(
            "HistoryTitle.TLabel",
            background=BG,
            foreground=TEXT,
            font=(DISPLAY_FONT, 16, "bold"),
        )
        style.configure(
            "History.TCombobox",
            fieldbackground=CARD,
            background=CARD,
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=CARD,
            darkcolor=CARD,
            padding=(8, 5),
        )
        style.map(
            "History.TCombobox",
            fieldbackground=[("readonly", CARD)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", CARD)],
            selectforeground=[("readonly", TEXT)],
        )
        style.configure(
            "History.Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=PANEL,
            darkcolor=PANEL,
            rowheight=28,
            font=(UI_FONT, 9),
        )
        style.map(
            "History.Treeview",
            background=[("selected", "#35417d")],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "History.Treeview.Heading",
            background=CARD,
            foreground=MUTED,
            bordercolor=BORDER,
            relief="flat",
            font=(UI_FONT, 9, "bold"),
            padding=(7, 7),
        )
        style.map("History.Treeview.Heading", background=[("active", BORDER)])
        top = ttk.Frame(self, style="History.TFrame", padding=(16, 14, 16, 12))
        top.pack(fill="x")
        ttk.Label(top, text="历史用量", style="HistoryTitle.TLabel").pack(side="left")
        period = ttk.Combobox(
            top,
            textvariable=self.days_var,
            values=("最近 7 天", "最近 30 天", "最近重置以来"),
            state="readonly",
            width=16,
            style="History.TCombobox",
        )
        period.pack(side="right")
        period.bind("<<ComboboxSelected>>", lambda _event: self.load_history())
        self.model_filter = ttk.Combobox(
            top,
            textvariable=self.model_var,
            values=(ALL_MODELS_LABEL,),
            state="readonly",
            width=18,
            style="History.TCombobox",
        )
        self.model_filter.pack(side="right", padx=(0, 8))
        self.model_filter.bind("<<ComboboxSelected>>", self._on_model_selected)
        self.chart_frame = ttk.Frame(self, style="HistorySurface.TFrame", padding=1)
        self.chart_frame.pack(fill="both", expand=True, padx=16)
        columns = ("date", "total", "input", "cached", "output", "rate", "cost")
        table_frame = ttk.Frame(self, style="History.TFrame")
        table_frame.pack(fill="x", padx=16, pady=(10, 16))
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=9,
            selectmode="extended",
            style="History.Treeview",
        )
        headings = {
            "date": "日期",
            "total": "总 Token",
            "input": "输入",
            "cached": "缓存输入",
            "output": "输出",
            "rate": "缓存率",
            "cost": "美元等价",
        }
        widths = {
            "date": 120,
            "total": 110,
            "input": 110,
            "cached": 110,
            "output": 100,
            "rate": 80,
            "cost": 100,
        }
        for col in columns:
            self.table.heading(col, text=headings[col])
            self.table.column(col, width=widths[col], anchor="center", stretch=True)
        self.table.tag_configure("total", background=CARD, foreground=ACCENT, font=(UI_FONT, 9, "bold"))
        self.table.tag_configure("even", background="#131821")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.table.bind("<Control-c>", self._copy_selected_rows)

    def _history_start(self) -> date:
        today = datetime.now(BEIJING).date()
        if self.days_var.get() == "最近 30 天":
            return today - timedelta(days=29)
        current = self.parent._last_report or self.current
        if self.days_var.get() == "最近重置以来" and current:
            if current.weekly_reset_at and (
                current._weekly_rate_limit_observed_at is not None or current.five_hour_used_percent is None
            ):
                return (current.weekly_reset_at - timedelta(minutes=10_080)).date()
            if current.five_hour_reset_at:
                return (current.five_hour_reset_at - timedelta(minutes=300)).date()
            if current.weekly_reset_at:
                window = current.rate_limit_window_minutes or 10_080
                return (current.weekly_reset_at - timedelta(minutes=window)).date()
        return today - timedelta(days=6)

    def load_history(self) -> None:
        request_id = self.queue.begin()
        start = self._history_start()
        self._clear_chart()
        ttk.Label(self.chart_frame, text="正在读取历史日志…", foreground=MUTED, background=PANEL).pack(pady=30)
        threading.Thread(target=self._worker, args=(request_id, start), daemon=True).start()
        if self._poll_after is None:
            self._poll_after = self.after(50, self._poll_result)

    def _worker(self, request_id: int, start: date) -> None:
        try:
            result = WorkerResult(request_id, collect_history(self.sessions_root, start), None)
        except Exception as exc:
            result = WorkerResult(request_id, None, exc)
        self.queue.put(result)

    def _poll_result(self) -> None:
        self._poll_after = None
        result = self.queue.get_current_nowait()
        if result is None:
            self._poll_after = self.after(50, self._poll_result)
            return
        if result.error is not None:
            self._clear_chart()
            ttk.Label(
                self.chart_frame,
                text=f"历史读取失败：{result.error}\n请切换周期或重新打开窗口后重试。",
                foreground=ERROR,
                background=PANEL,
                justify="center",
            ).pack(pady=30)
            return
        reports = result.value
        if isinstance(reports, list):
            self._reports = reports
            options = model_options(reports)
            self.model_filter.configure(values=options)
            if self.model_var.get() not in options:
                self.model_var.set(ALL_MODELS_LABEL)
            self._render_history(reports)

    def _clear_chart(self) -> None:
        if self._figure is not None:
            self._figure.clear()
            self._figure = None
        for child in self.chart_frame.winfo_children():
            child.destroy()

    def _on_model_selected(self, _event=None) -> None:
        if self._reports:
            self._render_history(self._reports)

    def _render_history(self, reports: list[UsageReport]) -> None:
        self._clear_chart()
        selected_model = self.model_var.get()
        usages = [usage_for_model(report, selected_model) for report in reports]
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure

            fig = Figure(figsize=(8.3, 3.0), dpi=95, facecolor=PANEL)
            self._figure = fig
            ax = fig.add_subplot(111, facecolor=PANEL)
            labels = [report.day.strftime("%m-%d") for report in reports]
            costs = [_cost_for_model(report, selected_model) for report in reports]
            tokens = [usage.total_tokens / 1_000_000 for usage in usages]
            x_values = list(range(len(reports)))
            ax.bar(x_values, costs, color="#343b4c", alpha=0.95, width=0.72)
            ax.set_ylabel("USD", color=SUBTLE)
            ax.tick_params(colors=MUTED, labelsize=8)
            positions = tick_positions(len(labels))
            ax.set_xticks(
                positions,
                [labels[index] for index in positions],
                rotation=30,
                ha="right",
            )
            ax.spines[:].set_color(BORDER)
            ax.grid(axis="y", color=BORDER, alpha=0.55, linewidth=0.7)
            ax.set_axisbelow(True)
            ax2 = ax.twinx()
            ax2.plot(x_values, tokens, color=ACCENT, marker="o", markersize=3.5, linewidth=1.8)
            ax2.set_ylabel("Million tokens", color=MUTED)
            ax2.tick_params(colors=MUTED, labelsize=8)
            ax2.spines[:].set_color(BORDER)
            fig.tight_layout()
            canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)
        except Exception as exc:
            ttk.Label(
                self.chart_frame,
                text=f"图表加载失败：{exc}",
                foreground=ERROR,
                background=PANEL,
            ).pack(pady=30)

        for item in self.table.get_children():
            self.table.delete(item)
        total_input = sum(usage.input_tokens for usage in usages)
        total_cached = sum(usage.cached_input_tokens for usage in usages)
        total_output = sum(usage.output_tokens for usage in usages)
        total_tokens = sum(usage.total_tokens for usage in usages)
        total_cost = sum(_cost_for_model(report, selected_model) for report in reports)
        total_rate = total_cached / total_input if total_input else 0.0
        partial = any(_unpriced_models_for_selection(report, selected_model) for report in reports)
        suffix = "*" if partial else ""
        self.table.insert(
            "",
            "end",
            values=(
                f"合计（{len(reports)}天）",
                format_tokens(total_tokens),
                format_tokens(total_input),
                format_tokens(total_cached),
                format_tokens(total_output),
                f"{total_rate:.1%}",
                f"${total_cost:,.4f}{suffix}",
            ),
            tags=("total",),
        )
        for index, (report, usage) in enumerate(reversed(list(zip(reports, usages, strict=True)))):
            cache_rate = usage.cached_input_tokens / usage.input_tokens if usage.input_tokens else 0.0
            partial = bool(_unpriced_models_for_selection(report, selected_model))
            self.table.insert(
                "",
                "end",
                values=(
                    report.day.strftime("%Y-%m-%d"),
                    format_tokens(usage.total_tokens),
                    format_tokens(usage.input_tokens),
                    format_tokens(usage.cached_input_tokens),
                    format_tokens(usage.output_tokens),
                    f"{cache_rate:.1%}",
                    f"${_cost_for_model(report, selected_model):,.4f}{'*' if partial else ''}",
                ),
                tags=("even",) if index % 2 else (),
            )

    def _copy_selected_rows(self, _event=None):
        selected = self.table.selection()
        if not selected:
            return "break"
        lines = ["\t".join(str(value) for value in self.table.item(item, "values")) for item in selected]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        return "break"

    def _close(self) -> None:
        if self._poll_after is not None:
            self.after_cancel(self._poll_after)
            self._poll_after = None
        self.parent._history_window = None
        self.destroy()


def main() -> None:
    if not _acquire_single_instance():
        return
    dashboard = UsageDashboard()
    dashboard._setup_tray()
    dashboard.mainloop()


if __name__ == "__main__":
    main()
