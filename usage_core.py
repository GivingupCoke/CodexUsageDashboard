"""Beijing-day Codex usage aggregation from cumulative JSONL snapshots."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
UTC = timezone.utc

# Current base API-equivalent prices checked against official OpenAI model docs.
# These are estimates only; they are not ChatGPT Plus charges.
PRICE_CHECKED_ON = date(2026, 8, 24)
PRICE_SOURCE_URL = "https://developers.openai.com/api/docs/models/compare"
PRICES = {
    "gpt-5.6": {"input": 4.0, "cached": 0.4, "output": 20.0},
    "gpt-5.6-sol": {"input": 4.0, "cached": 0.4, "output": 20.0},
    "gpt-5.6-terra": {"input": 2.0, "cached": 0.2, "output": 12.0},
    "gpt-5.6-luna": {"input": 0.2, "cached": 0.02, "output": 1.2},
}
LONG_CONTEXT_THRESHOLD = 272_000
CACHE_WRITE_MULTIPLIER = 1.25
_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


def _empty_usage() -> dict[str, int]:
    return {key: 0 for key in _KEYS}


def estimate_cost_usd(model: str, usage: Mapping[str, int]) -> float | None:
    """Estimate one token event at current documented base API prices.

    Unknown/internal model identifiers deliberately return ``None`` instead of
    being silently assigned another model's price.
    """
    price = PRICES.get(model)
    if price is None:
        return None

    input_tokens = max(0, int(usage.get("input_tokens", 0)))
    cached_tokens = min(input_tokens, max(0, int(usage.get("cached_input_tokens", 0))))
    cache_write_tokens = min(
        input_tokens - cached_tokens,
        max(0, int(usage.get("cache_write_input_tokens", 0))),
    )
    uncached_tokens = max(0, input_tokens - cached_tokens - cache_write_tokens)
    output_tokens = max(0, int(usage.get("output_tokens", 0)))
    long_context = input_tokens > LONG_CONTEXT_THRESHOLD
    input_multiplier = 2.0 if long_context else 1.0
    output_multiplier = 1.5 if long_context else 1.0

    input_cost = (
        uncached_tokens * price["input"]
        + cached_tokens * price["cached"]
        + cache_write_tokens * price["input"] * CACHE_WRITE_MULTIPLIER
    ) * input_multiplier
    output_cost = output_tokens * price["output"] * output_multiplier
    return (input_cost + output_cost) / 1_000_000


@dataclass
class ModelUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def uncached_input_tokens(self) -> int:
        return max(
            0,
            self.input_tokens - self.cached_input_tokens - self.cache_write_input_tokens,
        )

    def add(self, delta: Mapping[str, int], estimated_cost_usd: float | None = None) -> None:
        for key in _KEYS:
            setattr(self, key, getattr(self, key) + int(delta[key]))
        if estimated_cost_usd is not None:
            self.estimated_cost_usd += estimated_cost_usd

    def merge(self, other: ModelUsage) -> None:
        for key in _KEYS:
            setattr(self, key, getattr(self, key) + getattr(other, key))
        self.estimated_cost_usd += other.estimated_cost_usd


@dataclass
class UsageReport(ModelUsage):
    day: date = field(default_factory=lambda: datetime.now(BEIJING).date())
    by_model: dict[str, ModelUsage] = field(default_factory=dict)
    weekly_used_percent: float | None = None
    weekly_reset_at: datetime | None = None
    rate_limit_window_minutes: int | None = None
    sessions_scanned: int = 0
    files_with_usage: int = 0
    parse_errors: int = 0
    _rate_limit_observed_at: datetime | None = field(default=None, repr=False)

    @property
    def cache_rate(self) -> float:
        return self.cached_input_tokens / self.input_tokens if self.input_tokens else 0.0

    @property
    def cost_usd(self) -> float:
        return sum(usage.estimated_cost_usd for usage in self.by_model.values())

    @property
    def unpriced_models(self) -> tuple[str, ...]:
        return tuple(
            sorted(model for model, usage in self.by_model.items() if model not in PRICES and usage.total_tokens)
        )

    @property
    def cost_is_partial(self) -> bool:
        return bool(self.unpriced_models)


@dataclass
class _DaySummary:
    by_model: dict[str, ModelUsage] = field(default_factory=dict)
    weekly_used_percent: float | None = None
    weekly_reset_at: datetime | None = None
    rate_limit_window_minutes: int | None = None
    rate_limit_observed_at: datetime | None = None
    parse_errors: int = 0
    touched: bool = False


@dataclass
class _SessionCacheEntry:
    size: int = 0
    mtime_ns: int = 0
    offset: int = 0
    previous: dict[str, int] = field(default_factory=_empty_usage)
    model: str = "(unknown)"
    days: dict[date, _DaySummary] = field(default_factory=dict)
    unscoped_errors: int = 0


_SESSION_CACHE: dict[Path, _SessionCacheEntry] = {}
_CACHE_LOCK = threading.RLock()


def clear_usage_cache() -> None:
    """Clear the in-process JSONL parse cache."""
    with _CACHE_LOCK:
        _SESSION_CACHE.clear()


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).astimezone(UTC)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=BEIJING).astimezone(UTC)
    return start, start + timedelta(days=1)


def format_tokens(value: int) -> str:
    if value < 1_000:
        return f"{value:,}"
    if value < 1_000_000:
        return f"{value / 1_000:.1f}K"
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.2f}M"
    return f"{value / 1_000_000_000:.2f}B"


def _session_files(root: Path, start_utc: datetime) -> Iterable[tuple[Path, object]]:
    if not root.exists():
        return ()

    cutoff_timestamp = start_utc.timestamp()

    def candidates() -> Iterable[tuple[Path, object]]:
        try:
            paths = root.rglob("*.jsonl")
            for path in paths:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if path.is_file() and stat.st_mtime >= cutoff_timestamp:
                    yield path, stat
        except OSError:
            return

    return candidates()


def _usage(payload: dict) -> dict[str, int] | None:
    raw = (payload.get("info") or {}).get("total_token_usage")
    if not isinstance(raw, dict):
        return None
    parsed: dict[str, int] = {}
    for key in _KEYS:
        value = raw.get(key) or 0
        if isinstance(value, bool):
            raise ValueError(f"invalid boolean token count for {key}")
        parsed[key] = int(value)
        if parsed[key] < 0:
            raise ValueError(f"negative token count for {key}")
    return parsed


def _delta(current: Mapping[str, int], previous: Mapping[str, int]) -> dict[str, int]:
    if any(current[key] < previous[key] for key in _KEYS):
        previous = _empty_usage()
    return {key: max(0, current[key] - previous[key]) for key in _KEYS}


def _row_day(row: Mapping[str, object]) -> date | None:
    try:
        return parse_timestamp(str(row.get("timestamp", ""))).astimezone(BEIJING).date()
    except (TypeError, ValueError):
        return None


def _record_error(entry: _SessionCacheEntry, row: Mapping[str, object] | None = None) -> None:
    day = _row_day(row) if row is not None else None
    if day is None:
        entry.unscoped_errors += 1
    else:
        entry.days.setdefault(day, _DaySummary()).parse_errors += 1


def _parse_rate_limit(
    entry: _SessionCacheEntry,
    row: Mapping[str, object],
    payload: Mapping[str, object],
    summary: _DaySummary,
    observed_at: datetime,
) -> None:
    rate_limits = payload.get("rate_limits") or {}
    if not isinstance(rate_limits, dict):
        _record_error(entry, row)
        return
    primary = rate_limits.get("primary") or {}
    if not isinstance(primary, dict) or primary.get("used_percent") is None:
        return
    try:
        used_percent = float(primary["used_percent"])
        window_minutes = int(primary["window_minutes"]) if primary.get("window_minutes") is not None else None
        reset_at = (
            datetime.fromtimestamp(int(primary["resets_at"]), tz=UTC).astimezone(BEIJING)
            if primary.get("resets_at") is not None
            else None
        )
    except (OverflowError, TypeError, ValueError):
        _record_error(entry, row)
        return
    if summary.rate_limit_observed_at is None or observed_at >= summary.rate_limit_observed_at:
        summary.weekly_used_percent = used_percent
        summary.rate_limit_window_minutes = window_minutes
        summary.weekly_reset_at = reset_at
        summary.rate_limit_observed_at = observed_at


def _process_row(entry: _SessionCacheEntry, row: object) -> None:
    if not isinstance(row, dict):
        _record_error(entry)
        return
    payload = row.get("payload") or {}
    if not isinstance(payload, dict):
        _record_error(entry, row)
        return
    if row.get("type") == "turn_context" and payload.get("model"):
        entry.model = str(payload["model"])
        return
    if row.get("type") != "event_msg" or payload.get("type") != "token_count":
        return
    try:
        current = _usage(payload)
    except (OverflowError, TypeError, ValueError):
        _record_error(entry, row)
        return
    if current is None:
        return

    delta = _delta(current, entry.previous)
    entry.previous = current
    try:
        timestamp = parse_timestamp(str(row.get("timestamp", "")))
    except (TypeError, ValueError):
        _record_error(entry, row)
        return
    day = timestamp.astimezone(BEIJING).date()
    summary = entry.days.setdefault(day, _DaySummary())
    if sum(delta.values()):
        summary.touched = True
        model_usage = summary.by_model.setdefault(entry.model, ModelUsage())
        model_usage.add(delta, estimate_cost_usd(entry.model, delta))
    _parse_rate_limit(entry, row, payload, summary, timestamp)


def _load_session(path: Path, stat: object) -> _SessionCacheEntry:
    size = int(getattr(stat, "st_size"))
    mtime_ns = int(getattr(stat, "st_mtime_ns"))
    cached = _SESSION_CACHE.get(path)
    if cached is not None and cached.size == size and cached.mtime_ns == mtime_ns:
        return cached

    can_extend = cached is not None and size > cached.size and cached.offset <= cached.size
    if can_extend:
        assert cached is not None
        entry = cached
    else:
        entry = _SessionCacheEntry()
    start_offset = entry.offset if can_extend else 0
    # Binary offsets are stable and ``tell()`` is much cheaper than on a text
    # wrapper, which matters for large append-only session logs.
    with path.open("rb") as handle:
        handle.seek(start_offset)
        while True:
            line_start = handle.tell()
            line = handle.readline()
            if not line:
                break
            line_end = handle.tell()
            complete_line = line.endswith(b"\n")
            if not complete_line:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    entry.offset = line_start
                    break
                _process_row(entry, row)
                entry.offset = line_end
                continue
            if b'"token_count"' not in line and b'"turn_context"' not in line:
                entry.offset = line_end
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                _record_error(entry)
                entry.offset = line_end
                continue
            _process_row(entry, row)
            entry.offset = line_end
    entry.size = size
    entry.mtime_ns = mtime_ns
    _SESSION_CACHE[path] = entry
    return entry


def _merge_day(report: UsageReport, summary: _DaySummary) -> None:
    report.parse_errors += summary.parse_errors
    if summary.touched:
        report.files_with_usage += 1
    for model, source in summary.by_model.items():
        report.by_model.setdefault(model, ModelUsage()).merge(source)
    if summary.rate_limit_observed_at is not None and (
        report._rate_limit_observed_at is None or summary.rate_limit_observed_at >= report._rate_limit_observed_at
    ):
        report.weekly_used_percent = summary.weekly_used_percent
        report.weekly_reset_at = summary.weekly_reset_at
        report.rate_limit_window_minutes = summary.rate_limit_window_minutes
        report._rate_limit_observed_at = summary.rate_limit_observed_at


def _collect_range(sessions_root: str | Path, first_day: date, last_day: date) -> dict[date, UsageReport]:
    reports = {
        first_day + timedelta(days=i): UsageReport(day=first_day + timedelta(days=i))
        for i in range((last_day - first_day).days + 1)
    }
    start = day_bounds(first_day)[0]
    paths = list(_session_files(Path(sessions_root), start))
    for report in reports.values():
        report.sessions_scanned = len(paths)

    with _CACHE_LOCK:
        for path, stat in paths:
            try:
                entry = _load_session(path, stat)
            except OSError:
                reports[first_day].parse_errors += 1
                continue
            reports[first_day].parse_errors += entry.unscoped_errors
            for day, report in reports.items():
                summary = entry.days.get(day)
                if summary is not None:
                    _merge_day(report, summary)

    for report in reports.values():
        for usage in report.by_model.values():
            report.input_tokens += usage.input_tokens
            report.cached_input_tokens += usage.cached_input_tokens
            report.cache_write_input_tokens += usage.cache_write_input_tokens
            report.output_tokens += usage.output_tokens
            report.reasoning_output_tokens += usage.reasoning_output_tokens
            report.estimated_cost_usd += usage.estimated_cost_usd
    return reports


def collect_usage(sessions_root: str | Path, day: date | datetime | None = None) -> UsageReport:
    target = (
        datetime.now(BEIJING).date()
        if day is None
        else day.astimezone(BEIJING).date()
        if isinstance(day, datetime)
        else day
    )
    return _collect_range(sessions_root, target, target)[target]


def collect_history(sessions_root: str | Path, first_day: date, last_day: date | None = None) -> list[UsageReport]:
    last_day = last_day or datetime.now(BEIJING).date()
    if last_day < first_day:
        return []
    return list(_collect_range(sessions_root, first_day, last_day).values())
