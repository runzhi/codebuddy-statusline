# AGENTS.md

供 AI 开发助手阅读，帮助快速理解项目架构与约束。

## 项目概述

CodeBuddy Code 的 statusline 插件。stdin 接收状态 JSON → 增量解析 transcript → 渲染三行状态栏。核心约束：**每次调用是新进程，调用周期不固定（数秒到数分钟），必须低开销**。

## 文件结构

| 文件 | 职责 |
|------|------|
| `statusline.py` | 主脚本（增量解析 + 子 Agent 聚合 + git 检测 + 自动更新） |
| `cost-detail.py` | 按模型分组的详细报告 |
| `test_statusline.py` | 单元测试（164 用例） |
| `install.sh`/`install.ps1` | 安装脚本（内外网双地址） |
| `uninstall.sh`/`uninstall.ps1` | 卸载脚本 |
| `commands/` | 斜杠命令定义 |
| `scripts/sync-public.sh` | master → github/main 同步 |

## 调用机制

CodeBuddy 的 `StatusLineManager` 事件驱动 + 300ms 防抖。事件源：`sessionSubject`、`resultSubject`（最频繁）、`permissionModeSubject`、`settingsManager.onDidChange`、`costService.onDidChangeCost`。

**300ms 是防抖窗口上限，非固定调用周期**——空闲时可能数分钟不触发。流程：事件 → `scheduleUpdate()`(300ms 防抖) → `collectStatusLineData()` → stdin 传 JSON → `setStatusLine()`。

## 关键约束（改代码必看）

- **null 安全**：`model`/`cost`/`context_window` 等字段可能是 `null`，统一用 `.get('key') or {}` 防护。
- **`In` 含 `Cache`**：`inputTokens` 已包含缓存命中部分，两者是包含关系，不可相加。
- **CACHE_VERSION**：修改 `new_stats()` 结构或计数逻辑时必须升级，强制旧缓存失效。改后检查：① 测试数量；② `cost-detail.py` 是否需同步。
- **截断安全**：transcript 截断时丢弃所有缓存全量重解析，避免 double-counting；读到无换行的部分行时不推进 offset。
- **subprocess 两处用途**：`get_git_info()` 同步 fork（渲染用，不缓存保证实时）；`maybe_auto_update()` 后台异步（更新插件自身，每天一次）。不可混用。
- **截断显示内容**：用 `truncate_to_width`（CJK/ANSI 安全），禁止 `len()` + 切片。
- **脚本注入防护**：install/uninstall 脚本统一用临时文件 + `sys.argv` 传参，保持一致。
- **git 分支解析**：`_GIT_BRANCH_LINE_RE` 解析 `git status --porcelain=v1 --branch` 第一行，新增分支格式需更新正则。

## stdin JSON（常用字段）

`session_id`、`transcript_path`、`model.display_name`、`cost.*`、`context_window.{used_percentage, context_window_size, current_usage.input_tokens}`、`workspace.current_dir`、`terminal_width`。完整字段见 `collectStatusLineData()`。

## 数据来源

- `context_window.*`：进度条，直接渲染
- `transcript_path` JSONL：`function_call`（工具统计）、`providerData.usage`/`rawUsage`（Token/Credits，Cache 来自 `inputTokensDetails[].cached_tokens` 或 `prompt_cache_hit_tokens`）、`summary`（`pre-compact`→Auto-Compact，`periodic`→Periodic）
- `subagents/*.jsonl`：合并 token/credit/tool（`running_agents`/`compact_count`/`periodic_count` 仅主 transcript）

## 性能

Cold start ~1.4ms，warm run ~55µs（不含 git fork 的数毫秒）。优化：增量计算、统一缓存文件、字符串预过滤跳过 `json.loads`、steady state 跳写、延迟清理（~1% 概率）。缓存按 session_id 隔离存于 `~/.codebuddy/plugins/data/statusline/cache/`，7 天清理。

## 测试

```bash
python3 -m unittest discover -s ~/.codebuddy/statusline -p "test_*.py" -v
```

覆盖：增量解析、子 Agent 聚合、截断处理、null 安全、缓存语义、自动更新、部分行竞态、原子写入、ANSI 截断。
