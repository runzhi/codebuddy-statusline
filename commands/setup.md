---
description: "Install / re-run setup for the statusline"
argument-hint: "[repo-url]"
---

Set up the statusline by running the install script for the current
platform. This is a thin wrapper over `install.sh` / `install.ps1` — it can be
run again to re-install or repair the statusline after an update.

An optional `repo-url` argument (the git clone URL) is forwarded to the install
script. If omitted, the script auto-detects the URL from the existing clone or
falls back to the default repo.

Run the correct script for the platform:

```bash
# macOS / Linux
bash ~/.codebuddy/statusline/install.sh <repo-url>

# Windows (PowerShell)
powershell -File ~/.codebuddy/statusline/install.ps1 <repo-url>
```

After the script finishes, confirm the result to the user in one short line and
tell them to restart the session for the statusline to take effect.
