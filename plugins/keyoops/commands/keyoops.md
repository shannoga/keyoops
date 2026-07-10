---
description: Manage keyoops — list/add/remove keyboard-layout languages, or set autoapply (skip-confirmation) modes
argument-hint: "[list | add [lang] | remove <lang> | autoapply [modes|off|default]]"
allowed-tools: Bash, AskUserQuestion
---

Manage keyoops by running its CLI. The script lives at
`${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py`. Language codes: `en`, `he`, `ar`, `ru`.

Decide what to do from the arguments the user gave (`$ARGUMENTS`):

- **No arguments**, or `list` → run and show output:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" list
  ```

- **`add` with NO language specified** → first run `list` to see what's already
  configured, then use the **AskUserQuestion** tool to let the user pick a
  language to add. Offer: English (`en`), Hebrew (`he`), Arabic (`ar`),
  Russian (`ru`) — note in each description whether it's already configured. Then
  run, with the chosen code:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" add <code>
  ```

- **`autoapply` with NO modes** → show the current setting:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" autoapply
  ```
  `autoapply` controls which permission modes apply a correction WITHOUT asking
  (Claude just announces it). Only pure single-language scrambles auto-apply;
  mixed messages always ask. Valid modes: `default`, `plan`, `acceptEdits`,
  `auto`, `dontAsk`, `bypassPermissions`. Set with e.g.
  `autoapply bypassPermissions,dontAsk`, `autoapply off`, or `autoapply default`.

- **Anything else** (`add <lang>`, `remove <lang>`, `list`,
  `autoapply <modes|off|default>`) → run the script with those arguments directly:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" $ARGUMENTS
  ```

Always show the command's output. `add` auto-downloads the language's dictionary
when needed. Changes take effect on the next prompt — no restart. Do nothing
beyond selecting the language / mode (if needed) and running the command.
