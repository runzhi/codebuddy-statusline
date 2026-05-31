# Changelog

本文件记录 CodeBuddy Statusline 插件的所有重要变更。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.3.0] - 2026-05-31

### 新增 (Added)

- **AutoCompact 计数**：状态栏在 Context 进度条后显示 `AutoCompact×N`（黄色），追踪主 Agent 的自动 context 压缩事件。仅统计 `source` 为 `pre-compact` 的 `summary` 条目，忽略 `periodic`、`initial-user-message` 和无 `source` 的摘要。
- **null 安全处理**：CodeBuddy 可能对 `cost`、`model`、`context_window`、`current_usage` 等字段发送 `null`。改用 `.get('key') or {}` 模式，确保 `None` 值不会触发 `AttributeError`。
- **全局崩溃兜底**：`main()` 外层添加 `try/except`，任何未捕获异常输出 `ERR:TypeName: message` 而非静默空白，便于排查。
- **旧缓存兼容**：加载缓存时自动 backfill 缺失字段、删除不在 `new_stats()` 中的废弃 key（防止 KeyError 崩溃）。

### 修复 (Fixed)

- **旧缓存 KeyError 崩溃**：删除 `total_input`/`total_output` 等字段后，磁盘上旧缓存仍包含这些 key。增量合并时 `delta[key]` 抛出 KeyError 导致脚本静默崩溃（状态栏空白）。修复：加载缓存后删除不在 `new_stats()` 中的废弃 key。
- **子 Agent 截断 double-counting**：子 Agent transcript 截断时，旧的 `pass` 无操作导致旧数据保留、新全量解析叠加其上，造成 token/credit 重复计数。修复：任何 transcript 截断触发全量重解析（丢弃所有缓存 stats）。
- **delta 合并遍历方向**：合并循环从遍历 `stats` keys 改为遍历 `delta` keys，避免 `stats` 中残留意外 key 时 `delta[key]` 抛 KeyError。
- **`.jsonl` 后缀切片错误**：`[:-5]` 仅去掉 5 个字符（`.json`），实际 `.jsonl` 为 6 个字符。修正为 `[:-6]`。
- **AutoCompact 旧缓存误报**：曾按 `periodic` summary 误计 AutoCompact 的 v2 缓存会被判为过期并全量重算，避免未 compact 的会话继续显示 `AutoCompact×1`。

### 变更 (Changed)

- **In/Out/Cache/Credits 恢复包含子 Agent**：v1.2 中 In/Out/Cache 改为读取 stdin JSON 的 `context_window` 字段（仅含主 Agent），v1.3 恢复从 transcript 解析（含子 Agent），与 Credits 一致。Fallback 逻辑：transcript 无数据时回退到 stdin JSON。
- **子 Agent 解析策略调整**：`compact_count` 不计入子 Agent（仅主 context 的自动压缩事件有意义）；`running_agents` 仍仅从主 transcript 追踪。
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
