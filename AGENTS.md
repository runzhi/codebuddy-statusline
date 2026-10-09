# AGENTS.md

供 AI 开发助手阅读，帮助快速理解项目架构与约束。

## 项目概述

CodeBuddy Code 的 statusline 插件。stdin 接收状态 JSON → 增量解析 transcript → 渲染三行状态栏。核心约束：**每次调用是新进程，调用周期不固定（数秒到数分钟），必须低开销**。

## 文件结构

| 文件 | 职责 |
|------|------|
| `statusline.py` | 入口（薄编排）：读 stdin → `parsing.parse_transcript_incremental` → `render.build_statusline` → 打印 → `stats.maybe_auto_update` |
| `formatting.py` | 纯格式化与宽度/截断：`format_tokens/cost/duration`、`make_progress_bar`、`truncate_to_width`、`_tty_columns/_windows_columns`、`get_statusline_width(_from_input)`，以及颜色/费用常量 |
| `gitinfo.py` | git 分支/状态检测：`get_git_info` / `format_git_info` |
| `stats.py` | stats 结构与缓存持久化：`new_stats`/`load_cache`/`save_cache`/`cleanup_old_caches`/`maybe_auto_update` + `CACHE_VERSION`/`_LAST_KEYS`/`CACHE_DIR` |
| `parsing.py` | transcript 增量解析：`parse_transcript_incremental`/`add_line_to_stats`/`_extract_call_summary`，共享 `_read_transcript_delta`/`_collect_deltas`/`_merge_delta`（主/sub 解析去重） |
| `render.py` | 渲染：`format_tools`/`format_recent_calls`/`build_statusline`（三行装配）+ 布局配置 `load_layout_config`/`resolve_layout`/`RENDERERS`（块渲染器与顺序） |
| `config.py` | 布局配置读写（`/statusline:config` 命令后端）：`hide`/`show`/`move`/`enable`/`disable`/`reset`/`list`，原子写入 |
| `cost-detail.py` | 按模型分组的详细报告（独立脚本，需手动与 `parsing.py` 的 usage 提取逻辑同步） |
| `test_*.py` | 按模块拆分的单元测试（共 231 用例）：`test_formatting`/`test_gitinfo`/`test_stats`/`test_parsing`/`test_render`/`test_config` + `test_statusline`（入口集成冒烟） |
| `install.sh`/`install.ps1` | 安装脚本（内外网双地址） |
| `uninstall.sh`/`uninstall.ps1` | 卸载脚本 |
| `commands/` | 斜杠命令定义 |

## 调用机制

CodeBuddy 的 `StatusLineManager` 事件驱动 + 300ms 防抖。事件源：`sessionSubject`、`resultSubject`（最频繁）、`permissionModeSubject`、`settingsManager.onDidChange`、`costService.onDidChangeCost`。

**300ms 是防抖窗口上限，非固定调用周期**——空闲时可能数分钟不触发。流程：事件 → `scheduleUpdate()`(300ms 防抖) → `collectStatusLineData()` → stdin 传 JSON → `setStatusLine()`。

## 关键约束（改代码必看）

- **null 安全**：`model`/`cost`/`context_window` 等字段可能是 `null`，统一用 `.get('key') or {}` 防护。
- **模型元数据不全**：部分模型（如 hy4-dev）无最大上下文数据，`context_window_size=0` 且 `used_percentage` 为 `null`，但 `current_usage.input_tokens` 仍有值。此时 context_bar 回退显示当前用量（而非整块消失），不可把「无比例」当作「无数据」。
- **`current_usage` 三段互不重叠**：当前上下文长度 = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`（Claude Code 协议）。`input_tokens` 只是未命中缓存的部分，缓存命中高时可能为 0，**不可只读它**。三段全缺失时才用 `百分比 × 上下文窗口大小` 兜底推导。
- **`In` 含 `Cache`**：`inputTokens` 已包含缓存命中部分，两者是包含关系，不可相加。
- **CACHE_VERSION**：修改 `new_stats()` 结构或计数逻辑时必须升级，强制旧缓存失效。改后检查：① 测试数量；② `cost-detail.py` 是否需同步。
- **截断安全**：transcript 截断（缓存 offset 超出文件长度）在读取时检测，一旦发现即丢弃所有缓存全量重解析，避免 double-counting；每个 transcript 每轮只 `getsize` 一次；读到无换行的部分行时不推进 offset。
- **subprocess 两处用途**：`get_git_info()` 同步 fork（渲染用，不缓存保证实时）；`maybe_auto_update()` 后台异步（更新插件自身，每天一次）。不可混用。
- **截断显示内容**：用 `truncate_to_width`（CJK/ANSI 安全），禁止 `len()` + 切片。
- **禁止用连续空格对齐/填充**：host 的 `TextWrapBox` 按 `/\S+/` 分词后以单空格重排，连续空格会被折叠成一个（进度条因此只剩 1 格宽）。需要占位时用可见字符，如进度条空槽用 `░`。
- **脚本注入防护**：install/uninstall 脚本统一用临时文件 + `sys.argv` 传参，保持一致。
- **git 分支解析**：`_GIT_BRANCH_LINE_RE` 解析 `git status --porcelain=v1 --branch` 第一行，新增分支格式需更新正则。

## stdin JSON（常用字段）

`session_id`、`transcript_path`、`model.display_name`、`cost.*`、`context_window.{used_percentage, context_window_size, current_usage.input_tokens}`、`workspace.current_dir`、`terminal_width`。完整字段见 `collectStatusLineData()`。

## 数据来源

- `context_window.*`：进度条，直接渲染
- `transcript_path` JSONL：`function_call`（工具统计）、`providerData.usage`/`rawUsage`（Token/Credits，Cache 来自 `inputTokensDetails[].cached_tokens` 或 `prompt_cache_hit_tokens`）、`message`+`isCompactInternal`+`isSummary`（Compact）、`summary`+`periodic`（Periodic）
- `subagents/*.jsonl`：合并 token/credit/tool（`running_agents`/`compact_count`/`periodic_count` 仅主 transcript）

## 性能

端到端单次调用约 38ms，构成：Python 解释器启动 ~18ms（不可优化）、模块导入 ~4.6ms（其中 `subprocess` 占 5.1ms 累计）、`git status` fork ~13ms、transcript 增量解析 ~0.2ms（稳态）、渲染 <0.5ms。
下面提到的「warm run ~55µs」只统计 Python 侧解析+渲染的工作量，**不含**解释器启动与 git fork，不可当作端到端耗时引用。
优化：增量计算、统一缓存文件、字符串预过滤跳过 `json.loads`、steady state 跳写、延迟清理（~1% 概率）、每轮每个 transcript 只 stat 一次（截断检测并入读取）、子 Agent 列表一次性物化（单次 `os.listdir`）。缓存按 session_id 隔离存于 `~/.codebuddy/plugins/data/statusline/cache/`，7 天清理。

## 测试

```bash
python3 -m unittest discover -s ~/.codebuddy/statusline -p "test_*.py" -v
```

覆盖：增量解析、子 Agent 聚合、主/子 Agent 截断处理、null 安全、缓存语义、自动更新、部分行竞态、原子写入、ANSI 截断、布局配置解析。
