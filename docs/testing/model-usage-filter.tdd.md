# Model usage filter TDD evidence

## Source and user journey

No plan file was supplied. The journey was derived from the requested compact UI:

> As a user who switches between several models, I want to select all usage or one model in place, so that I can compare usage without expanding the dashboard into a long model table.

The weekly or other rate-limit percentage remains account-global because the local logs do not provide a reliable per-model quota split.

## RED and GREEN evidence

- RED command: `python -m pytest -q tests\test_dashboard_logic.py tests\test_dashboard_ui.py`
- RED result: collection failed because `ALL_MODELS_LABEL` and the model-selection helpers did not yet exist.
- GREEN command: `python -m pytest -q tests\test_dashboard_logic.py tests\test_dashboard_ui.py`
- GREEN result: `9 passed` after the initial implementation.
- Final suite command: `python -m coverage run -m pytest -q`
- Final suite result: `26 passed`.
- Coverage command: `python -m coverage report --precision=2`
- Coverage result: total `80.51%`, above the configured `80%` threshold.
- Static check: `python -m ruff check .`
- Static-check result: `All checks passed!`

## Test specification

| # | Guarantee | Test target | Type | Result |
|---|---|---|---|---|
| 1 | Available models are unique and ordered by total Token usage | `test_model_options_are_unique_and_sorted_by_total_usage` | Unit | PASS |
| 2 | Selecting all, one known model, or a missing model returns the correct usage slice | `test_usage_for_model_returns_selected_usage_or_empty_usage` | Unit | PASS |
| 3 | Cost and unpriced markers follow the selected model | `test_model_cost_and_unpriced_state_follow_the_selection` | Unit | PASS |
| 4 | The main window switches existing metrics in place and labels quota as global | `test_dashboard_and_history_user_flow` | UI integration | PASS |
| 5 | The history chart, totals, and daily rows switch to the selected model without rescanning | `test_dashboard_and_history_user_flow` | UI integration | PASS |
| 6 | A model that disappears after refresh falls back to “全部模型” | `test_dashboard_and_history_user_flow` | UI integration | PASS |

## Coverage and known gaps

The complete suite passes without skipped tests. Windows shell integration and some defensive Tk/Matplotlib error branches remain outside automated UI coverage; the model-selection data path, refresh behavior, and visible summaries are covered.

## Checkpoints

- `37e748c` — RED tests for model filtering.
- `c06f097` — minimal model-filter implementation with the same target tests GREEN.
