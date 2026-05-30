# CodeBuddy Statusline

CodeBuddy Code 的实时状态栏工具，类似于 Claude Hud，在状态栏实时显示当前会话的 Context 进度条、Token 用量、工具调用、费用等信息。

## 效果预览

状态栏分两行实时显示：

```
GLM-5.1 | ▕████▍     ▏44% 56.7K/128.0K | In:2.4M Out:10.7K Cache:2.2M Think:952 | Req:29 | Cost:$0.023 | Credits:67.20 | Time:45s | +156/-23
✓ Bash×15 ✓ Read×2 ✓ Edit×2 ✓ Agent ↑ Agent ✓ Agent×2
```

### 第一行：概览

| 字段 | 说明 |
|------|------|
| `GLM-5.1` | 当前模型名称 |
| `▕████▍     ▏44%` | Context 进度条（绿 < 50%，黄 < 80%，红 >= 80%） |
| `56.7K/128.0K` | 当前 Context 用量 / 窗口上限 |
| `In:2.4M` | 输入 Token 数（自动缩写 K/M） |
| `Out:10.7K` | 输出 Token 数 |
| `Cache:2.2M` | 缓存命中 Token 数 |
| `Think:952` | 推理/思考 Token 数 |
| `Req:29` | API 请求次数 |
| `Cost:$0.023` | 费用（按金额变色：绿 < $0.01，黄 < $0.1，红 >= $0.1） |
| `Credits:67.20` | 消耗 Credits |
| `Time:45s` | 会话耗时 |
| `+156/-23` | 代码增删行数 |

### 第二行：工具调用 & Agent 状态

**工具调用：**

| 格式 | 说明 |
|------|------|
| `✓ Bash×15` | 已调用 15 次 |
| `✓ Write` | 已调用 1 次（不显示 ×1） |

按固定顺序排列：Bash → Read → Edit → Write → Glob → Grep → Fetch → Search，其他工具自动追加。

**Agent 状态：**

Agent 在工具行中内联显示，区分运行中和已完成：

| 格式 | 说明 |
|------|------|
| `↑ Agent` | 1 个正在运行（黄色） |
| `↑ Agent×2` | 2 个正在运行（黄色） |
| `✓ Agent×3` | 3 个已完成（绿色） |
| `↑ Agent ✓ Agent×2` | 1 个运行中 + 2 个已完成 |

运行中的 Agent 完成后会自动合并到 ✓ 计数中。

## 安装

```bash
git clone https://git.woa.com/origuo/codebuddy-statusbar.git ~/.codebuddy/statusline
bash ~/.codebuddy/statusline/install.sh
```

安装脚本会自动：
1. 克隆/更新插件文件
2. 创建缓存目录
3. 在 `~/.codebuddy/settings.json` 中配置 `statusLine`（已有则跳过）

安装后重启 CodeBuddy Code 会话即可生效。

## 自动更新

完整版 `statusline.py` 内置了**每天最多一次**的 `git pull` 自动更新机制：

- 脚本运行时检查 `~/.codebuddy/statusline-cache/.last-update-check` 标记文件
- 距上次检查超过 24 小时，则在后台 `double-fork` 启动 `git -C <插件目录> pull --ff-only --quiet`
- 主进程**立即返回**，不阻塞状态栏渲染（即使无网络也不会卡顿）
- 失败静默：非 git 仓库、无远程、本地有冲突修改等情况都安全跳过
- 标记文件**先于 pull 写入**，避免 git 卡死时反复重试

如不希望自动更新，可在 `git` 子命令失效（如断网或权限不足）时它本就什么都不做；或将插件目录改名 `.git` 为 `.git.disabled` 即可永久禁用。

## 卸载

```bash
bash ~/.codebuddy/statusline/uninstall.sh
```

## 版本选择

### 完整版（默认）

双行显示：第一行为 Context 进度条、Token 用量、费用等；第二行为工具调用统计。通过增量解析会话 transcript 文件获取 Token 和工具数据，Context 进度直接读取 CodeBuddy 提供的 `context_window` 字段。

```json
"statusLine": {
    "command": "python3 ~/.codebuddy/statusline/statusline.py"
}
```

### 轻量版

单行显示，只使用 statusline 自带的 `cost` 和 `context_window` 字段，不解析 transcript 文件，更快但信息较少（仅显示 Cost、Time、代码变更）。

```json
"statusLine": {
    "command": "python3 ~/.codebuddy/statusline/statusline-lite.py"
}
```

切换方法：编辑 `~/.codebuddy/settings.json` 中的 `statusLine.command` 字段。

## 详细报告

随时运行查看按模型分组的详细 Token 报告：

```bash
python3 ~/.codebuddy/statusline/cost-detail.py
```

输出示例：

```
================================================================================
  CodeBuddy Code - Cost & Token Usage Report
================================================================================

  GLM-5.1:
    Requests:     29
    Input:        2,352,968 (2.4M)
    Output:       10,693 (10.7K)
    Cache Read:   2,227,648 (2.2M)
    Reasoning:    952
    Credits:      67.20

--------------------------------------------------------------------------------
  TOTALS:
    Requests:     29
    Input:        2,352,968 (2.4M)
    Output:       10,693 (10.7K)
    Cache Read:   2,227,648 (2.2M)
    Reasoning:    952
    Credits:      67.20
================================================================================
```

## 性能

完整版 `statusline.py` 经过精心优化，每次调用的开销极低：

| 路径 | 耗时 |
|------|------|
| Cold start（首次解析整个 transcript） | ~1.4ms |
| Warm run（无新数据，steady state） | ~55µs |

优化技术：

- **增量计算**：首次全量解析 transcript，后续只读取新增字节
- **统一缓存**：所有状态（累计 stats、主 transcript offset、子 agent offsets）合并到一个 JSON 文件，每次只需 1 次文件读取
- **跳过空 open**：缓存的 offset 等于文件大小时跳过 `open()`，仅 `stat()` 即可判断
- **字符串预过滤**：用 `'function_call' in line` 等廉价检查跳过无关行，避免 `json.loads` 解析每条
- **跳写优化**：steady state 下不重写缓存文件
- **延迟清理**：旧缓存清理仅约 1% 概率执行（~30 秒一次），避免每帧都 listdir
- **零外部依赖**：不导入 `random`、`subprocess` 等模块（cold start 减少 ~1.2ms）
- **文件截断检测**：缓存的 offset 超出文件大小时自动从头解析
- **崩溃安全**：stats 先写、offsets 后写，crash 时最坏只是少量重复计数，永不丢失数据

Context 进度条直接从 statusline JSON 的 `context_window` 字段读取，无需额外计算。
缓存按 session_id 隔离，存储在 `~/.codebuddy/statusline-cache/`，超过 7 天自动清理。

### 子 Agent Token 统计

完整版会自动扫描 `subagents/` 目录下的子 Agent transcript 文件，将其 token 用量合并到主统计中。这样状态栏显示的 In/Out/Cache/Credits 包含了所有子 Agent 的消耗，而不仅仅是主 Agent 的。

> 注意：`In` 字段（即 `inputTokens`）已包含 `Cache` 命中部分，与 CodeBuddy 系统自带显示一致。`Cache` 是 `In` 的子集，不应将两者相加。

## 工作原理

1. CodeBuddy Code 每 300ms 通过 stdin 向 statusline 脚本发送 JSON 数据，包含 `model`、`cost`、`context_window`、`transcript_path`、`session_id` 等字段
2. `context_window` 字段提供 `used_percentage`、`context_window_size`、`current_usage`，直接用于渲染进度条
3. 完整版脚本增量读取 `transcript_path` 指向的 JSONL 文件，解析 `function_call` 条目统计工具调用，解析 `providerData.usage` / `providerData.rawUsage` 获取 Token 明细
4. 同时扫描 `<session_id>/subagents/*.jsonl` 子 Agent transcript，并将其用量合并入总计
5. 轻量版脚本仅使用 statusline JSON 自带的 `cost` 和 `context_window` 字段，不读取文件
6. 两种版本都支持 ANSI 颜色码，在终端中高亮显示
7. 完整版每天还会尝试一次后台 `git pull`，保持插件最新

## 依赖

- Python 3
- CodeBuddy Code v1.16.0+

## 文件结构

```
~/.codebuddy/statusline/
├── .codebuddy-plugin/
│   └── plugin.json          # 插件元数据
├── statusline.py            # 完整版 statusline 脚本（增量解析 + 子 Agent 聚合 + 自动更新）
├── statusline-lite.py       # 轻量版 statusline 脚本
├── cost-detail.py           # 详细报告脚本（含子 Agent token 聚合）
├── test_statusline.py       # 单元测试（90+ 用例）
├── commands/
│   └── cost-detail.md       # 斜杠命令定义
├── install.sh               # 安装脚本
├── uninstall.sh             # 卸载脚本
├── CHANGELOG.md             # 版本变更记录
└── README.md
```

## 测试

```bash
python3 -m unittest discover -s ~/.codebuddy/statusline -p "test_*.py" -v
```

涵盖增量解析、子 Agent 聚合、文件截断处理、崩溃安全、缓存语义、自动更新等场景。

## License

MIT
