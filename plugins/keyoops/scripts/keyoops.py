#!/usr/bin/env python3
"""
UserPromptSubmit hook: detect wrong-keyboard-layout typing.

When you intend to type English but the OS keyboard is on Hebrew, every key
produces a Hebrew character by position ("hello" -> "יקךךם"). This hook reverse-
maps such tokens back through the layout table and, if clean English falls out,
injects a note asking Claude to confirm the decoded text before acting on it.

Detection is pure code (no model): reverse-map, then check tokens against a
wordlist. It never blocks — worst case is one "did you mean X?" you decline.

Reads the hook JSON from stdin (fields: `prompt`, `permission_mode`). On a
confident hit, prints a hookSpecificOutput JSON with `additionalContext` and
exits 0. Otherwise prints nothing and exits 0.

You declare the languages you type in an optional config file,
~/.claude/keyoops.config.json (e.g. {"languages":["he","en","ar"]}). The hook
then checks every ordered pair among them — for each language the layout might
have been ON, it decodes to each OTHER language and flags if real words fall out.
With no config it defaults to ["en","he"]. A direction only runs if the target
language's wordlist exists (macOS ships English only; install a Hebrew/Arabic/
Russian wordlist and point the config's "wordlists" at it).
"""
import sys
import os
import re
import json

# --- Language profiles -------------------------------------------------------
# You declare the languages you type (e.g. ["he","en","ar"]) in the config, and
# the hook checks every ordered pair among them: for each language you might have
# had the layout ON, decode to each OTHER language and see if real words fall out.
#
# Each profile maps a physical keyboard key (base QWERTY position) to the
# character that layout produces. A scramble from layout S to intended language T
# is decoded by: source-char -> its key (invert S) -> T's char at that key.

# Standard Israeli Hebrew layout: key position -> Hebrew char.
HE_KEYMAP = {
    'e': 'ק', 'r': 'ר', 't': 'א', 'y': 'ט', 'u': 'ו', 'i': 'ן', 'o': 'ם', 'p': 'פ',
    'a': 'ש', 's': 'ד', 'd': 'ג', 'f': 'כ', 'g': 'ע', 'h': 'י', 'j': 'ח', 'k': 'ל', 'l': 'ך',
    'z': 'ז', 'x': 'ס', 'c': 'ב', 'v': 'ה', 'b': 'נ', 'n': 'מ', 'm': 'צ',
    ';': 'ף', '.': 'ץ', ',': 'ת',
}
# Standard Arabic layout: key position -> Arabic char (single-char keys only).
AR_KEYMAP = {
    'q': 'ض', 'w': 'ص', 'e': 'ث', 'r': 'ق', 't': 'ف', 'y': 'غ', 'u': 'ع', 'i': 'ه',
    'o': 'خ', 'p': 'ح', '[': 'ج', ']': 'د',
    'a': 'ش', 's': 'س', 'd': 'ي', 'f': 'ب', 'g': 'ل', 'h': 'ا', 'j': 'ت', 'k': 'ن', 'l': 'م',
    ';': 'ك', "'": 'ط', 'z': 'ئ', 'x': 'ء', 'c': 'ؤ', 'v': 'ر', 'n': 'ى', 'm': 'ة',
    ',': 'و', '.': 'ز', '/': 'ظ',
}
# English/Latin layout: identity (the key IS the character).
EN_KEYMAP = {k: k for k in "qwertyuiopasdfghjklzxcvbnm;.,'/[]"}
# Standard Russian ЙЦУКЕН layout: key position -> Cyrillic char.
RU_KEYMAP = {
    'q': 'й', 'w': 'ц', 'e': 'у', 'r': 'к', 't': 'е', 'y': 'н', 'u': 'г', 'i': 'ш',
    'o': 'щ', 'p': 'з', '[': 'х', ']': 'ъ',
    'a': 'ф', 's': 'ы', 'd': 'в', 'f': 'а', 'g': 'п', 'h': 'р', 'j': 'о', 'k': 'л',
    'l': 'д', ';': 'ж', "'": 'э',
    'z': 'я', 'x': 'ч', 'c': 'с', 'v': 'м', 'b': 'и', 'n': 'т', 'm': 'ь',
    ',': 'б', '.': 'ю', '/': '.',
}

HEBREW_RE = re.compile(r'[֐-׿]')
LATIN_RE = re.compile(r'[A-Za-z]')
ARABIC_RE = re.compile(r'[؀-ۿ]')
CYRILLIC_RE = re.compile(r'[Ѐ-ӿ]')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_EN = os.path.join(SCRIPT_DIR, 'words-en.txt')

# code -> profile. 'wordlist' is a list of candidate paths (first existing wins),
# so a bundled fallback covers machines lacking a system wordlist.
# Add a language = one entry here + a target wordlist.
LANGUAGES = {
    'en': {'label': 'English', 'key_to_char': EN_KEYMAP, 'script_re': LATIN_RE,
           'wordlist': ['/usr/share/dict/words', BUNDLED_EN]},
    'he': {'label': 'Hebrew',  'key_to_char': HE_KEYMAP, 'script_re': HEBREW_RE,
           'wordlist': ['/opt/homebrew/share/hunspell/he_IL.dic']},
    'ar': {'label': 'Arabic',  'key_to_char': AR_KEYMAP, 'script_re': ARABIC_RE,
           'wordlist': ['/opt/homebrew/share/hunspell/ar.dic']},
    'ru': {'label': 'Russian', 'key_to_char': RU_KEYMAP, 'script_re': CYRILLIC_RE,
           'wordlist': ['/opt/homebrew/share/hunspell/ru_RU.dic']},
}

DEFAULT_LANGUAGES = ['en', 'he']
# Config lives in the user's home (not next to the script) so a plugin update
# never clobbers it.
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.claude',
                           'keyoops.config.json')

_EDGE_PUNCT = " \t\r\n\"'`.,!?;:()[]{}<>-–—…/\\|@#*_~"


def load_wordset(path):
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            return {w.strip().lower() for w in f if w.strip()}
    except OSError:
        return None


def decode(text, char_map):
    return ''.join(char_map.get(ch, ch) for ch in text)


def core(tok):
    """Strip edge punctuation so the wordlist test sees just the word."""
    return tok.strip(_EDGE_PUNCT)


def longest_run(indices):
    """Longest streak of consecutive integers in a sorted index list."""
    if not indices:
        return 0
    best = run = 1
    for a, b in zip(indices, indices[1:]):
        run = run + 1 if b == a + 1 else 1
        best = max(best, run)
    return best


def analyze(prompt, direction, wordset):
    """Return (should_flag, decoded_prompt) for one direction."""
    char_map = direction['char_map']
    src_re = direction['src_re']

    # Split keeping whitespace so we can reconstruct spacing exactly.
    parts = re.split(r'(\s+)', prompt)
    tokens = []          # (part_index, is_scrambled, decoded_part, has_src)
    for i, part in enumerate(parts):
        if not part or part.isspace():
            continue
        c = core(part)
        if not c:
            tokens.append((i, False, part, False))
            continue
        has_src = bool(src_re.search(c))
        if c.lower() in wordset:                       # already a real word
            tokens.append((i, False, part, has_src))
        elif has_src:
            dec_core = core(decode(c, char_map))
            if dec_core.lower() in wordset:            # decodes to a real target word
                tokens.append((i, True, decode(part, char_map), True))
            else:
                tokens.append((i, False, part, True))  # genuine source-language
        else:
            tokens.append((i, False, part, has_src))

    scrambled_pos = [n for n, t in enumerate(tokens) if t[1]]
    src_pos = [n for n, t in enumerate(tokens) if t[3]]
    if not scrambled_pos:
        return False, prompt

    # --- Anti-false-positive gate ---
    if len(tokens) == 1:
        # Lone word: can't compare against context; require a real, non-trivial
        # decode. (Residual risk is cheap — Claude still asks first.)
        dec_core = core(tokens[0][2])
        flag = len(dec_core) >= 3
    else:
        # Flag a contiguous run of >=2 scrambled tokens, OR when every
        # source-script token in the message is scrambled (a full slip),
        # never a lone coincidental word among real source-language text.
        flag = longest_run(scrambled_pos) >= 2 or len(scrambled_pos) >= len(src_pos)

    if not flag:
        return False, prompt

    rebuilt = list(parts)
    for part_index, is_scr, decoded_part, _ in tokens:
        if is_scr:
            rebuilt[part_index] = decoded_part
    return True, ''.join(rebuilt)


def build_context(decoded, permission_mode, desc):
    fast = permission_mode in ('auto', 'bypassPermissions', 'dontAsk', 'acceptEdits')
    lead = (
        "STOP — do not act on the user's prompt yet. "
        if fast else
        "Heads up before acting on the user's prompt. "
    )
    return (
        f"{lead}It looks like it was typed with the wrong keyboard layout "
        f"({desc}), so it reads as gibberish. "
        f"Decoded to the likely intended text: \"{decoded}\". "
        f"Ask the user exactly: \"Looks like the wrong keyboard layout — did you "
        f"mean: {decoded}? go with it?\" and wait for a yes/no. "
        f"If yes, proceed using the decoded text. If no, use the original. "
        f"Do NOT act on the original scrambled text before they confirm."
    )


def load_config():
    """Read the optional config file. Returns (language_codes, wordlist_overrides).

    Config shape (all fields optional):
        {
          "languages": ["he", "en", "ar"],
          "wordlists": {"he": "/path/to/he_IL.dic", "ar": "/path/to/ar.dic"}
        }
    'languages' may also be a comma string ("he,en,ar"). Missing/unreadable/
    invalid config falls back to the default, so a bad edit never breaks
    prompting.
    """
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return DEFAULT_LANGUAGES, {}
    langs = cfg.get('languages')
    if isinstance(langs, str):
        langs = langs.split(',')
    if not isinstance(langs, list) or not langs:
        langs = DEFAULT_LANGUAGES
    # normalize: lowercase, strip, drop unknowns, dedupe (keep order)
    seen, codes = set(), []
    for c in langs:
        code = str(c).strip().lower()
        if code in LANGUAGES and code not in seen:
            seen.add(code)
            codes.append(code)
    if not codes:
        codes = DEFAULT_LANGUAGES
    overrides = cfg.get('wordlists')
    if not isinstance(overrides, dict):
        overrides = {}
    return codes, overrides


def _invert(key_to_char):
    """char -> key (first key wins if a char maps from several keys)."""
    out = {}
    for key, ch in key_to_char.items():
        out.setdefault(ch, key)
    return out


def resolve_wordlist(tgt, overrides):
    """First existing wordlist path for a target language, or None."""
    cands = [overrides[tgt]] if tgt in overrides else LANGUAGES[tgt]['wordlist']
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


def make_direction(src, tgt, overrides):
    """Build a runnable direction: source-layout SRC, intended language TGT."""
    S, T = LANGUAGES[src], LANGUAGES[tgt]
    src_char_to_key = _invert(S['key_to_char'])
    char_map = {ch: T['key_to_char'].get(key, key)
                for ch, key in src_char_to_key.items()}
    return {
        'name': f'{src}-layout-to-{tgt}',
        'char_map': char_map,
        'src_re': S['script_re'],
        'wordlist_path': resolve_wordlist(tgt, overrides),
        'desc': f"{S['label']} keys while intending {T['label']}",
    }


def resolve_directions(codes, overrides):
    """Every ordered pair among the declared languages (source != target)."""
    return [make_direction(s, t, overrides)
            for s in codes for t in codes if s != t]


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    prompt = data.get('prompt') or ''
    permission_mode = data.get('permission_mode') or 'default'
    if not prompt.strip():
        return 0

    codes, overrides = load_config()
    wordset_cache = {}
    for direction in resolve_directions(codes, overrides):
        path = direction['wordlist_path']
        if not path:
            continue          # target language's wordlist not installed — skip
        if path not in wordset_cache:
            wordset_cache[path] = load_wordset(path)
        wordset = wordset_cache[path]
        if not wordset:
            continue
        flagged, decoded = analyze(prompt, direction, wordset)
        if flagged and decoded.strip() and decoded != prompt:
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": build_context(
                        decoded, permission_mode, direction['desc']),
                }
            }
            print(json.dumps(out, ensure_ascii=False))
            return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
