# Usage dashboard hardening TDD evidence

## Source and user journeys

No external plan file was supplied. The journeys were derived from the requested audit fixes:

1. A user sees a current, explicitly partial API-equivalent estimate instead of a fabricated price for unknown models.
2. A user can refresh large local logs without blocking the Tk event loop.
3. A user switching history periods sees only the latest request and receives a visible error instead of an endless loading state.
4. A malformed or partially written JSONL record does not abort or silently corrupt the whole report.
5. A user keeps the existing Beijing-day, compact, native-copy workflow.

## RED and GREEN evidence

- RED command: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q -p no:cacheprovider tests`
- RED result: test collection failed because `PRICE_CHECKED_ON`, `LatestResultQueue`, and the new pricing/cache APIs did not exist.
- GREEN command: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q`
- GREEN result: `14 passed`.
- Coverage command: `python -m coverage run -m pytest -q; python -m coverage report -m`
- Coverage result: 89% total branch-aware coverage (`codex_usage_dashboard.py` 91%, `usage_core.py` 87%).

## Test specification

| # | Guaranteed behavior | Test target | Type | Result |
|---|---|---|---|---|
| 1 | Beijing-day cumulative snapshots are de-duplicated and attributed by model | `test_collects_beijing_calendar_day_and_deduplicates_snapshots` | integration | PASS |
| 2 | Sol/Terra/Luna prices, cache-write surcharge, and long-context multipliers are applied per event | `test_uses_current_official_base_prices_and_cache_write_surcharge` | unit | PASS |
| 3 | Unknown/internal models remain unpriced and make the estimate explicitly partial | `test_unknown_models_are_reported_instead_of_silently_priced` | integration | PASS |
| 4 | Invalid token fields are counted as parse warnings without aborting collection | `test_malformed_usage_is_counted_without_aborting_collection` | integration | PASS |
| 5 | An incomplete final JSONL line is retried after append | `test_partial_last_line_is_retried_after_append` | integration | PASS |
| 6 | Unchanged session files are served from the in-process parse cache | `test_unchanged_sessions_reuse_the_parse_cache` | unit | PASS |
| 7 | Stale history results cannot overwrite the newest period request | `test_latest_result_queue_discards_stale_results` | unit | PASS |
| 8 | Worker exceptions are returned to the UI queue | `test_history_worker_returns_exceptions_to_the_ui` | unit | PASS |
| 9 | Main refresh, history rendering, error states, native copying, and collapse/expand work in a real Tk instance | `test_dashboard_and_history_user_flow` | UI integration | PASS |

## Known limits

- Prices are a current-base-price estimate checked on 2026-08-24, not a Plus bill or an effective-dated historical invoice.
- Unknown model identifiers remain excluded until an authoritative price mapping exists.
- The first scan still reads matching files once; subsequent unchanged scans use the in-process cache.
- This directory is not a Git repository, so no RED/GREEN checkpoint commits were created.
