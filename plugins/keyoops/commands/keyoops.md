---
description: Manage keyoops languages — list, add, or remove keyboard-layout languages (auto-downloads dictionaries)
argument-hint: "[list | add [lang] | remove <lang>]  (lang: en he ar ru)"
allowed-tools: Bash, AskUserQuestion
---

Manage the user's keyoops languages by running its CLI. The script lives at
`${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py`. Supported codes: `en`, `he`, `ar`, `ru`.

Decide what to do from the arguments the user gave (`$ARGUMENTS`):

- **No arguments**, or `list` → run and show output:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" list
  ```

- **`add` with NO language specified** → first run `list` to see what's already
  configured, then use the **AskUserQuestion** tool to let the user pick a
  language to add. Offer these options: English (`en`), Hebrew (`he`),
  Arabic (`ar`), Russian (`ru`) — note in each description whether it's already
  configured. Then run, with the chosen code:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" add <code>
  ```

- **`add <lang>`**, **`remove <lang>`**, or **`list`** given explicitly → run the
  script with those arguments directly:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keyoops.py" $ARGUMENTS
  ```

Always show the command's output. `add` auto-downloads the language's dictionary
when needed. Changes take effect on the next prompt — no restart. Do nothing
beyond selecting the language (if needed) and running the command.
