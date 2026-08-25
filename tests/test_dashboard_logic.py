import queue
from datetime import date
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
from usage_core import ModelUsage, UsageReport


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


def test_chart_tick_positions_stay_readable_for_thirty_days():
    positions = tick_positions(30, max_ticks=7)

    assert positions[0] == 0
    assert positions[-1] == 29
    assert len(positions) <= 7


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
