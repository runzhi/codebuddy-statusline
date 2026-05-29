# CodeBuddy Statusline

CodeBuddy Code 的实时状态栏工具，类似于 Claude Hub，在状态栏实时显示当前会话的 Context 进度条、Token 用量、工具调用、费用等信息。

## 效果预览

状态栏分两行实时显示：

```
GLM-5.1 | ▕████▍     ▏44% 56.7K/128.0K | In:2.4M Out:10.7K Cache:2.2M Think:952 | Req:29 | Cost:$0.023 | Credits:67.20 | Time:45s | +156/-23
✓ Bash×15 ✓ Read×2 ✓ Edit×2 ✓ Write
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

### 第二行：工具调用

| 格式 | 说明 |
|------|------|
| `✓ Bash×15` | 已调用 15 次 |
| `✓ Write` | 已调用 1 次（不显示 ×1） |

按固定顺序排列：Bash → Read → Edit → Write → Glob → Grep → Agent → Fetch → Search，其他工具自动追加。

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

- 使用**增量计算**：首次运行全量解析 transcript，后续只读取新增行
- Context 进度条直接从 statusline JSON 的 `context_window` 字段读取，无需额外计算
- 工具调用统计随 transcript 增量解析一起完成，无额外开销
- 缓存上次读取位置和累计统计数据到 `~/.codebuddy/statusline-cache/`
- 按 session_id 隔离缓存，自动清理超过 7 天的旧缓存
- 缓存命中后约 35ms 完成，远低于 statusline 300ms 更新间隔

## 工作原理

1. CodeBuddy Code 每 300ms 通过 stdin 向 statusline 脚本发送 JSON 数据，包含 `model`、`cost`、`context_window`、`transcript_path`、`session_id` 等字段
2. `context_window` 字段提供 `used_percentage`、`context_window_size`、`current_usage`，直接用于渲染进度条
3. 完整版脚本增量读取 `transcript_path` 指向的 JSONL 文件，解析 `function_call` 条目统计工具调用，解析 `providerData.rawUsage` 获取 Token 明细
4. 轻量版脚本仅使用 statusline JSON 自带的 `cost` 和 `context_window` 字段，不读取文件
5. 两种版本都支持 ANSI 颜色码，在终端中高亮显示

## 依赖

- Python 3
- CodeBuddy Code v1.16.0+

## 文件结构

```
~/.codebuddy/statusline/
├── .codebuddy-plugin/
│   └── plugin.json          # 插件元数据
├── statusline.py            # 完整版 statusline 脚本（增量解析 + Context 进度条 + 工具统计）
├── statusline-lite.py       # 轻量版 statusline 脚本
├── cost-detail.py           # 详细报告脚本
├── commands/
│   └── cost-detail.md       # 斜杠命令定义
├── install.sh               # 安装脚本
├── uninstall.sh             # 卸载脚本
└── README.md
```

## License

MIT
