---
description: "Configure or reconfigure the statusline plugin"
argument-hint: ""
---

Configure the statusline plugin for CodeBuddy Code.

Run the setup script to ensure everything is properly configured:

```bash
bash ~/.codebuddy/statusline/scripts/setup.sh
```

Show the output to the user. If successful, remind them to restart the session if this is a fresh installation.

If there are errors, help the user troubleshoot:
- Python 3 must be installed and available as `python3`
- The script is idempotent and safe to run multiple times
- It configures `statusLine` in `~/.codebuddy/settings.json`
