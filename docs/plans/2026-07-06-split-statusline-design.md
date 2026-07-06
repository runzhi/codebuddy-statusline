# 拆分 statusline.py 设计文档

日期：2026-07-06
状态：已确认，待实现

## 目标

`statusline.py` 当前 1222 行，关注点混杂。本次拆分的**核心目标是提升可维护性**（文件太长难导航），同时**消除 `parse_transcript_incremental` 内的重复代码**（主/sub transcript 的读取循环与 merge 逻辑各复制一份，改一处极易漏另一处）。

约束（必须保留）：
- 每次调用是新进程，冷启动敏感 —— 本地模块 import 开销极小，需避免顶层重 import。
- install 脚本按文件名引用 `statusline.py` —— 入口文件名与 `python statusline.py` 调用方式不变。
- 行为保持：重构不改变输出与计数语义，`new_stats()` schema 不变，无需 bump `CACHE_VERSION`。

## 落地形态

同目录平铺模块（非 package），`statusline.py` 退化为薄编排入口。

| 新模块 | 搬入内容 | 职责 |
|------|-----------|------|
| `formatting.py` | `format_tokens`/`format_cost`/`format_duration`/`make_progress_bar`/`_char_width`/`_visible_len`/`truncate_to_width`/`_windows_columns`/`_tty_columns`/`get_statusline_width`/`get_statusline_width_from_input` + 颜色常量 (`NC/CYAN/BLUE/GREEN/RED/YELLOW/DIM`) | 纯格式化 + 宽度/截断（零依赖，最独立） |
| `gitinfo.py` | `get_git_info`/`format_git_info` | git 分支/状态 |
| `stats.py` | `new_stats`/`load_cache`/`save_cache`/`maybe_auto_update`/`cleanup_old_caches` + `CACHE_VERSION`/`_LAST_KEYS`/`CACHE_DIR` | stats 结构 + 缓存持久化/自动更新 |
| `parsing.py` | `parse_transcript_incremental`/`add_line_to_stats`/`_extract_call_summary` + 新增 `_read_transcript_delta()` / `_merge_delta()` | transcript 增量解析（消除重复） |
| `render.py` | `format_tools`/`format_recent_calls` + 新增 `build_statusline(input_data, stats) -> str`（从 `main()` 抽出的三行装配） | 渲染 |
| `statusline.py` | 仅 `main()`：读 stdin → `parse_transcript_incremental` → `build_statusline` → print → `maybe_auto_update` | 编排入口（约 40 行） |

### 重复代码合并（本次必做）

- **`_read_transcript_delta(path, offset) -> (delta, new_offset)`**：合并主 transcript（787–869）与 sub-agent（871–953）里逐字复制的读取循环（打开→seek→逐行读→跳过部分行→预过滤→`json.loads`→`add_line_to_stats`）。
- **`_merge_delta(stats, delta, is_main)`**：合并两份 merge 逻辑（846–863 vs 926–946）。`is_main=True` 时处理 `running_agents`/`compact_count`/`periodic_count`；sub-agent 传 `is_main=False` 跳过这几项，与现行为一致。

消除约 100+ 行重复，计数规则变更只改一处。

## 数据流向

```
main() [statusline.py]
  ├─ input_data = json.load(sys.stdin)
  ├─ stats = parse_transcript_incremental(transcript_path, session_id)   # from parsing
  ├─ output = build_statusline(input_data, stats)                        # from render
  ├─ print(output)
  └─ maybe_auto_update()                                                 # from stats (自带 try/except)
```
- `build_statusline` 内部直接调 `get_git_info`/`format_git_info`（来自 gitinfo）与 formatting 各函数，保持 `main()` 精简。
- `parsing` 从 `stats` 导入 `new_stats`/`load_cache`/`save_cache`/`cleanup_old_caches`/`_LAST_KEYS`/`CACHE_VERSION`。

## 错误处理

- `main()` 的全局安全网（`try/except` 打印 `ERR:`）保留在 `statusline.py`。
- `maybe_auto_update()` 调用处保留 try/except。
- `build_statusline` 保持 null 安全（`.get() or {}` 模式），由 `test_render.py::TestMainNullSafety` 覆盖。
- 部分行 / 截断 / 原子写逻辑原样迁移，不重写。

## 测试拆分（164 例 → 6 文件）

| 文件 | 来源测试类 |
|------|-----------|
| `test_formatting.py` | TestFormatTokens / Cost / Duration / MakeProgressBar / TruncateToWidth / GetStatuslineWidth(+FromInput) / TtyColumns / WindowsColumns |
| `test_gitinfo.py` | TestGitInfo / TestFormatGitInfo |
| `test_stats.py` | TestNewStats / TestCacheOperations / TestCleanupOldCaches / TestAutoUpdate / TestAtomicCacheWrite / cache 版本回填（原 859 行） |
| `test_parsing.py` | TestAddLineToStats / TestExtractCallSummary / TestIncrementalParsing / TestPartialLineRaceCondition |
| `test_render.py` | TestFormatTools / TestFormatToolEntry / TestFormatRecentCalls / **TestMainNullSafety（改为测 `build_statusline` 的 null 安全）** |
| `test_statusline.py` | 瘦身为 `main()` 入口集成冒烟测试（读 stdin → 输出三行） |

验证：`python3 -m unittest discover -s . -p "test_*.py" -v` 全部通过。

## 实现顺序

1. 新建 `formatting.py`（含颜色常量），`statusline.py` 改为 `from formatting import ...`，跑测试。
2. 抽 `gitinfo.py`、`stats.py`，更新 import，跑测试。
3. 抽 `parsing.py` 并合并重复（新增两个 helper），跑测试。
4. 抽 `render.py`（`build_statusline`），`main()` 精简，跑测试。
5. 拆分测试文件，删除/瘦身 `test_statusline.py`，全量跑测试。
6. 更新 AGENTS.md 文件结构表与 README 相关描述。

每步独立验证，保证可回退。
