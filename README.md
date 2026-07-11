# keyoops

A Claude Code plugin that catches prompts typed with the **wrong keyboard layout**.

You meant to type English but the OS was on Hebrew, so `hello` came out as `יקךךם`?
`keyoops` notices, decodes it back to what you meant, and asks Claude to confirm
before doing anything:

> Looks like the wrong keyboard layout — did you mean: **hello add a button**? go with it?

Detection is pure code (no model tokens): it reverse-maps each character through
the keyboard layout and checks the result against a wordlist. If clean words fall
out, it flags; otherwise it stays silent. It **never blocks** — worst case is one
"did you mean…?" you decline.

## Install

```
/plugin marketplace add shannoga/keyoops
/plugin install keyoops@keyoops
```

The hook registers automatically — no `settings.json` editing. Restart your
session and it's active. Requires `python3` (preinstalled on macOS and most Linux).

## Configure — the `/keyoops` command

By default it catches **Hebrew-layout → English**. Manage which languages it
watches right from Claude Code — no file editing:

```
/keyoops list            # show your languages + dictionary status + auto-apply modes
/keyoops add             # pick a language from a menu (auto-downloads its dictionary)
/keyoops add ru          # …or name it directly
/keyoops remove ru       # remove Russian
/keyoops autoapply       # show/set which modes skip the confirmation (see below)
```

### Skipping confirmation (auto-apply)

Normally keyoops asks *"did you mean X? go with it?"* before using the decoded
text. In modes where you've opted into autonomy it can instead **apply the fix
and just tell you** — no yes/no. This is on for **`bypassPermissions`** by
default, and **only for pure single-language scrambles** (a message that mixes
languages always asks, to be safe).

```
/keyoops autoapply                          # show current modes
/keyoops autoapply bypassPermissions,dontAsk  # also skip in dontAsk mode
/keyoops autoapply off                      # always ask
/keyoops autoapply default                  # reset to [bypassPermissions]
```

Valid modes: `default`, `plan`, `acceptEdits`, `auto`, `dontAsk`,
`bypassPermissions`. (Same as the `auto_apply_modes` config key.)

Supported codes: `en`, `he`, `ar`, `ru`. Changes take effect on your **next
prompt** — no restart needed. The hook checks **every ordered pair** among your
languages: for each language your layout might have been ON, it decodes to each
*other* language and flags real words.

`add` automatically downloads the language's dictionary when one is needed (see
below), so `/keyoops add he` is all it takes to start catching Hebrew targets.

Everything is stored under `~/.claude/` (`keyoops.config.json` +
`keyoops-dicts/`), so plugin updates never overwrite your settings.

### Not using the plugin command?

You can run the same CLI directly on any install:

```bash
python3 "$(/plugin root keyoops)/scripts/keyoops.py" add ru
```

## Dictionaries (auto-downloaded)

English works out of the box — a wordlist ships inside the plugin. Detecting
gibberish that decodes to **real Hebrew / Arabic / Russian** needs that
language's wordlist, which `/keyoops add <lang>` downloads for you into
`~/.claude/keyoops-dicts/`:

| Language | Source |
|----------|--------|
| Hebrew (`he`) | wooorm/dictionaries |
| Russian (`ru`) | wooorm/dictionaries |
| Arabic (`ar`) | LibreOffice/dictionaries |

Dictionaries are fetched at install-time to your machine (not redistributed in
this repo), each under its own upstream license.

**Prefer your own wordlist?** Point the config at any one-word-per-line file
(hunspell `.dic`, aspell dump, custom list):

```json
{
  "languages": ["en", "he"],
  "wordlists": { "he": "/opt/homebrew/share/hunspell/he_IL.dic" }
}
```

If a wordlist can't be found for a language, that direction is simply skipped —
never an error.

## How it decides to fire

keyoops only fires when **every letter in the message is one script** (a "pure"
scramble — no mixed-language messages) **and** decoding the whole thing yields
mostly real words in another language. So:

- Real Hebrew/Russian/Arabic reverse-maps to gibberish, not words → ignored.
- Mixed messages (`add כפתור to the page`) → ignored (not one script).
- A normal English sentence stays English when decoded → ignored.

Once it *does* fire, the **entire** message is decoded by the key mapping —
including loanwords, names, or words not in the dictionary (the dictionary is
only used to *decide* whether it was a scramble). Claude reads the full decode
and renders your intended text.

## What it does not do

It only handles **layout scrambles** (gibberish from the wrong layout). It does
**not** translate coherent text you wrote in a real-but-unintended language —
that has no reliable code signal, so Claude handles it by judgment when it notices.

## License

MIT
