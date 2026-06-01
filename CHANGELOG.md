# Changelog

本文件记录 CodeBuddy Statusline 插件的所有重要变更。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.3.1] - 2026-06-01

### 变更 (Changed)

- **Compact 显示更名为 Auto-Compact**：状态栏中 `Compact×N` 改为 `Auto-Compact×N`，更准确地表达 `pre-compact` 事件是自动压缩而非手动触发。

## [1.3.0] - 2026-05-31

### 新增 (Added)

- **插件化改造**：支持通过 CodeBuddy 插件系统安装，SessionStart hook 自动配置 statusLine，无需手动编辑 settings.json。
- **SessionStart hook**：`hooks/hooks.json` 监听 `startup|resume|clear|compact` 事件，自动执行幂等 setup 脚本。
- **幂等 setup 脚本**：`scripts/setup.sh` 检查 python3、创建缓存目录、配置 statusLine 到 settings.json（已配置则跳过）。
- **`/statusline:setup` 命令**：手动触发配置或排查问题的斜杠命令。
- **`IS_PLUGIN_MODE` 标志**：`CODEBUDDY_PLUGIN_ROOT` 环境变量存在时自动启用，跳过 git pull 自动更新（由 marketplace 管理），git-clone 模式下照常每日自动更新。
- **Compact / Periodic 分别计数**：状态栏在 Context 进度条后分别显示 `Compact×N`（黄色，`pre-compact` 事件）和 `Periodic×M`（灰色，`periodic` 事件），两者均为 `summary` 类型条目但含义不同：Compact 是真正的 context 压缩，Periodic 是常规定期摘要。`initial-user-message` 和无 `source` 的摘要不计入。
- **null 安全处理**：CodeBuddy 可能对 `cost`、`model`、`context_window`、`current_usage`、`usage` 等字段发送 `null`。改用 `.get('key') or {}` 模式，确保 `None` 值不会触发 `AttributeError`。
- **全局崩溃兜底**：`main()` 外层添加 `try/except`，任何未捕获异常输出 `ERR:TypeName: message` 而非静默空白，便于排查。
- **旧缓存兼容**：加载缓存时自动 backfill 缺失字段、删除不在 `new_stats()` 中的废弃 key（防止 KeyError 崩溃）。

### 修复 (Fixed)

- **`usage=null` 导致 AttributeError**：`providerData.usage` 为 JSON `null` 时，`pd.get('usage', {})` 返回 `None` 而非 `{}`，后续 `None.get()` 崩溃。改为 `pd.get('usage') or {}`。
- **`prompt_cache_hit_tokens=0` 被吞掉**：`raw_usage.get('prompt_cache_hit_tokens', cache_read) or cache_read` 在 API 显式返回 0 时回退到 `inputTokensDetails` 计算值。改为先检查 key 是否存在再取值。
- **Corrupted cache 非 dict `tool_counts` 崩溃**：缓存文件中 `tool_counts` 字段为非 dict 值时，合并循环 `stats[key].get(k, 0)` 抛 `AttributeError`。增加 `isinstance` 防护。
- **旧缓存 KeyError 崩溃**：删除 `total_input`/`total_output` 等字段后，磁盘上旧缓存仍包含这些 key。增量合并时 `delta[key]` 抛出 KeyError 导致脚本静默崩溃。修复：加载缓存后删除不在 `new_stats()` 中的废弃 key。
- **子 Agent 截断 double-counting**：子 Agent transcript 截断时，旧的 `pass` 无操作导致旧数据保留、新全量解析叠加其上，造成 token/credit 重复计数。修复：任何 transcript 截断触发全量重解析（丢弃所有缓存 stats）。
- **delta 合并遍历方向**：合并循环从遍历 `stats` keys 改为遍历 `delta` keys，避免 `stats` 中残留意外 key 时 `delta[key]` 抛 KeyError。
- **`.jsonl` 后缀切片错误**：`[:-5]` 仅去掉 5 个字符（`.json`），实际 `.jsonl` 为 6 个字符。修正为 `[:-6]`。
- **CACHE_VERSION 未升级导致旧缓存误用**：修改 compact 计数逻辑后未同步升级 `CACHE_VERSION`，旧缓存中 `compact_count` 不准确但不会被判定为过期。修复：每次修改 `new_stats()` 结构或计数逻辑时同步升级 `CACHE_VERSION`（当前 v5）。

### 变更 (Changed)

- **统一缓存路径**：CACHE_DIR 统一为 `{PLUGIN_DATA}/cache`（插件模式：`${CODEBUDDY_PLUGIN_DATA}/cache`，git-clone 模式：`~/.codebuddy/plugins/data/statusline/cache`），不再使用旧的 `~/.codebuddy/statusline-cache`。
- **plugin.json 补全元数据**：添加 `description_en`、`homepage`、`repository`、`license`、`commands`、`hooks` 字段。
- **cost-detail 命令路径**：`commands/cost-detail.md` 改用 `${CODEBUDDY_PLUGIN_ROOT}` 环境变量。
- **In/Out/Cache/Credits 恢复包含子 Agent**
- **子 Agent 解析策略调整**：`compact_count`、`periodic_count` 不计入子 Agent（仅主 context 的压缩/摘要事件有意义）；`running_agents` 仍仅从主 transcript 追踪。
- **Cache 命中提取**：`add_line_to_stats` 从 `providerData.usage.inputTokensDetails[].cached_tokens` 提取 `total_cache_read`，并兼容 `providerData.rawUsage.prompt_cache_hit_tokens`。

## [1.2.0] - 2026-05-30

这是一次大幅度的功能、稳定性与性能升级。

### 新增 (Added)

- **子 Agent Token 聚合**：自动扫描 `<session_id>/subagents/*.jsonl` 中所有子 Agent 的 transcript，将其 token 用量、工具调用、Credits 合并到主统计中。此前子 Agent 的开销完全不计入状态栏。
- **自动更新**：`statusline.py` 内置每天最多一次的后台 `git pull --ff-only` 更新机制。通过 double-fork 完全脱离主进程，对状态栏渲染零影响；失败静默（无网络、非 git 仓库等都安全跳过）。
- **CHANGELOG.md**：本文件，用于记录后续版本变更。
- **完整单元测试套件**：从 48 个测试扩展到 90+ 个测试，覆盖增量解析、子 Agent 聚合、文件截断、崩溃安全、缓存语义、自动更新等场景。

### 修复 (Fixed)

- **`running_agents` 跨增量块永远不递减的 bug**：`function_call` 和对应的 `function_call_result` 分属不同增量块时，`max(0, 0-1)=0` 会吞掉递减，导致 `↑ Agent` 永远卡在 1+。改为允许 delta 为负，仅在 gauge 计算时 clamp。
- **缓存写入顺序导致崩溃后数据丢失**：之前 offset cache 先于 stats cache 写入，进程在两次写入之间崩溃会导致数据永久丢失。改为 stats 先写、offsets 后写，崩溃时最坏只是少量重复计数。
- **文件截断未检测**：transcript 文件被重写或截断时，旧的 offset 超出文件大小会导致全部新数据被静默跳过。新增 `getsize` 检查，offset > file_size 时自动从 0 重新解析。
- **`cleanup_old_caches` 误删当前 session 的 offset cache**：之前只保护 `{session_id}.json`，未保护 `{session_id}_main_offset.json` / `{session_id}_sub_offset_*.json`，可能导致缓存被清后重复计数。改为按 session_id 前缀整体保护。
- **空文件写入无效 cache**：之前空 transcript 在 offset 0 时仍会写入 `{"offset": 0}` cache 文件。改为仅在确实读到数据时才写入。
- **损坏的 cache 字段类型崩溃**：`{"offset": "abc"}` 这类损坏 cache 会导致 `f.seek` TypeError。新增类型校验，非数字直接重置为 0。
- **subagents 目录中非 .jsonl 文件被尝试打开**：依赖 `os.listdir` 返回的条目可能是目录或非 .jsonl 文件。新增 `os.path.isfile` 显式检查。

### 性能 (Performance)

| 路径 | v1.1 | v1.2 | 改善 |
|------|------|------|------|
| Cold start（首次解析整个 transcript） | ~5.5ms | **~1.4ms** | 4× |
| Warm run（无新数据，steady state） | ~445µs | **~55µs** | 8× |

具体优化：

- **统一缓存文件**：将 stats、主 offset、所有子 agent offsets 合并到一个 JSON 文件，每次仅 1 次文件读取（v1.1 是 2+N 次）。
- **跳过空 open**：缓存的 offset 等于文件大小时仅 `stat()` 即可判断无新数据，跳过 `open()`/`seek()`/`iterate()` 全部 syscall。
- **字符串预过滤**：`json.loads` 前先用 `'function_call' in line` / `'providerData' in line` 等廉价子串检查筛掉 ~75% 不相关的行（assistant text、tool result 等）。
- **跳写优化**：steady state 下不重写缓存文件（每次都写会浪费 I/O 并扩大崩溃过度计数窗口）。
- **延迟清理**：`cleanup_old_caches` 改为约 1% 概率执行（~30 秒一次），避免每帧都做 O(n) listdir。
- **移除 `random` import**：用 `time.time_ns() % 97 < 1` 替代 `random.random() < 0.01`，cold start 减少 ~1.2ms。

### 变更 (Changed)

- **`In` 字段语义说明**：`In` 显示 `inputTokens` 总数（含 cache hit 部分），与 CodeBuddy 系统自带显示对齐。`Cache` 是 `In` 的子集，不应将两者相加（README 已加注释）。
- **`_parse_single_transcript_incremental` 签名变更**：现在接受 `start_offset: int` 参数，返回 4 元组 `(delta, new_offset, truncated, has_new_data)`。不再自己读写 cache，由调用方统一管理。
- **`save_cache(session_id, stats, main_offset, sub_offsets)` 签名变更**：参数语义改为统一缓存格式。
- **`cost-detail.py` 也聚合子 Agent**：与 statusline 一致地扫描 `subagents/` 子目录。

### 兼容性 (Compatibility)

- 升级后旧的 split offset cache 文件（`{session_id}_main_offset.json`、`{session_id}_sub_offset_*.json`）会保留但不再被读取。`cleanup_old_caches` 7 天后会自动清理。
- 第一次升级后会重新全量解析 transcript（cold start ~1.4ms），后续恢复增量。

## [1.1.0] - 2026-05-29

### 新增

- 增量解析模式：首次全量解析后只读取新增行
- Context 进度条
- 工具调用统计行
- Agent 运行/完成状态显示

## [1.0.0] - 2026-05-27

- 初始版本
- 基本的 token、cost、duration 显示
