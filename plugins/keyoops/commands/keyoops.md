---
description: Manage keyoops languages — list, add, or remove keyboard-layout languages (auto-downloads dictionaries)
argument-hint: "[list | add <lang> | remove <lang>]  (lang: en he ar ru)"
allowed-tools: Bash
---

Run the keyoops language-management CLI with the user's arguments, then show its
output verbatim.

Execute exactly this (if the user gave no arguments, use `list`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" $ARGUMENTS
```

Notes:
- Supported language codes: `en`, `he`, `ar`, `ru`.
- `add <lang>` also auto-downloads that language's dictionary when needed.
- Changes take effect on the next prompt — no restart required.
- Do not do anything beyond running the command and reporting its output.
