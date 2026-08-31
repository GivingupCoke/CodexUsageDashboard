import ctypes
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import codex_usage_dashboard as dashboard
from usage_core import BEIJING, ModelUsage, UsageReport


def create_dashboard():
    """Retry only known transient Tcl initialization failures."""
    max_attempts = 4
    for attempt in range(max_attempts):
        try:
            return dashboard.UsageDashboard()
        except tk.TclError as exc:
            transient_errors = (
                "Can't find a usable tk.tcl",
                "Can't find a usable init.tcl",
                "couldn't read file",
                'invalid command name "tcl_findLibrary"',
            )
            if attempt == max_attempts - 1 or not any(message in str(exc) for message in transient_errors):
                raise
            time.sleep(0.05)
    raise AssertionError("unreachable")


def pump_until(root, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("UI condition was not reached before timeout")


def make_report(day=None, *, unknown=False, parse_errors=0):
    day = day or datetime.now(BEIJING).date()
    known = ModelUsage(
        input_tokens=1_000,
        cached_input_tokens=600,
        output_tokens=100,
        reasoning_output_tokens=20,
        estimated_cost_usd=0.004,
    )
    models = {"gpt-5.6-sol": known}
    if unknown:
        models["stealth/ox-alpha"] = ModelUsage(input_tokens=50, output_tokens=5)
    report = UsageReport(
        day=day,
        input_tokens=sum(value.input_tokens for value in models.values()),
        cached_input_tokens=sum(value.cached_input_tokens for value in models.values()),
        output_tokens=sum(value.output_tokens for value in models.values()),
        reasoning_output_tokens=sum(value.reasoning_output_tokens for value in models.values()),
        by_model=models,
        weekly_used_percent=49,
        weekly_reset_at=datetime.now(BEIJING) + timedelta(days=3),
        rate_limit_window_minutes=10_080,
        sessions_scanned=4,
        files_with_usage=3,
        parse_errors=parse_errors,
    )
    return report


def test_dashboard_and_history_user_flow(monkeypatch):
    current = make_report(unknown=True, parse_errors=2)
    monkeypatch.setattr(dashboard, "collect_usage", lambda *_args, **_kwargs: current)

    def history(_root, start):
        today = datetime.now(BEIJING).date()
        return [
            make_report(start + timedelta(days=index), unknown=index == 0) for index in range((today - start).days + 1)
        ]

    monkeypatch.setattr(dashboard, "collect_history", history)
    root = create_dashboard()
    root.withdraw()
    try:
        pump_until(root, lambda: root._last_report is current)
        summary = root.summary.get("1.0", "end")
        assert "API 参考估算" in summary
        assert "未计价模型：stealth/ox-alpha" in summary
        assert "日志警告：2 条记录" in summary
        assert str(current.weekly_used_percent) in summary
        assert str(dashboard.PRICE_CHECKED_ON.year) in summary
        assert tuple(root.model_filter.cget("values")) == (
            dashboard.ALL_MODELS_LABEL,
            "gpt-5.6-sol",
            "stealth/ox-alpha",
        )

        root.model_var.set("stealth/ox-alpha")
        root._on_model_selected()
        summary = root.summary.get("1.0", "end")
        assert "今日模型 Token" in summary
        assert "55" in summary
        assert "$0.0000*" in summary
        assert "一周额度" in summary

        root.model_var.set("gpt-5.6-sol")
        root._on_model_selected()
        assert "$0.0040" in root.summary.get("1.0", "end")

        dual_quota = make_report()
        dual_quota.five_hour_used_percent = 24
        dual_quota.five_hour_reset_at = datetime.now(BEIJING) + timedelta(hours=2)
        dual_quota._weekly_rate_limit_observed_at = datetime.now(BEIJING)
        root._render_summary(dual_quota)
        dual_summary = root.summary.get("1.0", "end")
        assert "5 小时额度" in dual_summary
        assert "一周额度" in dual_summary

        root.model_var.set("stealth/ox-alpha")
        root._sync_model_options(make_report())
        assert root.model_var.get() == dashboard.ALL_MODELS_LABEL

        no_quota = make_report()
        no_quota.weekly_used_percent = None
        root._render_summary(no_quota)
        assert "未知" in root.summary.get("1.0", "end")
        assert len(root._quota_bars) == 2
        assert all(not canvas.find_withtag("fill") for canvas in root._quota_bars)

        root.collapse_button.invoke()
        root.update()
        assert root.state() == "withdrawn"
        assert root._orb_visible()
        root._orb.open_main()
        root.update()
        assert root.state() != "withdrawn"
        assert not root._orb_visible()
        root._topmost.set(False)
        root._toggle_topmost()

        root.open_history()
        history_window = root._history_window
        assert history_window is not None
        assert history_window.title() == "Codex Usage v1.1 · 历史用量"
        history_window.withdraw()
        pump_until(root, lambda: len(history_window.table.get_children()) == 8)
        assert len(history_window.chart_frame.winfo_children()) == 1
        assert str(history_window.table.cget("style")) == "History.Treeview"
        assert tuple(history_window.model_filter.cget("values")) == (
            dashboard.ALL_MODELS_LABEL,
            "gpt-5.6-sol",
            "stealth/ox-alpha",
        )

        history_window.model_var.set("stealth/ox-alpha")
        history_window._on_model_selected()
        filtered_rows = history_window.table.get_children()
        filtered_total = history_window.table.item(filtered_rows[0], "values")
        assert filtered_total[1] == "55"
        assert filtered_total[-1] == "$0.0000*"

        history_window.model_var.set("removed-model")
        request_id = history_window.queue.begin()
        history_window.queue.put(dashboard.WorkerResult(request_id, [make_report()], None))
        history_window._poll_result()
        assert history_window.model_var.get() == dashboard.ALL_MODELS_LABEL

        root.open_history()
        assert root._history_window is history_window

        rows = history_window.table.get_children()
        history_window.table.selection_set(rows[:2])
        assert history_window._copy_selected_rows() == "break"
        assert "合计" in history_window.clipboard_get()

        history_window.days_var.set("最近 30 天")
        history_window.load_history()
        pump_until(root, lambda: len(history_window.table.get_children()) == 31)

        history_window.days_var.set("最近重置以来")
        assert history_window._history_start() <= date.today()
        history_window._close()
        assert root._history_window is None

        def fail_usage(*_args, **_kwargs):
            raise OSError("usage unavailable")

        monkeypatch.setattr(dashboard, "collect_usage", fail_usage)
        root.refresh()
        pump_until(root, lambda: "读取失败" in root.summary.get("1.0", "end"))
        assert str(root.refresh_button.cget("state")) == "normal"

        monkeypatch.setattr(dashboard, "collect_usage", lambda *_args, **_kwargs: make_report())
        root.refresh()
        assert root.refresh_button.cget("bg") == dashboard.BORDER
        root._set_action_button_background(root.refresh_button, dashboard.ACCENT_HOVER)
        assert root.refresh_button.cget("bg") == dashboard.BORDER
        root.refresh()
        pump_until(root, lambda: str(root.refresh_button.cget("state")) == "normal")
        assert root.refresh_button.cget("bg") == dashboard.ACCENT

        def fail_history(*_args, **_kwargs):
            raise ValueError("history unavailable")

        monkeypatch.setattr(dashboard, "collect_history", fail_history)
        root.open_history()
        history_window = root._history_window
        assert history_window is not None
        history_window.withdraw()
        pump_until(
            root,
            lambda: any("历史读取失败" in child.cget("text") for child in history_window.chart_frame.winfo_children()),
        )
        assert history_window._copy_selected_rows() == "break"
        history_window._close()
    finally:
        root.destroy()


def test_quota_orb_lifecycle_and_rings(monkeypatch):
    current = make_report()
    current.five_hour_used_percent = 40
    monkeypatch.setattr(dashboard, "collect_usage", lambda *_args, **_kwargs: current)
    root = create_dashboard()
    root.withdraw()
    try:
        pump_until(root, lambda: root._last_report is current)
        assert root._orb is None
        assert not root._orb_visible()

        root.collapse_button.invoke()
        root.update()
        orb = root._orb
        assert orb is not None
        assert root._orb_visible()
        assert root.state() == "withdrawn"
        assert dashboard.QuotaOrb.SIZE == 120

        assert len(orb.canvas.find_withtag("orb_art")) == 1
        assert orb.canvas.itemcget("weekly_value", "text") == "49%"
        assert orb.canvas.itemcget("weekly_label", "text") == "WEEK"
        assert orb.canvas.itemcget("five_hour_value", "text") == "5H 40%"
        orb.update_report(current)
        assert len(orb.canvas.find_withtag("orb_art")) == 1

        unknown = make_report()
        unknown.weekly_used_percent = None
        unknown.five_hour_used_percent = None
        orb.update_report(unknown)
        assert orb.canvas.itemcget("weekly_value", "text") == "--"
        assert orb.canvas.itemcget("five_hour_value", "text") == "5H --"

        orb.open_main()
        root.update()
        assert root.state() != "withdrawn"
        assert not root._orb_visible()

        root.close_orb()
        assert root._orb is None
        assert not root._orb_visible()

        # 悬浮球开启时刷新数据会同步更新球面
        root.collapse_button.invoke()
        root.update()
        updated = make_report()
        updated.weekly_used_percent = 88
        root._poll_refresh_result.__self__._orb.update_report(updated)
        assert root._orb._report is updated
        assert root._orb.canvas.itemcget("weekly_value", "text") == "88%"
        root.close_orb()
    finally:
        root.destroy()


def test_custom_titlebar_and_compact_dashboard_hierarchy(monkeypatch):
    current = make_report()
    monkeypatch.setattr(dashboard, "collect_usage", lambda *_args, **_kwargs: current)
    root = create_dashboard()
    root.withdraw()
    try:
        pump_until(root, lambda: root._last_report is current)

        assert dashboard.APP_VERSION == "1.1"
        assert root.title() == "Codex Usage v1.1 · 今日用量"
        assert root.app_title_label.cget("text") == "Codex Usage v1.1"
        assert root.geometry().split("+", 1)[0] == dashboard.MAIN_WINDOW_GEOMETRY
        assert root.minsize() == (dashboard.MAIN_WINDOW_MIN_WIDTH, dashboard.MAIN_WINDOW_MIN_HEIGHT)
        root.update_idletasks()
        window_bottom = root.winfo_rooty() + root.winfo_height()
        for button in (root.history_button, root.refresh_button):
            assert button.winfo_rooty() + button.winfo_height() <= window_bottom

        caption_buttons = root.caption_controls.pack_slaves()
        assert caption_buttons == [
            root.collapse_button,
            root.pin_button,
            root.minimize_button,
            root.maximize_button,
            root.close_button,
        ]
        assert root.pin_button.master is root.caption_controls
        assert root.pin_button.cget("text") == dashboard.PIN_ICON
        assert root.pin_button.cget("bg") == dashboard.ACCENT
        assert root.history_button.cget("text") == "历史记录"
        assert root.refresh_button.cget("text") == "刷新"
        assert not hasattr(root, "orb_button")
        assert not hasattr(root, "_collapsed")
        assert root.history_button.cget("fg") == "#ffffff"
        assert root.history_button.cget("bg") == dashboard.ACCENT
        assert root.refresh_button.cget("fg") == "#ffffff"
        assert root.history_button.bind("<Enter>")
        assert root.history_button.bind("<Leave>")
        assert root.history_button.bind("<ButtonPress-1>")
        assert root.refresh_button.bind("<Enter>")
        assert root.refresh_button.bind("<Leave>")
        assert root.refresh_button.bind("<ButtonPress-1>")

        root._set_action_button_background(root.history_button, dashboard.ACCENT_HOVER)
        assert root.history_button.cget("bg") == dashboard.ACCENT_HOVER
        root._set_action_button_background(root.history_button, dashboard.ACCENT_PRESSED_BG)
        assert root.history_button.cget("bg") == dashboard.ACCENT_PRESSED_BG
        root._set_action_button_background(root.history_button, dashboard.ACCENT)
        assert root.history_button.cget("bg") == dashboard.ACCENT

        root._set_action_button_background(root.refresh_button, dashboard.ACCENT_HOVER)
        assert root.refresh_button.cget("bg") == dashboard.ACCENT_HOVER
        root._set_action_button_background(root.refresh_button, dashboard.ACCENT_PRESSED_BG)
        assert root.refresh_button.cget("bg") == dashboard.ACCENT_PRESSED_BG
        root._set_action_button_background(root.refresh_button, dashboard.ACCENT_HOVER)
        assert root.refresh_button.cget("bg") == dashboard.ACCENT_HOVER
        root._set_action_button_background(root.refresh_button, dashboard.ACCENT)
        assert root.refresh_button.cget("bg") == dashboard.ACCENT
        root._update_tray_status(make_report(unknown=True))
        assert "今日总 Token" in root._tray_status
        assert "API 参考估算" in root._tray_status
        assert "输入 Token" in root._tray_status
        assert "输出 Token" in root._tray_status
        assert "缓存率" in root._tray_status
        assert "5 小时额度" in root._tray_status
        assert "一周额度" in root._tray_status
        assert "未计价：stealth/ox-alpha" in root._tray_status
        assert len(root._tray_status_lines) == 8
        assert len(root._tray_tooltip) <= 127

        root.pin_button.invoke()
        assert root._topmost.get() is False
        assert root.pin_button.cget("bg") == dashboard.TITLE_BG
        root.pin_button.invoke()
        assert root._topmost.get() is True

        assert root.minimize_button.bind("<Enter>")
        assert root.minimize_button.bind("<Motion>")
        assert root.minimize_button.cget("activebackground") == dashboard.CAPTION_HOVER_BG
        assert root.maximize_button.bind("<Enter>")
        assert root.maximize_button.bind("<Motion>")
        assert root.maximize_button.cget("activebackground") == dashboard.CAPTION_HOVER_BG

        summary = root.summary.get("1.0", "end")
        assert "今日总 Token" in summary
        assert "API 参考估算" in summary
        assert "一周额度" in summary
        assert len(root._quota_bars) == 2
        weekly_bar = root._quota_bars[1]
        weekly_fills = weekly_bar.find_withtag("fill")
        assert len(weekly_fills) == 1
        assert weekly_bar.itemcget(weekly_fills[0], "fill") == dashboard.ACCENT

        assert root._maximized is False
        root._toggle_maximize()
        assert root._maximized is True
        assert root.maximize_button.cget("text") == dashboard.RESTORE_ICON
        root._toggle_maximize()
        assert root._maximized is False
        assert root.maximize_button.cget("text") == dashboard.MAXIMIZE_ICON

        root.collapse_button.invoke()
        root.update()
        assert root.state() == "withdrawn"
        assert root._orb_visible()
        root._orb.open_main()
        root.update()
        assert root.state() != "withdrawn"
        assert not root._orb_visible()

        root._tray_icon = object()
        root.close_button.invoke()
        assert root.state() == "withdrawn"
        root._show_main_window()
        assert root.state() != "withdrawn"
        root._tray_icon = None
        root._setup_tray = lambda: None
        root._window_handle = None
        root.close_button.invoke()
        assert root.state() == "iconic"
    finally:
        root.destroy()


def test_windows_titlebar_drag_posts_native_move_command(monkeypatch):
    root = create_dashboard()
    root.withdraw()
    calls = []

    class FakeFunction:
        def __init__(self, name):
            self.name = name
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            calls.append((self.name, *args))
            return True

    class FakeUser32:
        def __init__(self):
            self.ReleaseCapture = FakeFunction("ReleaseCapture")
            self.PostMessageW = FakeFunction("PostMessageW")

    user32 = FakeUser32()
    monkeypatch.setattr(dashboard.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32))
    root._window_handle = 1234
    event = SimpleNamespace(x_root=100, y_root=100)
    try:
        assert root._start_drag(event) == "break"
        assert calls == [
            ("ReleaseCapture",),
            ("PostMessageW", 1234, dashboard.WM_SYSCOMMAND, dashboard.SC_MOVE | dashboard.HTCAPTION, 0),
        ]
        assert user32.ReleaseCapture.argtypes == []
        assert user32.ReleaseCapture.restype is ctypes.c_bool
        assert user32.PostMessageW.argtypes == [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        assert user32.PostMessageW.restype is ctypes.c_bool
        assert root._drag_origin is None
    finally:
        root.destroy()
