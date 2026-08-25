# Windows release TDD evidence

## Source and user journeys

No external plan file was supplied. The journeys were derived from the request:

1. A non-developer downloads one archive and starts the dashboard by double-clicking an EXE.
2. A maintainer can reproduce the Windows build with one PowerShell command.
3. A tagged GitHub build runs tests before publishing the same archive to Releases.
4. Build jobs use read-only repository permission; only the release job can write a Release.

## RED and GREEN evidence

- Initial RED: `python -m pytest tests/test_release_packaging.py -q` returned `2 failed` because the build script, workflow, build dependency, and simplified README sections did not exist.
- Initial GREEN: the same target returned `2 passed` after adding those release surfaces.
- Action-version RED: the packaging test failed after it was updated to require the current official action major versions.
- Action-version GREEN: the workflow passed after updating to `checkout@v6`, `setup-python@v6`, `upload-artifact@v7`, and `download-artifact@v8`.

## Test specification

| # | What is guaranteed | Test or command | Type | Result |
|---|---|---|---|---|
| 1 | The local build uses PyInstaller single-file windowed mode | `test_windows_release_build_is_reproducible` | configuration | PASS |
| 2 | The workflow runs on Windows with Python 3.12 and tests before building | `test_windows_release_build_is_reproducible` | configuration | PASS |
| 3 | The workflow uploads an artifact and publishes tagged Releases | `test_windows_release_build_is_reproducible` | configuration | PASS |
| 4 | README presents EXE download before developer commands | `test_readme_leads_with_double_click_release_instructions` | documentation | PASS |
| 5 | The packaged EXE creates a responsive main window | Win32 process-family smoke probe | runtime | PASS |
| 6 | The packaged EXE can open the Matplotlib history window | Win32 click and window-enumeration probe | runtime | PASS |
| 7 | The release ZIP contains the EXE and README | `System.IO.Compression.ZipFile` archive inspection | artifact | PASS |

## Build evidence

- Build command: `.\scripts\build_windows.ps1`
- PyInstaller: `6.19.0`
- Python: `3.12.10`
- Build-platform test result: `17 passed`
- Executable: `dist\CodexUsageDashboard.exe`
- Executable size: `39.28 MB`
- Executable SHA-256: `EBA2581C44A0C488A24B641F8AEC18E30693656D126066B2265403532F71126B`
- Release archive: `dist\CodexUsageDashboard-windows-x64.zip`
- Release archive size: `38.88 MB`

## Validation notes and known gaps

- The workflow YAML parsed successfully and its read/write permission split was inspected.
- `actionlint` was not installed, so no actionlint result is claimed.
- The GitHub-hosted workflow cannot be executed until this directory is uploaded as a GitHub repository.
- The first smoke probe checked only the PyInstaller launcher PID and missed the child window process. The corrected probe inspected the complete executable process family and found the responsive window.
- This directory has no Git metadata, so no RED/GREEN checkpoint commits were created.

## v1.0 naming evidence

- RED: the targeted UI and packaging tests returned `3 failed` because `APP_VERSION` did not exist, project metadata was `0.2.0`, and README had no public version.
- GREEN: the same targets returned `4 passed` after centralizing `APP_VERSION = "1.0"` and synchronizing the UI, history title, README, metadata, and release-tag example.
- Packaged runtime: the rebuilt EXE opened with the verified window title `Codex Usage v1.0 · 今日用量` and remained responsive.
