---
description: "Show detailed cost and token usage breakdown by model"
argument-hint: ""
---

Read the current session transcript file and show a detailed cost/token breakdown.

Use Bash to run this command:
```bash
python3 ${CODEBUDDY_PLUGIN_ROOT}/cost-detail.py
```

The script reads the transcript from the environment variable or from the transcript_path in the hook input. Parse the output and present it in a clear, formatted table to the user showing:
- Per-model token usage (input, output, cache read, reasoning)
- Total requests per model
- Credits consumed
- Total session cost and duration
