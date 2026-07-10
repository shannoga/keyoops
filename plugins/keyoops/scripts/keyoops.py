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
# so a bundled/downloaded fallback covers machines lacking a system wordlist.
# 'dict_url' (optional) is auto-downloadable via `keyoops add <lang>`.
# Add a language = one entry here (+ a dict_url or bundled wordlist).
_WOOORM = 'https://raw.githubusercontent.com/wooorm/dictionaries/main/dictionaries'
_LIBRE = 'https://raw.githubusercontent.com/LibreOffice/dictionaries/master'
LANGUAGES = {
    'en': {'label': 'English', 'key_to_char': EN_KEYMAP, 'script_re': LATIN_RE,
           'wordlist': ['/usr/share/dict/words', BUNDLED_EN], 'dict_url': None},
    'he': {'label': 'Hebrew',  'key_to_char': HE_KEYMAP, 'script_re': HEBREW_RE,
           'wordlist': ['/opt/homebrew/share/hunspell/he_IL.dic'],
           'dict_url': f'{_WOOORM}/he/index.dic'},
    'ar': {'label': 'Arabic',  'key_to_char': AR_KEYMAP, 'script_re': ARABIC_RE,
           'wordlist': ['/opt/homebrew/share/hunspell/ar.dic'],
           'dict_url': f'{_LIBRE}/ar/ar.dic'},
    'ru': {'label': 'Russian', 'key_to_char': RU_KEYMAP, 'script_re': CYRILLIC_RE,
           'wordlist': ['/opt/homebrew/share/hunspell/ru_RU.dic'],
           'dict_url': f'{_WOOORM}/ru/index.dic'},
}

DEFAULT_LANGUAGES = ['en', 'he']
# Config + auto-downloaded dictionaries live in the user's home (not next to the
# script) so a plugin update never clobbers them.
CLAUDE_DIR = os.path.join(os.path.expanduser('~'), '.claude')
CONFIG_PATH = os.path.join(CLAUDE_DIR, 'keyoops.config.json')
DICTS_DIR = os.path.join(CLAUDE_DIR, 'keyoops-dicts')

_EDGE_PUNCT = " \t\r\n\"'`.,!?;:()[]{}<>-–—…/\\|@#*_~"


def load_wordset(path):
    """Load a wordlist into a lowercased set.

    Handles plain one-word-per-line lists AND hunspell .dic files, whose lines
    look like "word/AFFIXFLAGS" (and whose first line is an entry count). We take
    the first whitespace token and drop anything after a '/'.
    """
    try:
        words = set()
        with open(path, encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                w = line.split()[0].split('/', 1)[0].strip().lower()
                if w:
                    words.add(w)
        return words
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
    tokens = []          # (part_index, is_scrambled, decoded_part, has_src, strong)
    for i, part in enumerate(parts):
        if not part or part.isspace():
            continue
        c = core(part)
        if not c:
            tokens.append((i, False, part, False, False))
            continue
        has_src = bool(src_re.search(c))
        if c.lower() in wordset:                       # already a real word
            tokens.append((i, False, part, has_src, False))
        elif has_src:
            dec_core = core(decode(c, char_map))
            if dec_core.lower() in wordset:            # decodes to a real target word
                # "strong" = a >=3 char decode; short decodes (a, as, to -> real
                # but tiny target words) are coincidence-prone and don't carry a
                # flag on their own.
                strong = len(dec_core) >= 3
                tokens.append((i, True, decode(part, char_map), True, strong))
            else:
                tokens.append((i, False, part, True, False))  # genuine source-lang
        else:
            tokens.append((i, False, part, has_src, False))

    scrambled_pos = [n for n, t in enumerate(tokens) if t[1]]
    strong_pos = [n for n, t in enumerate(tokens) if t[4]]
    src_pos = [n for n, t in enumerate(tokens) if t[3]]
    if not scrambled_pos:
        return False, prompt

    # --- Anti-false-positive gate ---
    if len(tokens) == 1:
        # Lone word: require a strong (>=3 char) decode. Cheap even if wrong —
        # Claude still asks first.
        flag = bool(strong_pos)
    else:
        # Real evidence = a contiguous run of >=2 STRONG decodes, OR a full slip
        # where every source-script token decodes (and at least one is strong).
        # A couple of scattered short coincidences never fire.
        flag = (longest_run(strong_pos) >= 2
                or (len(scrambled_pos) >= len(src_pos) and bool(strong_pos)))

    if not flag:
        return False, prompt

    rebuilt = list(parts)
    for part_index, is_scr, decoded_part, _, _ in tokens:
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
    """First existing wordlist path for a target language, or None.

    Order: explicit config override -> auto-downloaded cache -> system/bundled.
    """
    cands = []
    if tgt in overrides:
        cands.append(overrides[tgt])
    cands.append(os.path.join(DICTS_DIR, f'{tgt}.dic'))   # `keyoops add` cache
    cands.extend(LANGUAGES[tgt]['wordlist'])
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


# --- CLI: manage languages (add / remove / list) ----------------------------
# Invoked with args (e.g. `keyoops add ru`). With no args it's the hook (above).

def load_config_raw():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            return cfg
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


def write_config(cfg):
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write('\n')


def config_langs(cfg):
    langs = cfg.get('languages')
    if isinstance(langs, str):
        langs = langs.split(',')
    if not isinstance(langs, list):
        langs = list(DEFAULT_LANGUAGES)
    out, seen = [], set()
    for c in langs:
        c = str(c).strip().lower()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out or list(DEFAULT_LANGUAGES)


def download_dict(code):
    """Fetch a language's dictionary into the cache. Returns (ok, path_or_error)."""
    url = LANGUAGES.get(code, {}).get('dict_url')
    if not url:
        return False, 'no downloadable dictionary for this language'
    import urllib.request
    os.makedirs(DICTS_DIR, exist_ok=True)
    dest = os.path.join(DICTS_DIR, f'{code}.dic')
    tmp = dest + '.tmp'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'keyoops'})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, 'wb') as out:
            out.write(r.read())
        os.replace(tmp, dest)
        return True, dest
    except Exception as e:  # network/IO — report, don't crash
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, str(e)


def _overrides(cfg):
    ov = cfg.get('wordlists')
    return ov if isinstance(ov, dict) else {}


def cmd_list():
    cfg = load_config_raw()
    langs = config_langs(cfg)
    overrides = _overrides(cfg)
    print('keyoops languages:', ', '.join(langs))
    print('dictionary status (needed only when a language is a decode *target*):')
    for code in langs:
        if code not in LANGUAGES:
            print(f'  {code}: unknown language (ignored)')
            continue
        label = LANGUAGES[code]['label']
        wl = resolve_wordlist(code, overrides)
        if wl:
            print(f'  {code} ({label}): ready  [{wl}]')
        elif LANGUAGES[code].get('dict_url'):
            print(f'  {code} ({label}): missing — run `keyoops add {code}` to download')
        else:
            print(f'  {code} ({label}): no dictionary available')
    return 0


def pick_language():
    """Show a numbered menu of supported languages and return the chosen code.

    Interactive when attached to a terminal; otherwise prints the list and
    returns None (the /keyoops command drives selection via Claude instead).
    """
    codes = list(LANGUAGES)
    print('Select a language to add:')
    for n, c in enumerate(codes, 1):
        print(f'  {n}) {c} — {LANGUAGES[c]["label"]}')
    if not sys.stdin.isatty():
        print('Re-run as `keyoops add <code>` with one of:', ', '.join(codes))
        return None
    try:
        choice = input('Enter number or code: ').strip().lower()
    except EOFError:
        return None
    if choice.isdigit():
        i = int(choice) - 1
        return codes[i] if 0 <= i < len(codes) else None
    return choice if choice in LANGUAGES else None


def cmd_add(code=None):
    code = (code or '').strip().lower()
    if not code:
        code = pick_language()
        if not code:
            return 1
    if code not in LANGUAGES:
        print(f"unknown language '{code}'. supported: {', '.join(LANGUAGES)}")
        return 1
    cfg = load_config_raw()
    langs = config_langs(cfg)
    if code not in langs:
        langs.append(code)
    cfg['languages'] = langs
    write_config(cfg)
    print(f"added '{code}' ({LANGUAGES[code]['label']}). languages: {', '.join(langs)}")
    if resolve_wordlist(code, _overrides(cfg)):
        print(f"dictionary ready: {resolve_wordlist(code, _overrides(cfg))}")
    elif LANGUAGES[code].get('dict_url'):
        print('downloading dictionary…')
        ok, info = download_dict(code)
        if ok:
            print(f'  saved to {info}')
        else:
            print(f'  download failed: {info}')
            print(f"  you can set a manual path under 'wordlists' in {CONFIG_PATH}")
    else:
        print('no dictionary needed / available.')
    print('Active on your next prompt — no restart needed.')
    return 0


def cmd_remove(code):
    code = code.strip().lower()
    cfg = load_config_raw()
    langs = config_langs(cfg)
    if code not in langs:
        print(f"'{code}' is not in your languages: {', '.join(langs)}")
        return 0
    langs = [c for c in langs if c != code]
    cfg['languages'] = langs
    write_config(cfg)
    print(f"removed '{code}'. languages: {', '.join(langs) or '(none)'}")
    print('Active on your next prompt. (Any downloaded dictionary stays cached.)')
    return 0


def cli(argv):
    import argparse
    p = argparse.ArgumentParser(
        prog='keyoops', description='Manage keyoops keyboard-layout languages.')
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('list', help='show configured languages + dictionary status')
    a = sub.add_parser('add', help='add a language (auto-downloads its dictionary)')
    a.add_argument('lang', nargs='?', help='language code: ' + ', '.join(LANGUAGES)
                   + ' (omit for a selection menu)')
    r = sub.add_parser('remove', help='remove a language')
    r.add_argument('lang')
    args = p.parse_args(argv)
    if args.cmd == 'list':
        return cmd_list()
    if args.cmd == 'add':
        return cmd_add(args.lang)
    if args.cmd == 'remove':
        return cmd_remove(args.lang)
    p.print_help()
    return 0


if __name__ == '__main__':
    # Args -> management CLI; no args -> UserPromptSubmit hook (reads stdin).
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    sys.exit(main())
