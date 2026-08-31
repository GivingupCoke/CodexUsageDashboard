# Native titlebar drag crash TDD evidence

## Source and user journey

No plan file was supplied. The journey was derived from the reproduced crash:

- As a Windows user, I can drag the custom titlebar so the window moves without terminating the dashboard.

## Task report

### RED: remove the synchronous move-loop contract

Command:

```text
python -X faulthandler -m pytest -q tests/test_dashboard_ui.py::test_windows_titlebar_drag_posts_native_move_message
```

Result: `1 failed`; `_start_drag()` returned `None` because the old implementation called `SendMessageW`.

Checkpoint: `f459047 test: reproduce native titlebar drag crash`

### GREEN and packaged behavior correction

The first asynchronous `WM_NCLBUTTONDOWN` implementation passed its unit test but the packaged window did not move. The test was tightened to require `WM_SYSCOMMAND` with `SC_MOVE | HTCAPTION`.

Second RED: `1 failed` because `WM_SYSCOMMAND` was not implemented.

Final focused result: `1 passed` for `test_windows_titlebar_drag_posts_native_move_command`.

Checkpoints:

- `5d2bab2 fix: avoid reentrant titlebar drag crash`
- `f6a80f6 test: require asynchronous system move command`
- `e2e7d9a fix: post asynchronous system move command`

## Test specification

| Guarantee | Test or command | Type | Result |
|---|---|---|---|
| Drag initiation posts an asynchronous system move command with explicit Win32 signatures | `test_windows_titlebar_drag_posts_native_move_command` | Unit/Win32 contract | PASS |
| Existing dashboard behavior remains intact | `python -m coverage run --branch -m pytest -q` | Integration/UI | 35 passed |
| Project quality threshold remains satisfied | `python -m coverage report` | Coverage | 80% total |
| Final packaged window moves and remains alive | Physical drag of `dist/CodexUsageDashboard.exe` | Windows E2E | Moved `(0,0)` to `(120,90)`; process responding |

## Additional verification

- `python -m ruff check .`: PASS
- `python -m py_compile codex_usage_dashboard.py usage_core.py version.py tests/test_dashboard_ui.py`: PASS
- PyInstaller 6.19.0 one-file windowed build: PASS

## Known gap

The physical mouse drag is retained as a packaged acceptance check rather than an automated CI test because it manipulates the active Windows desktop. The unit test deterministically guards the exact asynchronous Win32 command and signatures.
