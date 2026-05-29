# CodeBuddy Cost Monitor

CodeBuddy Code 的实时成本和 Token 用量监控工具，类似于 Claude Hub，在状态栏实时显示当前会话的费用、Token 用量、Context 进度条、请求数等信息。

## 效果预览

状态栏实时显示：

```
GLM-5.1 | ▕████▍     ▏44% 56.7K/128.0K | In:2.4M Out:10.7K Cache:2.2M Think:952 | Req:29 | Cost:$0.023 | Credits:67.20 | Time:45s | +156/-23
```

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

## 快速安装

```bash
# 方式一：从 Git 仓库安装
git clone https://git.woa.com/origuo/codebuddy-statusbar.git ~/.codebuddy/cost-monitor
bash ~/.codebuddy/cost-monitor/install.sh

# 方式二：一键安装
curl -fsSL https://git.woa.com/origuo/codebuddy-statusbar/-/raw/master/install.sh | bash
```

安装后重启 CodeBuddy Code 会话即可生效。

## 卸载

```bash
bash ~/.codebuddy/cost-monitor/uninstall.sh
```

## 版本选择

### 完整版（默认）

显示 Context 进度条、Token 用量、Cache、Reasoning、Credits 等详细信息。通过增量解析会话 transcript 文件获取 Token 数据，Context 进度直接读取 CodeBuddy 提供的 `context_window` 字段。

```json
"statusLine": {
    "command": "python3 ~/.codebuddy/cost-monitor/statusline.py"
}
```

### 轻量版

只使用 statusline 自带的 `cost` 和 `context_window` 字段，不解析 transcript 文件，更快但信息较少（仅显示 Context 进度、Cost、Time、代码变更）。

```json
"statusLine": {
    "command": "python3 ~/.codebuddy/cost-monitor/statusline-lite.py"
}
```

切换方法：编辑 `~/.codebuddy/settings.json` 中的 `statusLine.command` 字段。

## 详细报告

随时运行查看按模型分组的详细 Token 报告：

```bash
python3 ~/.codebuddy/cost-monitor/cost-detail.py
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
- 缓存上次读取位置和累计统计数据到 `~/.codebuddy/cost-monitor-cache/`
- 按 session_id 隔离缓存，切换会话自动清理旧缓存
- 缓存命中后约 35ms 完成，远低于 statusline 300ms 更新间隔

## 工作原理

1. CodeBuddy Code 每 300ms 通过 stdin 向 statusline 脚本发送 JSON 数据，包含 `model`、`cost`、`context_window`、`transcript_path`、`session_id` 等字段
2. `context_window` 字段提供 `used_percentage`、`context_window_size`、`current_usage`，直接用于渲染进度条
3. 完整版脚本额外读取 `transcript_path` 指向的 JSONL 文件，增量解析 `providerData.rawUsage` 获取 Token 明细
4. 轻量版脚本仅使用 statusline JSON 自带的 `cost` 和 `context_window` 字段，不读取文件
5. 两种版本都支持 ANSI 颜色码，在终端中高亮显示

## 依赖

- Python 3
- CodeBuddy Code v1.16.0+

## 文件结构

```
~/.codebuddy/cost-monitor/
├── .codebuddy-plugin/
│   └── plugin.json          # 插件元数据
├── statusline.py            # 完整版 statusline 脚本（增量解析 + Context 进度条）
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
