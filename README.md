# layout-scramble

A Claude Code plugin that catches prompts typed with the **wrong keyboard layout**.

You meant to type English but the OS was on Hebrew, so `hello` came out as `יקךךם`?
This plugin notices, decodes it back to what you meant, and asks Claude to confirm
before doing anything:

> Looks like the wrong keyboard layout — did you mean: **hello add a button**? go with it?

Detection is pure code (no model tokens): it reverse-maps each character through
the keyboard layout and checks the result against a wordlist. If clean words fall
out, it flags; otherwise it stays silent. It **never blocks** — worst case is one
"did you mean…?" you decline.

## Install

```
/plugin marketplace add shannoga/layout-scramble
/plugin install layout-scramble
```

The hook registers automatically — no `settings.json` editing. Restart your
session and it's active. Requires `python3` (preinstalled on macOS and most Linux).

## Configure (optional)

By default it catches **Hebrew-layout → English**. To change which languages it
watches, copy the example config to your home and edit it:

```
cp "$(/plugin root layout-scramble)/layout-scramble.config.example.json" \
   ~/.claude/layout-scramble.config.json
```

Then list the languages you type:

```json
{ "languages": ["en", "he", "ru"] }
```

The hook checks **every ordered pair** among them — for each language your layout
might have been ON, it decodes to each *other* language and flags real words.
Supported codes: `en`, `he`, `ar`, `ru`.

Config lives in `~/.claude/` so plugin updates never overwrite it.

### Non-English targets

English works out of the box (a wordlist is bundled). Detecting gibberish that
decodes to **real Hebrew/Arabic/Russian** needs that language's wordlist
installed — then point `wordlists` at it:

```json
{
  "languages": ["en", "he"],
  "wordlists": { "he": "/opt/homebrew/share/hunspell/he_IL.dic" }
}
```

## How it stays quiet on real text

- Real Hebrew/Russian/Arabic reverse-maps to gibberish, not words → ignored.
- Intentional mixing (`add כפתור to the page`) → ignored.
- A lone word that coincidentally decodes → ignored (needs a contiguous run or a
  full-message slip to fire).

## What it does not do

It only handles **layout scrambles** (gibberish from the wrong layout). It does
**not** translate coherent text you wrote in a real-but-unintended language —
that has no reliable code signal, so Claude handles it by judgment when it notices.

## License

MIT
