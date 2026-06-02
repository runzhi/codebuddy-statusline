# CodeBuddy Statusline

CodeBuddy Code 的实时状态栏工具，类似于 Claude Hud，在状态栏实时显示当前会话的 Context 进度条、Token 用量、工具调用、费用等信息。

## 效果预览

状态栏分三行实时显示：

```
GLM-5.1 | ▕████▍     ▏44% 56.7K/128.0K Auto-Compact×2 Periodic×3 | In:2.4M Out:10.7K Cache:2.2M Think:952 | Req:29 | Cost:$0.023 | Credits:67.20 | Time:45s | +156/-23
Tools: ✓ Bash×15 | ✓ Read×2 | ✓ Edit×2 | ✓ Agent | ↑ Agent×2
Recent: In:3.2K Out:856 Cache:2.1K(65%) Credits:1.50 Cost:$0.003 | Bash apt-get install -y tmux | Read /data/app/main.py | Edit /data/app/config.yaml
```

### 第一行：概览

| 字段 | 说明 |
|------|------|
| `GLM-5.1` | 当前模型名称 |
| `▕████▍     ▏44%` | Context 进度条（绿 < 50%，黄 < 80%，红 >= 80%） |
| `56.7K/128.0K` | 当前 Context 用量 / 窗口上限 |
| `Auto-Compact×2` | Context 自动压缩次数（`pre-compact` 事件，黄色，详见下方说明） |
| `Periodic×3` | Context 阶段摘要次数（`periodic` 事件，灰色，详见下方说明） |
| `In:2.4M` | 输入 Token 数（自动缩写 K/M） |
| `Out:10.7K` | 输出 Token 数 |
| `Cache:2.2M` | 缓存命中 Token 数 |
| `Think:952` | 推理/思考 Token 数 |
| `Req:29` | API 请求次数 |
| `Cost:$0.023` | 费用（按金额变色：绿 < $0.01，黄 < $0.1，红 >= $0.1） |
| `Credits:67.20` | 消耗 Credits |
| `Time:45s` | 会话耗时 |
| `+156/-23` | 代码增删行数 |

#### Auto-Compact vs Periodic 区别

两者都是 transcript 中的 `type: "summary"` 条目，但含义完全不同：

| | `Auto-Compact` (pre-compact) | `Periodic` (periodic) |
|---|---|---|
| **本质** | **自动压缩**——丢掉原文，换成摘要 | **打标签**——给对话分段加标题 |
| **触发时机** | Context 快满了，被迫压缩腾空间 | 对话进行一段后，主动做阶段性总结 |
| **Context 影响** | 用量明显下降（历史被替换为更短的摘要） | 用量不变或微增（摘要追加到对话中） |
| **触发条件** | Context 达到阈值（默认 200k tokens） | 每隔若干轮对话自动触发 |
| **可否手动触发** | 可以，`/compact` 命令 | 不可以 |

### 第二行：工具调用 & Agent 状态

标题 `Tools:` 使用暗淡样式显示。工具之间用 `|` 分隔。

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

### 第三行：最近交互详情 & Function Call

标题 `Recent:` 使用暗淡样式显示。左侧展示最近一次 API 交互的 Token 明细和 Cache 命中率，右侧展示最近 3 次工具调用的名称及参数摘要，用 `|` 分隔：

```
Recent: In:3.2K Out:856 Cache:2.1K(65%) Credits:1.50 Cost:$0.003 | Bash apt-get install -y tmux | Read /data/app/main.py | Edit /data/app/config.yaml
```

**最近一次交互详情：**

| 字段 | 说明 |
|------|------|
| `In:3.2K` | 最近一次请求的输入 Token 数 |
| `Out:856` | 最近一次请求的输出 Token 数 |
| `Cache:2.1K(65%)` | 最近一次请求的缓存命中 Token 数及命中率（命中数占输入数的百分比） |

仅在有 API 请求记录时显示，Cache 命中率仅在 Cache > 0 时显示。

**最近 Function Call：**

| 工具 | 提取字段 |
|------|----------|
| Bash | `command` |
| Read / Edit / Write | `file_path` |
| Grep | `pattern` + `path` |
| Glob | `pattern` |
| Agent | `description` |
| WebFetch | `url` |
| WebSearch | `query` |

优先使用 `argumentsDisplayText`，否则从 `arguments` JSON 提取对应字段。摘要超过 60 字符自动截断并添加 `…`。

## 安装

### 方式一：Git Clone 安装（推荐）

支持自动更新，推荐使用。

```bash
git clone https://git.woa.com/origuo/codebuddy-statusbar.git ~/.codebuddy/statusline
bash ~/.codebuddy/statusline/install.sh
```

**Windows PowerShell 用户：**

```powershell
git clone https://git.woa.com/origuo/codebuddy-statusbar.git "$env:USERPROFILE\.codebuddy\statusline"
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codebuddy\statusline\install.ps1"
```

安装脚本会自动：
1. 克隆/更新插件文件
2. 创建缓存目录
3. 在 `~/.codebuddy/settings.json` 中配置 `statusLine`（已有则跳过）

安装后即时生效，无需重启 CodeBuddy Code 会话。

### 方式二：Marketplace 插件安装

> 注意：Marketplace 安装模式不支持内置的 `git pull` 自动更新，需通过 `/plugin update` 手动更新。

```bash
# 1. 添加 four-harness 插件市场
/plugin marketplace add https://git.woa.com/four-harness/codebuddy-marketplace.git

# 2. 安装 statusline 插件
/plugin install statusline@four-harness

# 3. 手动执行 setup（配置 statusLine）
/statusline:setup
```

插件更新：

```bash
/plugin update statusline@four-harness
```

## 自动更新

Git-clone 安装模式下，完整版 `statusline.py` 内置了**每天最多一次**的 `git pull` 自动更新机制：

- 脚本运行时检查缓存目录下的 `.last-update-check` 标记文件
- 距上次检查超过 24 小时，则在后台 `double-fork` 启动 `git -C <插件目录> pull --ff-only --quiet`
- 主进程**立即返回**，不阻塞状态栏渲染（即使无网络也不会卡顿）
- 失败静默：非 git 仓库、无远程、本地有冲突修改等情况都安全跳过
- 标记文件**先于 pull 写入**，避免 git 卡死时反复重试

**Marketplace 安装模式下自动更新会跳过**（`IS_PLUGIN_MODE=True`），需通过 `/plugin update statusline@four-harness` 手动更新。

如不希望自动更新，可在 `git` 子命令失效（如断网或权限不足）时它本就什么都不做；或将插件目录改名 `.git` 为 `.git.disabled` 即可永久禁用。

## 卸载

**Git Clone 安装模式：**

```bash
# macOS / Linux / Git Bash
bash ~/.codebuddy/statusline/uninstall.sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codebuddy\statusline\uninstall.ps1"
```

**Marketplace 插件安装模式：**

```bash
# 1. 移除 statusLine 配置
/statusline:uninstall

# 2. 卸载插件
/plugin uninstall statusline@four-harness

# 3. 清理缓存（可选）
rm -rf ~/.codebuddy/plugins/data/statusline
```

## 版本选择

### 完整版（默认）

双行显示：第一行为 Context 进度条、Token 用量、费用等；第二行为工具调用统计；第三行为最近一次交互的 In/Out/Cache 命中率及最近 3 次 function call 摘要。通过增量解析会话 transcript 文件获取 Token 和工具数据，Context 进度直接读取 CodeBuddy 提供的 `context_window` 字段。

```json
"statusLine": {
    "command": "python3 ${CODEBUDDY_PLUGIN_ROOT}/statusline.py"
}
```

Git-clone 安装用户使用：
```json
"statusLine": {
    "command": "python3 ~/.codebuddy/statusline/statusline.py"
}
```

切换方法：编辑 `~/.codebuddy/settings.json` 中的 `statusLine.command` 字段。

## 详细报告

随时运行查看按模型分组的详细 Token 报告：

```bash
# 插件模式
/statusline:cost-detail

# 或直接运行
python3 ${CODEBUDDY_PLUGIN_ROOT}/cost-detail.py

# Git-clone 模式
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
- **子 Agent 聚合**：扫描 `subagents/` 目录，增量解析并合并子 Agent 的 token/credit/tool 数据
- **统一缓存**：所有状态（累计 stats、主 transcript offset、子 agent offsets）合并到一个 JSON 文件，每次只需 1 次文件读取
- **跳过空 open**：缓存的 offset 等于文件大小时跳过 `open()`，仅 `stat()` 即可判断
- **字符串预过滤**：用 `'function_call' in line` 等廉价检查跳过无关行，避免 `json.loads` 解析每条
- **跳写优化**：steady state 下不重写缓存文件
- **延迟清理**：旧缓存清理仅约 1% 概率执行（~30 秒一次），避免每帧都 listdir
- **零外部依赖**：不导入 `random`、`subprocess` 等模块（cold start 减少 ~1.2ms）
- **文件截断检测**：缓存的 offset 超出文件大小时自动从头解析
- **崩溃安全**：全局 try/except 兜底，任何未捕获异常输出 `ERR:` 而非静默空白；旧缓存不兼容字段自动清理/backfill

Context 进度条直接从 statusline JSON 的 `context_window` 字段读取，无需额外计算。
缓存按 session_id 隔离，存储在 `~/.codebuddy/plugins/data/statusline/cache/`（插件模式）或相同路径（git-clone 模式），超过 7 天自动清理。

### 子 Agent Token 统计

完整版会自动扫描 `subagents/` 目录下的子 Agent transcript 文件，将其 token 用量合并到主统计中。这样状态栏显示的 In/Out/Cache/Credits 包含了所有子 Agent 的消耗，而不仅仅是主 Agent 的。

子 Agent 的 `running_agents`、`compact_count` 和 `periodic_count` 不计入主统计（前者由主 transcript 的 Agent 调用/返回追踪，后两者仅统计主 context 的压缩/摘要事件）。子 Agent 的工具调用、token 用量、Credits 则会合并。

当任何 transcript（主或子 Agent）被截断时，脚本会丢弃所有缓存 stats，对全部 transcript 做全量重新解析，以避免截断后 double-counting。

> 注意：`In` 字段（即 `inputTokens`）已包含 `Cache` 命中部分，与 CodeBuddy 系统自带显示一致。`Cache` 是 `In` 的子集，不应将两者相加。

## 工作原理

### 调用机制

CodeBuddy Code 内部通过 `StatusLineManager` 管理 statusline 更新，采用**事件驱动 + 300ms 防抖**机制：

**5 个事件源**，任一触发都会调度更新：

| 事件源 | 说明 | 触发频率 |
|--------|------|----------|
| `sessionSubject` | 会话变化（新建/切换） | 低 |
| `resultSubject` | AI 回复片段、工具调用结果返回 | **高**（最频繁） |
| `permissionModeSubject` | 权限模式切换 | 低 |
| `settingsManager.onDidChange` | 用户修改配置 | 低 |
| `costService.onDidChangeCost` | API 调用后费用更新 | 中 |

**防抖**：每次事件都调用 `scheduleUpdate()`，内部会 `clearTimeout` + `setTimeout(300ms)`，确保最多 300ms 更新一次。实际效果是：对话活跃期间，约每 300ms 调用一次 statusline 脚本。

**执行流程**：

```
事件触发 → scheduleUpdate() (300ms防抖) → updateStatusLine()
  → collectStatusLineData()   // 收集当前状态 JSON
  → executeStatusLine(data)   // 通过 stdin 传给脚本
  → setStatusLine(result)     // 更新 UI
```

### stdin JSON 数据结构

`collectStatusLineData()` 收集并传入脚本的完整 JSON：

| 字段 | 类型 | 说明 |
|------|------|------|
| `hook_event_name` | `string` | 固定值 `"Status"` |
| `session_id` | `string` | 当前会话 ID |
| `session_name` | `string` | 会话名称 |
| `transcript_path` | `string` | 会话 transcript JSONL 文件路径 |
| `cwd` | `string` | 当前工作目录 |
| `permission_mode` | `string` | 权限模式（`"default"` / `"plan"` 等） |
| `model.id` | `string` | 模型 ID |
| `model.display_name` | `string` | 模型显示名 |
| `workspace.current_dir` | `string` | 当前目录 |
| `workspace.project_dir` | `string` | 项目根目录 |
| `workspace.added_dirs` | `string[]` | 额外添加的目录 |
| `version` | `string` | CodeBuddy Code 版本号 |
| `output_style.name` | `string` | 输出风格名 |
| `cost.total_cost_usd` | `number` | 总费用（美元） |
| `cost.total_duration_ms` | `number` | 总耗时（毫秒） |
| `cost.total_api_duration_ms` | `number` | API 耗时（毫秒） |
| `cost.total_lines_added` | `number` | 新增代码行数 |
| `cost.total_lines_removed` | `number` | 删除代码行数 |
| `context_window` | `object` | 上下文窗口使用数据 |
| `context_window.used_percentage` | `number` | 使用百分比 |
| `context_window.context_window_size` | `number` | 窗口大小（tokens） |
| `context_window.current_usage.input_tokens` | `number` | 当前输入 tokens |
| `exceeds_200k_tokens` | `boolean` | 是否超过 200k tokens |
| `vim` | `object` | Vim 模式数据（如启用） |
| `team` | `object` | 团队协作数据（如启用） |

### 数据处理

1. CodeBuddy Code 每 300ms 通过 stdin 向 statusline 脚本发送上述 JSON 数据
2. `context_window` 字段提供 `used_percentage`、`context_window_size`、`current_usage`，直接用于渲染进度条
3. 完整版脚本增量读取 `transcript_path` 指向的 JSONL 文件，解析 `function_call` 条目统计工具调用，解析 `providerData.usage` / `providerData.rawUsage` 获取 Token 明细（Cache 来自 `inputTokensDetails[].cached_tokens`，并兼容 `prompt_cache_hit_tokens`），解析 `summary` 条目区分 `pre-compact`（Auto-Compact×N）和 `periodic`（Periodic×M）
4. 同时扫描 `<session_id>/subagents/*.jsonl` 子 Agent transcript，并将其 token/credit/tool 用量合并入总计（`running_agents`、`compact_count`、`periodic_count` 仅从主 transcript 追踪）
5. 轻量版脚本仅使用 statusline JSON 自带的 `cost` 和 `context_window` 字段，不读取文件
6. 两种版本都支持 ANSI 颜色码，在终端中高亮显示
7. 完整版每天还会尝试一次后台 `git pull`，保持插件最新

## 依赖

- Python 3
- CodeBuddy Code v1.16.0+

## 文件结构

```
codebuddy-statusbar/
├── .codebuddy-plugin/
│   └── plugin.json          # 插件元数据
├── commands/
│   ├── setup.md             # /statusline:setup 命令
│   ├── uninstall.md         # /statusline:uninstall 命令
│   └── cost-detail.md       # /statusline:cost-detail 命令
├── statusline.py            # 完整版 statusline 脚本（增量解析 + 子 Agent 聚合 + 自动更新）
├── cost-detail.py           # 详细报告脚本（含子 Agent token 聚合）
├── test_statusline.py       # 单元测试（104 用例）
├── install.sh               # Git-clone 模式安装脚本（macOS/Linux/Git Bash）
├── install.ps1              # Git-clone 模式安装脚本（Windows PowerShell）
├── uninstall.sh             # 卸载脚本（macOS/Linux/Git Bash）
├── uninstall.ps1            # 卸载脚本（Windows PowerShell）
├── CHANGELOG.md             # 版本变更记录
└── README.md
```

## 测试

```bash
python3 -m unittest discover -s ~/.codebuddy/statusline -p "test_*.py" -v
```

涵盖增量解析、子 Agent 聚合、AutoCompact 计数、null 安全、旧缓存兼容、文件截断处理、崩溃安全、缓存语义、自动更新、插件模式守卫等场景。

## License

MIT
