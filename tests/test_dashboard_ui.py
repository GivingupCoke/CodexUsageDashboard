import ctypes
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import codex_usage_dashboard as dashboard
from usage_core import BEIJING, ModelUsage, UsageReport


def create_dashboard():
    """Retry only the known transient second-interpreter Tcl initialization failure."""
    for attempt in range(2):
        try:
            return dashboard.UsageDashboard()
        except tk.TclError as exc:
            transient_errors = ("Can't find a usable tk.tcl", 'invalid command name "tcl_findLibrary"')
            if attempt or not any(message in str(exc) for message in transient_errors):
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
        assert "周额度（全局）" in summary

        root.model_var.set("gpt-5.6-sol")
        root._on_model_selected()
        assert "$0.0040" in root.summary.get("1.0", "end")

        root.model_var.set("stealth/ox-alpha")
        root._sync_model_options(make_report())
        assert root.model_var.get() == dashboard.ALL_MODELS_LABEL

        no_quota = make_report()
        no_quota.weekly_used_percent = None
        root._render_summary(no_quota)
        assert "░░░░░░░░░░" in root.summary.get("1.0", "end")

        root.toggle_collapsed()
        assert root._collapsed is True
        root.toggle_collapsed()
        assert root._collapsed is False
        root._topmost.set(False)
        root._toggle_topmost()

        root.open_history()
        history_window = root._history_window
        assert history_window is not None
        assert history_window.title() == "Codex Usage v1.0 · 历史用量"
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
        root.refresh()
        pump_until(root, lambda: root._last_report is not None)

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


def test_custom_titlebar_and_compact_dashboard_hierarchy(monkeypatch):
    current = make_report()
    monkeypatch.setattr(dashboard, "collect_usage", lambda *_args, **_kwargs: current)
    root = create_dashboard()
    root.withdraw()
    try:
        pump_until(root, lambda: root._last_report is current)

        assert dashboard.APP_VERSION == "1.0"
        assert root.title() == "Codex Usage v1.0 · 今日用量"
        assert root.app_title_label.cget("text") == "Codex Usage v1.0"

        caption_buttons = root.caption_controls.pack_slaves()
        assert caption_buttons == [
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
        assert root.history_button.cget("fg") == dashboard.TEXT
        assert root.refresh_button.cget("fg") == "#ffffff"
        root._update_tray_status(make_report(unknown=True))
        assert "今日总 Token" in root._tray_status
        assert "API 参考估算" in root._tray_status
        assert "输入 Token" in root._tray_status
        assert "输出 Token" in root._tray_status
        assert "缓存率" in root._tray_status
        assert "周额度" in root._tray_status
        assert "未计价：stealth/ox-alpha" in root._tray_status
        assert len(root._tray_status_lines) == 7

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
        assert "周额度" in summary
        assert "█" in summary

        assert root._maximized is False
        root._toggle_maximize()
        assert root._maximized is True
        assert root.maximize_button.cget("text") == dashboard.RESTORE_ICON
        root._toggle_maximize()
        assert root._maximized is False
        assert root.maximize_button.cget("text") == dashboard.MAXIMIZE_ICON

        root.toggle_collapsed()
        assert root._collapsed is True
        assert root.collapse_button.cget("text") == dashboard.EXPAND_ICON
        root.toggle_collapsed()
        assert root._collapsed is False
        assert root.collapse_button.cget("text") == dashboard.COLLAPSE_ICON

        root._tray_icon = object()
        root.close_button.invoke()
        assert root.state() == "withdrawn"
        root._show_main_window()
        assert root.state() != "withdrawn"
        root._tray_icon = None
    finally:
        root.destroy()


def test_windows_titlebar_drag_uses_native_move_loop(monkeypatch):
    root = create_dashboard()
    root.withdraw()
    calls = []

    class FakeUser32:
        def ReleaseCapture(self):
            calls.append(("ReleaseCapture",))

        def SendMessageW(self, handle, message, hit_test, parameter):
            calls.append(("SendMessageW", handle, message, hit_test, parameter))

    monkeypatch.setattr(dashboard.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=FakeUser32()))
    root._window_handle = 1234
    event = SimpleNamespace(x_root=100, y_root=100)
    try:
        assert root._start_drag(event) == "break"
        assert calls == [
            ("ReleaseCapture",),
            ("SendMessageW", 1234, dashboard.WM_NCLBUTTONDOWN, dashboard.HTCAPTION, 0),
        ]
        assert root._drag_origin is None
    finally:
        root.destroy()
