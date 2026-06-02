---
description: "Uninstall the statusline plugin"
argument-hint: ""
---

Uninstall the statusline plugin from CodeBuddy Code.

**Git Clone 安装模式**，运行卸载脚本：

```bash
bash ~/.codebuddy/statusline/uninstall.sh
```

**Marketplace 插件安装模式**，执行以下步骤：

1. 移除 statusLine 配置：
```bash
python3 -c "
import json
path = '$HOME/.codebuddy/settings.json'
with open(path) as f:
    settings = json.load(f)
if 'statusLine' in settings:
    cmd = settings['statusLine'].get('command', '')
    if 'statusline' in cmd:
        del settings['statusLine']
        with open(path, 'w') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write('\n')
        print('Removed statusLine config')
    else:
        print('statusLine exists but not statusline, skipping')
else:
    print('No statusLine config found')
"
```

2. 卸载插件：
```bash
/plugin uninstall statusline@four-harness
```

3. 清理缓存（可选）：
```bash
rm -rf ~/.codebuddy/plugins/data/statusline
```

卸载后重启会话即可生效。向用户确认卸载结果。
