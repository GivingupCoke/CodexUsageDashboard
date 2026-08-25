import queue
from datetime import date, datetime
from types import SimpleNamespace

import codex_usage_dashboard as dashboard
from codex_usage_dashboard import (
    ALL_MODELS_LABEL,
    HistoryWindow,
    LatestResultQueue,
    WorkerResult,
    model_options,
    usage_for_model,
    tick_positions,
)
from usage_core import BEIJING, ModelUsage, UsageReport


def test_latest_result_queue_discards_stale_results():
    results = LatestResultQueue()
    old_request = results.begin()
    current_request = results.begin()
    results.put(WorkerResult(old_request, "old", None))
    results.put(WorkerResult(current_request, "new", None))

    result = results.get_current_nowait()

    assert result is not None
    assert result.value == "new"


def test_latest_result_queue_waits_when_only_stale_result_exists():
    results = LatestResultQueue()
    old_request = results.begin()
    results.begin()
    results.put(WorkerResult(old_request, "old", None))

    assert results.get_current_nowait() is None


def test_history_worker_returns_exceptions_to_the_ui(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise ValueError("bad log")

    monkeypatch.setattr(dashboard, "collect_history", fail)
    fake_window = SimpleNamespace(queue=queue.Queue(), sessions_root=tmp_path)

    HistoryWindow._worker(fake_window, 7, date(2026, 8, 18))
    result = fake_window.queue.get_nowait()

    assert result.request_id == 7
    assert result.value is None
    assert isinstance(result.error, ValueError)


def test_scheduled_refresh_runs_refresh_and_schedules_next_cycle():
    calls = []
    fake_dashboard = SimpleNamespace(
        refresh=lambda: calls.append("refresh"),
        after=lambda delay, callback: calls.append((delay, callback)),
    )
    fake_dashboard._scheduled_refresh = dashboard.UsageDashboard._scheduled_refresh.__get__(fake_dashboard)

    dashboard.UsageDashboard._scheduled_refresh(fake_dashboard)

    assert calls == ["refresh", (60_000, fake_dashboard._scheduled_refresh)]


def test_empty_async_polls_schedule_another_check():
    scheduled = []
    empty_results = SimpleNamespace(get_current_nowait=lambda: None)
    fake_dashboard = SimpleNamespace(
        _refresh_poll_after="old",
        _refresh_results=empty_results,
        after=lambda delay, callback: scheduled.append((delay, callback)) or "main-poll",
    )
    fake_dashboard._poll_refresh_result = dashboard.UsageDashboard._poll_refresh_result.__get__(fake_dashboard)
    fake_history = SimpleNamespace(
        _poll_after="old",
        queue=empty_results,
        after=lambda delay, callback: scheduled.append((delay, callback)) or "history-poll",
    )
    fake_history._poll_result = HistoryWindow._poll_result.__get__(fake_history)

    dashboard.UsageDashboard._poll_refresh_result(fake_dashboard)
    HistoryWindow._poll_result(fake_history)

    assert fake_dashboard._refresh_poll_after == "main-poll"
    assert fake_history._poll_after == "history-poll"
    assert [delay for delay, _callback in scheduled] == [50, 50]


def test_model_callbacks_do_nothing_before_reports_are_loaded():
    dashboard.UsageDashboard._on_model_selected(SimpleNamespace(_last_report=None))
    HistoryWindow._on_model_selected(SimpleNamespace(_reports=[]))


def test_chart_tick_positions_stay_readable_for_thirty_days():
    positions = tick_positions(30, max_ticks=7)

    assert positions[0] == 0
    assert positions[-1] == 29
    assert len(positions) <= 7


def test_chart_tick_positions_handle_empty_and_single_tick_ranges():
    assert tick_positions(0) == []
    assert tick_positions(5, max_ticks=1) == [4]


def test_rate_limit_labels_cover_weekly_hourly_and_generic_windows():
    assert dashboard._rate_limit_label(10_080) == "周额度"
    assert dashboard._rate_limit_label(300) == "5 小时额度"
    assert dashboard._rate_limit_label(90) == "额度"


def test_quota_lines_show_both_plus_windows():
    report = UsageReport(
        weekly_used_percent=61,
        weekly_reset_at=datetime(2026, 8, 31, tzinfo=BEIJING),
        five_hour_used_percent=24,
        five_hour_reset_at=datetime(2026, 8, 25, 1, tzinfo=BEIJING),
        rate_limit_window_minutes=300,
    )
    report._weekly_rate_limit_observed_at = datetime(2026, 8, 24, tzinfo=BEIJING)

    assert [line[0] for line in dashboard._quota_lines(report)] == ["5 小时额度（全局）", "一周额度（全局）"]


def test_quota_lines_do_not_treat_a_five_hour_primary_window_as_weekly():
    report = UsageReport(
        weekly_used_percent=24,
        weekly_reset_at=datetime(2026, 8, 25, 1, tzinfo=BEIJING),
        five_hour_used_percent=24,
        five_hour_reset_at=datetime(2026, 8, 25, 1, tzinfo=BEIJING),
        rate_limit_window_minutes=300,
    )

    five_hour, weekly = dashboard._quota_lines(report)

    assert five_hour[1] == 24
    assert weekly[1] is None


def test_model_options_are_unique_and_sorted_by_total_usage():
    first = UsageReport(
        by_model={
            "gpt-5.6-sol": ModelUsage(input_tokens=100, output_tokens=10),
            "gpt-5.6-luna": ModelUsage(input_tokens=300, output_tokens=20),
        }
    )
    second = UsageReport(
        by_model={
            "gpt-5.6-sol": ModelUsage(input_tokens=50, output_tokens=5),
            "stealth/ox-alpha": ModelUsage(input_tokens=200, output_tokens=10),
        }
    )

    assert model_options([first, second]) == (
        ALL_MODELS_LABEL,
        "gpt-5.6-luna",
        "stealth/ox-alpha",
        "gpt-5.6-sol",
    )


def test_usage_for_model_returns_selected_usage_or_empty_usage():
    selected = ModelUsage(input_tokens=300, cached_input_tokens=200, output_tokens=20)
    report = UsageReport(
        input_tokens=400,
        cached_input_tokens=250,
        output_tokens=30,
        by_model={"gpt-5.6-luna": selected},
    )

    assert usage_for_model(report, ALL_MODELS_LABEL) is report
    assert usage_for_model(report, "gpt-5.6-luna") is selected
    assert usage_for_model(report, "missing").total_tokens == 0


def test_model_cost_and_unpriced_state_follow_the_selection():
    known = ModelUsage(input_tokens=100, output_tokens=10, estimated_cost_usd=0.75)
    unknown = ModelUsage(input_tokens=20, output_tokens=5)
    report = UsageReport(by_model={"gpt-5.6-sol": known, "stealth/ox-alpha": unknown})

    assert dashboard._cost_for_model(report, "gpt-5.6-sol") == 0.75
    assert dashboard._unpriced_models_for_selection(report, "gpt-5.6-sol") == ()
    assert dashboard._unpriced_models_for_selection(report, "stealth/ox-alpha") == ("stealth/ox-alpha",)
    assert dashboard._unpriced_models_for_selection(report, "missing") == ()
