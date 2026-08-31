from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_windows_release_build_is_reproducible():
    build_script = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows-release.yml").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_data = tomllib.loads(project)

    assert 'build = ["pyinstaller>=6,<7"]' in project
    assert project_data["project"]["dynamic"] == ["version"]
    assert 'version = {attr = "version.__version__"}' in project
    assert "python -m PyInstaller" in build_script
    assert "--onefile" in build_script
    assert "--windowed" in build_script
    assert "CodexUsageDashboard" in build_script
    assert "pystray>=0.19,<1" in project
    assert '--icon (Join-Path $projectRoot "assets\\codex_usage_dashboard.ico")' in build_script
    assert "--add-data \"$(Join-Path $projectRoot 'assets');assets\"" in build_script
    assert (ROOT / "assets/codex_usage_dashboard.ico").is_file()
    assert (ROOT / "assets/codex_usage_dashboard.png").is_file()

    dashboard_source = (ROOT / "codex_usage_dashboard.py").read_text(encoding="utf-8")
    assert "self.iconbitmap(default=str(ico_path))" in dashboard_source
    assert 'if sys.platform == "win32":\n                    return' in dashboard_source
    assert "SINGLE_INSTANCE_MUTEX_NAME" in dashboard_source
    assert "_acquire_single_instance()" in dashboard_source
    assert "_tray_status_lines" in dashboard_source

    assert "windows-latest" in workflow
    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert 'python-version: "3.12"' in workflow
    assert "python -m pytest -q" in workflow
    assert "scripts/build_windows.ps1" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "publish-release:" in workflow
    assert "contents: read" in workflow
    assert "gh release" in workflow
    assert "path: dist/CodexUsageDashboard.exe" in workflow
    assert 'executable="./release/CodexUsageDashboard.exe"' in workflow
    assert "Compress-Archive" not in workflow
    assert "windows-x64.zip" not in workflow


def test_readme_leads_with_double_click_release_instructions():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ordinary_user = readme.index("## 普通用户：下载后双击运行")
    developer = readme.index("## 开发者：从源码运行")

    assert ordinary_user < developer
    assert readme.startswith("# Codex Usage Dashboard\n")
    assert "Releases" in readme[ordinary_user:developer]
    assert "CodexUsageDashboard.exe" in readme[ordinary_user:developer]
    assert "无需安装 Python" in readme[ordinary_user:developer]
    assert "py -3.12 -m venv" not in readme[:developer]
    assert "git tag v1.2" in readme
