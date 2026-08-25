# Codex Usage Dashboard

一个面向 Windows 的本地 Codex 用量面板。它读取 Codex 保存在本机的会话日志，按北京时间统计每日 Token、缓存命中率、额度周期和 API 等价费用，并提供最近 7 天、30 天及当前额度周期的历史趋势。

> [!IMPORTANT]
> 费用是根据日志中的 Token 和代码内置的公开 API 价格计算出的参考值，不是 ChatGPT Plus 账单，也不代表账户实际扣费。

## 主要功能

- 按北京时间 `00:00–24:00` 汇总当日使用量
- 展示输入、缓存输入、输出 Token 和缓存率；统计引擎同时识别缓存写入与推理输出
- 计算缓存率和当前额度窗口的已用比例、重置时间
- 按日志中的模型标识统计各模型的 Token 使用量；只要日志中存在模型标识，GPT 和非 GPT 模型都会纳入统计
- 主面板和历史窗口可在“全部模型”与单个模型之间原位切换，不额外展开明细列表；额度仍明确显示为账户全局数据
- 对价格表中的 GPT 模型估算 API 等价费用；非价格表模型仍统计 Token，但费用会明确标记为未计价
- 查看最近 7 天、30 天或最近一次额度周期的图表和明细表
- 启动后显示在 Windows 任务栏；关闭窗口时可隐藏到系统托盘，托盘菜单支持进入主界面、刷新、历史记录和退出
- 系统托盘状态中显示今日总 Token 和 API 参考估算，费用不完整时同时标记未计价模型

置顶按钮位于标题栏最小化按钮左侧。按钮显示蓝紫色时，表示窗口正在保持置顶。

## 工作原理

Codex 会在用户目录下保存 JSONL 会话日志：

```text
C:\Users\<用户名>\.codex\sessions\YYYY\MM\DD\*.jsonl
```

程序的数据流如下：

```text
本地 JSONL 日志
      │
      ▼
筛选 turn_context / token_count 事件
      │
      ▼
累计 Token 快照做相邻差分
      │
      ▼
转换为北京时间并按日期、模型聚合
      │
      ├── Token / 缓存率 / 额度周期
      └── API 等价费用估算
      │
      ▼
Tkinter 主面板 + Matplotlib 历史图表
```

### 1. 读取本地会话日志

程序递归扫描 `~/.codex/sessions` 下的 `.jsonl` 文件，只读取日志，不会修改会话文件。解析器只处理与统计有关的两类记录：

- `turn_context`：确定后续 Token 属于哪个模型
- `event_msg / token_count`：读取累计 Token 快照和额度信息

其他日志内容会被跳过。

### 2. 对累计快照做差分

日志中的 `total_token_usage` 是会话运行到当前时刻的累计值，不能直接把每条记录相加。程序为每个会话保存上一条快照，并计算：

```text
本次实际增量 = 当前累计值 - 上一次累计值
```

如果累计值发生回退，程序会把它视为一次新的计数序列；零增量不会重复计入。这样可以避免同一批 Token 被多次累计。

### 3. 按北京时间归档

日志时间戳先解析为 UTC，再转换到 `UTC+08:00`。每天的统计边界固定为北京时间 `00:00–24:00`，不受 Windows 当前显示语言影响。

主要指标的计算方式：

```text
总 Token = 输入 Token + 输出 Token
缓存率    = 缓存输入 Token / 输入 Token
```

推理输出会单独记录，但不会再次加入总 Token，避免与输出 Token 重复计算。

### 4. 读取 Codex 额度窗口

程序同时读取日志 `rate_limits` 中的 `primary` 和 `secondary` 窗口。Plus 用户日志可能同时包含：

- `window_minutes = 300`：5 小时额度
- `window_minutes = 10080`：周额度

主面板和托盘菜单会分别显示可用窗口及其使用百分比、下次重置时间。额度是账户级信息，不会随模型筛选切换。

### 5. 估算 API 等价费用

费用按每个模型、每次 Token 增量分别计算，再汇总到当天。计算会区分：

- 未缓存输入
- 缓存输入
- 缓存写入
- 输出 Token
- 长上下文倍率

价格表定义在 [`usage_core.py`](./usage_core.py) 的 `PRICES` 中，当前核对日期为 **2026-08-24**：

| 模型 | 输入 / 1M Token | 缓存输入 / 1M Token | 输出 / 1M Token |
|---|---:|---:|---:|
| `gpt-5.6` | $4.00 | $0.40 | $20.00 |
| `gpt-5.6-sol` | $4.00 | $0.40 | $20.00 |
| `gpt-5.6-terra` | $2.00 | $0.20 | $12.00 |
| `gpt-5.6-luna` | $0.20 | $0.02 | $1.20 |

补充规则：

- 缓存写入按基础输入价格的 `1.25` 倍估算
- 单次输入超过 `272K` Token 时，输入价格乘 `2`，输出价格乘 `1.5`
- 未知或内部模型不会套用其他模型价格
- 存在未计价模型时，费用后会显示 `*`，表示结果不完整
- 历史费用统一使用当前代码中的价格重新计算，不是历史时点账单

价格来源：[OpenAI 模型文档](https://developers.openai.com/api/docs/models/compare)

### 5. 增量缓存和后台刷新

为避免反复读取大型日志，程序会在内存中记录每个文件的大小、修改时间、读取偏移和上一条累计快照：

- 文件未变化：直接复用解析缓存
- 文件继续追加：只读取上次偏移之后的新内容
- 文件缩小或被替换：从头重新解析
- 最后一行尚未写完整：保留偏移，等待下次刷新重试

主面板和历史窗口均在后台线程中读取日志。切换历史周期时，旧请求即使稍后完成，也不会覆盖更新的结果。

## 隐私和安全

- 所有统计均在本机完成
- 不需要登录额外账户
- 不上传日志、提示词或统计结果
- 不修改、移动或删除 Codex 会话文件
- 项目本身不发起网络请求

README 中的价格来源链接仅供人工核对，程序运行时不会访问该网站。

## 普通用户：下载后双击运行

普通用户无需安装 Python、创建虚拟环境或输入命令：

1. 打开仓库右侧的 **[Releases](../../releases/latest)** 页面。
2. 直接下载最新的 `CodexUsageDashboard.exe`。
3. 双击 `CodexUsageDashboard.exe`。

程序会自动读取当前 Windows 用户的：

```text
%USERPROFILE%\.codex\sessions
```

如果目录不存在或还没有产生 Codex 会话日志，面板会显示为零用量。

> [!NOTE]
> 当前 EXE 没有购买代码签名证书。Windows SmartScreen 首次运行时可能显示提示；请确认文件来自本仓库的 Release，再选择“更多信息 → 仍要运行”。

## 开发者：从源码运行

只有准备修改代码、运行测试或自行构建 EXE 时，才需要下面的步骤。

环境要求：

- Windows 10 或 Windows 11
- Python 3.12 或更高版本
- Tk 8.6（Python 官方 Windows 安装包通常已包含）

克隆仓库并安装开发环境：

```powershell
git clone https://github.com/GivingupCoke/CodexUsageDashboard.git
cd CodexUsageDashboard
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,build]"
```

从源码启动：

```powershell
python .\codex_usage_dashboard.py
```

在本机生成单文件 EXE：

```powershell
.\scripts\build_windows.ps1
```

生成结果位于：

```text
dist\CodexUsageDashboard.exe
```

项目依赖和构建工具通过 [`pyproject.toml`](./pyproject.toml) 管理。

## 使用说明

- 点击标题栏图钉切换窗口置顶
- 点击标题旁的箭头收起或展开面板
- 点击“刷新”立即重新读取日志；程序也会每 60 秒自动刷新
- 点击“历史记录”查看不同时间范围的趋势和明细
- 主面板可直接拖选文字，使用 `Ctrl+A` 全选、`Ctrl+C` 复制
- 历史表格可选择一行或多行后按 `Ctrl+C` 复制

## 发布 Windows 版本

仓库包含 [Windows Release 工作流](./.github/workflows/windows-release.yml)。推送 `v` 开头的标签后，GitHub Actions 会自动：

1. 在 Windows 环境运行测试。
2. 使用 PyInstaller 构建单文件 EXE。
3. 创建对应的 GitHub Release 并直接上传 `CodexUsageDashboard.exe`。

示例：

```powershell
git tag v1.0
git push origin v1.0
```

也可以在 GitHub Actions 页面手动运行工作流。手动运行只生成可下载的构建产物，不自动创建正式 Release。

## 项目结构

```text
CodexUsageDashboard/
├── .github/workflows/
│   └── windows-release.yml    # 自动构建和发布 Windows EXE
├── scripts/
│   └── build_windows.ps1      # 本地 PyInstaller 构建脚本
├── codex_usage_dashboard.py   # Tkinter 界面、窗口控制和后台任务
├── usage_core.py              # 日志解析、差分聚合、缓存和费用估算
├── tests/
│   ├── test_usage_core.py     # 统计与费用规则测试
│   ├── test_dashboard_logic.py
│   └── test_dashboard_ui.py   # Tk 界面交互测试
├── docs/testing/              # TDD 和验证记录
├── pyproject.toml             # 构建、依赖和工具配置
└── README.md
```

## 开发与验证

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q
python -m coverage run -m pytest -q
python -m coverage report -m
ruff check .
ruff format --check .
```

当前测试覆盖以下关键行为：

- 北京时间日期边界
- 累计 Token 快照去重和差分
- 模型归属与费用规则
- 未知模型和损坏日志处理
- 未写完的 JSONL 尾行重试
- 增量文件缓存
- Plus 5 小时额度与周额度的双窗口解析和展示
- 后台任务的过期结果丢弃
- 主窗口、历史窗口、复制和窗口控制

## 已知限制

- 目前主要针对 Windows 开发和测试，其他平台不在支持范围内
- Codex 本地日志格式如果发生变化，解析规则可能需要同步更新
- 费用估算依赖代码中的静态价格表，需要人工核对和维护
- 额度信息取自日志中最近一次有效的 `rate_limits.primary`/`secondary` 记录；日志格式变化时可能需要同步解析规则
- 自定义标题栏支持最小化、最大化和还原，但未自动测试 Windows 11 最大化按钮的悬停 Snap Layout 菜单

## 贡献

欢迎提交 Issue 或 Pull Request。修改统计逻辑时，请同时补充测试，并确保费用估算、北京时间边界和未知模型处理仍然明确可验证。
