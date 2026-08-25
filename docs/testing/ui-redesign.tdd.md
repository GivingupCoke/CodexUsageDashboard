# UI redesign TDD evidence

## Source

The user journeys were derived during this implementation; no plan file was supplied.

## User journeys

- As a dashboard user, I can pin the window from the title bar next to the standard window controls.
- As a dashboard user, I can minimize, maximize, restore, collapse, and drag the custom window.
- As a dashboard user, I can scan today's primary metrics in a compact hierarchy while retaining selectable text.
- As a dashboard user, I see the same restrained dark visual language in the history chart and table.

## RED and GREEN evidence

| Behavior | RED evidence | GREEN evidence |
|---|---|---|
| Custom title bar and compact hierarchy | `python -m pytest tests/test_dashboard_ui.py::test_custom_titlebar_and_compact_dashboard_hierarchy -q` failed because `caption_controls` did not exist | The same target passed: `1 passed` |
| Main and history window flow | `python -m pytest tests/test_dashboard_ui.py -q` exposed the removed legacy `GOLD` color reference during the redesign | The same target passed: `2 passed` |
| Native window state integration | Not applicable to the prior system title bar | Runtime Win32 probe returned `WIN32_CHROME_OK maximize restore minimize` |

## Test specification

| # | What is guaranteed | Test or command | Type | Result |
|---|---|---|---|---|
| 1 | Pin is directly before minimize, maximize/restore, and close | `test_custom_titlebar_and_compact_dashboard_hierarchy` | UI integration | PASS |
| 2 | Pin state and active color stay synchronized | `test_custom_titlebar_and_compact_dashboard_hierarchy` | UI integration | PASS |
| 3 | Summary exposes total tokens, API estimate, and weekly progress | `test_custom_titlebar_and_compact_dashboard_hierarchy` | UI integration | PASS |
| 4 | Collapse and maximize icons track their window states | `test_custom_titlebar_and_compact_dashboard_hierarchy` | UI integration | PASS |
| 5 | History loading, chart, table, periods, copy, and failures remain functional | `test_dashboard_and_history_user_flow` | UI integration | PASS |
| 6 | Win32 maximize, restore, and minimize reach native states | Inline runtime probe using `IsZoomed` and `IsIconic` | Runtime integration | PASS |

## Coverage and quality gates

- `python -m coverage run -m pytest -q`: `15 passed`
- `python -m coverage report -m`: total branch coverage `84%`
- `ruff check .`: passed
- `ruff format --check .`: passed
- `python -m py_compile codex_usage_dashboard.py usage_core.py`: passed

Known gap: Windows 11 Snap Layout hover is not automated; native minimize, maximize, and restore states are runtime-tested.

## Merge evidence

The directory has no Git metadata, so no RED/GREEN checkpoint commits were created.
