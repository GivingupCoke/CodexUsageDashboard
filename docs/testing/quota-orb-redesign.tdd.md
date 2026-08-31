# Quota orb redesign TDD evidence

## Source and user journey

No plan file was supplied. The behavior was derived from the requested redesign:

- As a dashboard user, the titlebar collapse button enters quota-orb mode directly.
- As a dashboard user, clicking the orb restores the complete main window.
- As a dashboard user, I can read weekly and five-hour usage at a glance.
- As a Windows user, the orb has a clean transparent boundary on light and dark desktops.
- Existing drag, right-click menu, tray state, refresh updates, and exit behavior remain available.

## Design contract

- 120 x 120 pixel instrument-style orb.
- Weekly usage uses the outer cyan ring; five-hour usage uses the inner violet ring.
- Existing warning and critical thresholds remain amber at 70% and red at 90%.
- A dark glass core, restrained glow, tick marks, and endpoint nodes provide depth without continuous animation.
- Text exposes the weekly percentage, `WEEK`, and the five-hour percentage.
- The duplicate bottom `悬浮球` button and the intermediate titlebar-only collapsed state are removed.
- The opaque body stops at radius 54; 24 independently masked ticks restore the airy silhouette without color-key fringe.

## RED and GREEN evidence

| Behavior | RED evidence | GREEN evidence |
|---|---|---|
| Unified collapse/orb entry and readable quota labels | Focused UI run failed `3 failed`: the collapse button still used the old strip mode, the 76 px orb had no labels, and the duplicate bottom button remained | The same focused run passed `3 passed, 1 deselected` |
| Windows color-key transparency | `test_quota_orb_lifecycle_and_rings` failed because rendered alpha contained values between 0 and 255, reproduced as black fringe in the packaged screenshot | The same target passed after adding an opaque instrument plate and binary alpha mask |
| Airy silhouette regression | The focused pixel test failed because a point between outer ticks was still opaque, proving the color-key fix had become a full black disc | The same target passed after shrinking the plate and masking the 24 outer ticks independently |

Checkpoints:

- `878d00c test: define redesigned quota orb behavior`
- `e29ea52 feat: redesign quota orb and unify collapse entry`
- `add6ad5 test: reproduce quota orb color-key fringe`
- `401201e fix: eliminate quota orb color-key fringe`
- `4084283 test: reproduce solid quota orb silhouette`
- `afe4f93 fix: restore airy quota orb silhouette`

## Test specification

| Guarantee | Test or command | Type | Result |
|---|---|---|---|
| Titlebar collapse enters orb mode and withdraws the main window | `test_custom_titlebar_and_compact_dashboard_hierarchy` | UI integration | PASS |
| Clicking the orb restores the complete main window | `test_quota_orb_lifecycle_and_rings` | UI integration | PASS |
| The duplicate bottom orb button and old collapsed state are absent | `test_custom_titlebar_and_compact_dashboard_hierarchy` | UI contract | PASS |
| Weekly, WEEK, and five-hour labels update with reports and unknown data | `test_quota_orb_lifecycle_and_rings` | UI integration | PASS |
| Color-key output contains only fully transparent or fully opaque alpha | `test_quota_orb_lifecycle_and_rings` | Pixel contract | PASS |
| The outer tick is opaque while the gap between ticks exposes the desktop | `test_quota_orb_lifecycle_and_rings` | Pixel/shape contract | PASS |
| Existing dashboard and history flow remains intact | Full test suite | Regression | 35 passed |
| Final packaged EXE hides to the 120 px orb and restores on click | Physical Windows E2E | Packaged runtime | PASS |

## Final verification

- `ruff check .`: PASS
- `py_compile`: PASS
- Full pytest suite: `35 passed`
- Combined line/branch coverage: `81.64%` (required: 80%)
- Basic Python secret scan: no matches
- PyInstaller 6.19.0 one-file windowed build: PASS
- Packaged E2E: `main_hidden=True`, `main_restored=True`
- Final EXE SHA-256: `5a593c3635ed840f401d7fc7b880d32219a9bdb6193bd1375ac6cf0617da8936`
- Final screenshots: `orb-airy-packaged-light.png`, `orb-airy-packaged-dark.png`

## Known boundary

The physical mouse interaction and desktop compositing check are retained as a local packaged acceptance test because they require the active Windows desktop. Deterministic UI and pixel contracts cover the behavior in the automated suite.
