import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import usage_core
from usage_core import (
    PRICE_CHECKED_ON,
    clear_usage_cache,
    collect_history,
    collect_usage,
    estimate_cost_usd,
    format_tokens,
)


@pytest.fixture(autouse=True)
def isolated_usage_cache():
    clear_usage_cache()
    yield
    clear_usage_cache()


def event(ts, kind, payload):
    return {"timestamp": ts, "type": kind, "payload": payload}


def token_event(
    ts,
    total,
    cached,
    output,
    *,
    cache_write=0,
    reasoning=0,
    rate_limits=None,
):
    payload = {
        "type": "token_count",
        "info": {
            "total_token_usage": {
                "input_tokens": total,
                "cached_input_tokens": cached,
                "cache_write_input_tokens": cache_write,
                "output_tokens": output,
                "reasoning_output_tokens": reasoning,
                "total_tokens": total + output,
            },
            "last_token_usage": {},
        },
    }
    if rate_limits is not None:
        payload["rate_limits"] = rate_limits
    return event(ts, "event_msg", payload)


def write_session(root: Path, rows, name="rollout.jsonl") -> Path:
    session = root / "2026" / "08" / "24" / name
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return session


def test_collects_beijing_calendar_day_and_deduplicates_snapshots(tmp_path: Path):
    rows = [
        event("2026-08-23T15:59:59.000Z", "turn_context", {"model": "gpt-5.6-sol"}),
        token_event("2026-08-23T15:59:59.100Z", 100, 50, 10),
        token_event("2026-08-24T00:00:01.000Z", 300, 200, 30),
        token_event("2026-08-24T00:00:02.000Z", 300, 200, 30),
        event("2026-08-24T01:00:00.000Z", "turn_context", {"model": "gpt-5.6-luna"}),
        token_event("2026-08-24T01:00:01.000Z", 500, 300, 50),
    ]
    write_session(tmp_path, rows)

    result = collect_usage(tmp_path, datetime(2026, 8, 24, tzinfo=timezone.utc))

    assert result.input_tokens == 400
    assert result.cached_input_tokens == 250
    assert result.output_tokens == 40
    assert result.cache_rate == 250 / 400
    assert result.total_tokens == 440
    assert result.by_model["gpt-5.6-sol"].total_tokens == 220
    assert result.by_model["gpt-5.6-luna"].total_tokens == 220


def test_uses_current_official_base_prices_and_cache_write_surcharge():
    regular = {
        "input_tokens": 100_000,
        "cached_input_tokens": 20_000,
        "cache_write_input_tokens": 10_000,
        "output_tokens": 10_000,
        "reasoning_output_tokens": 2_000,
    }
    long_context = {
        **regular,
        "input_tokens": 300_000,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
    }

    assert PRICE_CHECKED_ON == date(2026, 8, 24)
    assert estimate_cost_usd("gpt-5.6-sol", regular) == pytest.approx(0.538)
    assert estimate_cost_usd("gpt-5.6-sol", long_context) == pytest.approx(2.7)
    assert estimate_cost_usd("stealth/ox-alpha", regular) is None


def test_unknown_models_are_reported_instead_of_silently_priced(tmp_path: Path):
    write_session(
        tmp_path,
        [
            event("2026-08-24T00:00:00Z", "turn_context", {"model": "stealth/ox-alpha"}),
            token_event("2026-08-24T00:00:01Z", 100, 50, 10),
        ],
    )

    result = collect_usage(tmp_path, date(2026, 8, 24))

    assert result.cost_usd == 0.0
    assert result.cost_is_partial is True
    assert result.unpriced_models == ("stealth/ox-alpha",)


def test_malformed_usage_is_counted_without_aborting_collection(tmp_path: Path):
    bad = token_event("2026-08-24T00:00:01Z", 100, 0, 0)
    bad["payload"]["info"]["total_token_usage"]["input_tokens"] = "bad"
    write_session(tmp_path, [bad])

    result = collect_usage(tmp_path, date(2026, 8, 24))

    assert result.total_tokens == 0
    assert result.parse_errors == 1


def test_partial_last_line_is_retried_after_append(tmp_path: Path):
    session = write_session(
        tmp_path,
        [
            event("2026-08-24T00:00:00Z", "turn_context", {"model": "gpt-5.6-sol"}),
            token_event("2026-08-24T00:00:01Z", 100, 50, 10),
        ],
    )
    next_line = json.dumps(token_event("2026-08-24T00:01:01Z", 160, 80, 20))
    split = len(next_line) // 2
    with session.open("a", encoding="utf-8") as handle:
        handle.write(next_line[:split])

    first = collect_usage(tmp_path, date(2026, 8, 24))
    assert first.total_tokens == 110
    assert first.parse_errors == 0

    with session.open("a", encoding="utf-8") as handle:
        handle.write(next_line[split:] + "\n")

    second = collect_usage(tmp_path, date(2026, 8, 24))
    assert second.input_tokens == 160
    assert second.output_tokens == 20
    assert second.parse_errors == 0


def test_unchanged_sessions_reuse_the_parse_cache(tmp_path: Path, monkeypatch):
    write_session(
        tmp_path,
        [
            event("2026-08-24T00:00:00Z", "turn_context", {"model": "gpt-5.6-sol"}),
            token_event("2026-08-24T00:00:01Z", 100, 50, 10),
        ],
    )
    real_loads = usage_core.json.loads
    calls = 0

    def counting_loads(value):
        nonlocal calls
        calls += 1
        return real_loads(value)

    monkeypatch.setattr(usage_core.json, "loads", counting_loads)
    collect_usage(tmp_path, date(2026, 8, 24))
    first_calls = calls
    collect_usage(tmp_path, date(2026, 8, 24))

    assert first_calls > 0
    assert calls == first_calls


def test_rate_limit_window_and_latest_reset_are_preserved(tmp_path: Path):
    write_session(
        tmp_path,
        [
            event("2026-08-24T00:00:00Z", "turn_context", {"model": "gpt-5.6-sol"}),
            token_event(
                "2026-08-24T00:00:01Z",
                100,
                50,
                10,
                rate_limits={
                    "primary": {
                        "used_percent": 49,
                        "window_minutes": 10_080,
                        "resets_at": 1_777_000_000,
                    }
                },
            ),
        ],
    )

    result = collect_usage(tmp_path, date(2026, 8, 24))

    assert result.weekly_used_percent == 49
    assert result.rate_limit_window_minutes == 10_080
    assert result.weekly_reset_at is not None


def test_plus_rate_limits_keep_five_hour_and_weekly_windows(tmp_path: Path):
    write_session(
        tmp_path,
        [
            event("2026-08-24T00:00:00Z", "turn_context", {"model": "gpt-5.6-sol"}),
            token_event(
                "2026-08-24T00:00:01Z",
                100,
                50,
                10,
                rate_limits={
                    "primary": {
                        "used_percent": 24,
                        "window_minutes": 300,
                        "resets_at": 1_777_000_000,
                    },
                    "secondary": {
                        "used_percent": 61,
                        "window_minutes": 10_080,
                        "resets_at": 1_777_600_000,
                    },
                },
            ),
            token_event(
                "2026-08-24T00:00:02Z",
                100,
                50,
                10,
                rate_limits={
                    "primary": {
                        "used_percent": 62,
                        "window_minutes": 10_080,
                        "resets_at": 1_777_600_001,
                    },
                    "secondary": {
                        "used_percent": 25,
                        "window_minutes": 300,
                        "resets_at": 1_777_000_001,
                    },
                },
            ),
        ],
    )

    result = collect_usage(tmp_path, date(2026, 8, 24))

    assert result.five_hour_used_percent == 25
    assert result.five_hour_reset_at is not None
    assert result.weekly_used_percent == 62
    assert result.weekly_reset_at is not None


def test_history_parse_errors_are_not_multiplied_across_days(tmp_path: Path):
    session = write_session(tmp_path, [])
    session.write_text('{"token_count": broken}\n', encoding="utf-8")

    reports = collect_history(tmp_path, date(2026, 8, 20), date(2026, 8, 24))

    assert sum(report.parse_errors for report in reports) == 1


def test_format_tokens_is_human_readable():
    assert format_tokens(999) == "999"
    assert format_tokens(12_345) == "12.3K"
    assert format_tokens(1_234_567) == "1.23M"
