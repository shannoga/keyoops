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
import marshal
import hashlib

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
CACHE_DIR = os.path.join(CLAUDE_DIR, 'keyoops-cache')

_EDGE_PUNCT = " \t\r\n\"'`.,!?;:()[]{}<>-–—…/\\|@#*_~"


def _parse_wordlist(path):
    """Parse a wordlist file into a lowercased set (the slow path).

    Handles plain one-word-per-line lists AND hunspell .dic files, whose lines
    look like "word/AFFIXFLAGS" (and whose first line is an entry count). We take
    the first whitespace token and drop anything after a '/'.
    """
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


def load_wordset(path):
    """Load a wordlist as a lowercased set, using a marshal cache keyed by mtime.

    The hook runs as a fresh process per prompt, so re-parsing a multi-MB .dic
    every time is the main latency cost. We cache the parsed set to a binary
    (marshal) file; subsequent loads just deserialize it (much faster) as long as
    the source file's mtime is unchanged.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cache = os.path.join(
        CACHE_DIR, hashlib.md5(os.path.abspath(path).encode()).hexdigest() + '.marshal')
    try:
        with open(cache, 'rb') as f:
            stored_mtime, words = marshal.load(f)
        if stored_mtime == mtime and isinstance(words, set):
            return words
    except (OSError, EOFError, ValueError, TypeError):
        pass  # missing/stale/corrupt cache — rebuild below
    try:
        words = _parse_wordlist(path)
    except OSError:
        return None
    try:  # best-effort cache write; never fatal
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = cache + '.tmp'
        with open(tmp, 'wb') as f:
            marshal.dump((mtime, words), f)
        os.replace(tmp, cache)
    except OSError:
        pass
    return words


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

    # "pure" = the whole message is in the source script (no foreign real words
    # mixed in). Used to gate auto-apply: only fully-scrambled messages skip the
    # confirmation, mixed ones always ask.
    pure = True
    for part in parts:
        if not part or part.isspace():
            continue
        c = core(part)
        if any(ch.isalpha() for ch in c) and not src_re.search(c):
            pure = False
            break

    if not scrambled_pos:
        return False, prompt, pure

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
        return False, prompt, pure

    rebuilt = list(parts)
    for part_index, is_scr, decoded_part, _, _ in tokens:
        if is_scr:
            rebuilt[part_index] = decoded_part
    return True, ''.join(rebuilt), pure


# Permission modes eligible for auto-apply by default. Overridable in config via
# "auto_apply_modes". Valid modes: default, plan, acceptEdits, auto, dontAsk,
# bypassPermissions. ("dontAsk" is available but off by default.)
DEFAULT_AUTO_APPLY_MODES = ['bypassPermissions']
VALID_MODES = ('default', 'plan', 'acceptEdits', 'auto', 'dontAsk',
               'bypassPermissions')


def build_context(decoded, desc, auto):
    intro = (
        f"The user's prompt looks like it was typed with the wrong keyboard "
        f"layout ({desc}), so it reads as gibberish. Decoded to the likely "
        f"intended text: \"{decoded}\". "
    )
    if auto:
        # No confirmation gate — proceed, but tell the user what was corrected.
        return (
            intro +
            "You have permission to proceed without confirmation, so use the "
            "decoded text directly — do NOT ask a yes/no first. Briefly tell the "
            "user you caught a keyboard-layout mistake and are using the decoded "
            "text instead of the original. Never act on the original scramble."
        )
    return (
        intro +
        "Ask the user exactly: \"Looks like the wrong keyboard layout — did you "
        f"mean: {decoded}? go with it?\" and wait for a yes/no. "
        "If yes, proceed using the decoded text. If no, use the original. "
        "Do NOT act on the original scrambled text before they confirm."
    )


def load_config():
    """Read the optional config file. Returns (codes, overrides, auto_apply_modes).

    Config shape (all fields optional):
        {
          "languages": ["he", "en", "ar"],
          "wordlists": {"he": "/path/to/he_IL.dic", "ar": "/path/to/ar.dic"},
          "auto_apply_modes": ["bypassPermissions"]
        }
    'languages' may also be a comma string ("he,en,ar"). Missing/unreadable/
    invalid config falls back to the defaults, so a bad edit never breaks
    prompting.
    """
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return DEFAULT_LANGUAGES, {}, list(DEFAULT_AUTO_APPLY_MODES)
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
    # auto_apply_modes: absent -> default; explicit [] -> never auto-apply.
    modes = cfg.get('auto_apply_modes')
    if isinstance(modes, str):
        modes = modes.split(',')
    if not isinstance(modes, list):
        auto_modes = list(DEFAULT_AUTO_APPLY_MODES)
    else:
        auto_modes = [str(m).strip() for m in modes if str(m).strip() in VALID_MODES]
    return codes, overrides, auto_modes


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
        'src': src,
        'tgt': tgt,
        'char_map': char_map,
        'src_re': S['script_re'],
        'wordlist_path': resolve_wordlist(tgt, overrides),
        'desc': f"{S['label']} keys while intending {T['label']}",
    }


def resolve_directions(codes, overrides):
    """Every ordered pair among the declared languages (source != target)."""
    return [make_direction(s, t, overrides)
            for s in codes for t in codes if s != t]


def skippable_latin_direction(prompt, en_wordset):
    """True if an English-layout -> other-language direction can be skipped.

    A real scramble into another language looks like a run of >=2 adjacent Latin
    tokens that are NOT valid English — the exact thing the flag gate needs. If
    the message has no such run, the direction could never fire, so we skip
    loading its (large) target dictionary. This changes NO detection outcomes;
    it only avoids needless work on ordinary English text.
    """
    flags = []  # per Latin word-token: True if it is NOT a real English word
    for part in re.split(r'\s+', prompt):
        c = core(part)
        if c and LATIN_RE.search(c):
            flags.append(c.lower() not in en_wordset)
    if len(flags) <= 1:
        return False  # too short to judge — don't skip (single-token case)
    non_en = [i for i, bad in enumerate(flags) if bad]
    return longest_run(non_en) < 2


def detect(prompt, codes, overrides, auto_modes, permission_mode):
    """Core detection shared by the hook and `selftest`.

    Returns (decoded, desc, auto) for the first firing direction, else None.
    Builds a fresh in-process wordset cache per call (like a real per-prompt hook
    run); the on-disk marshal cache keeps repeated loads fast.
    """
    wordset_cache = {}

    # For English-layout -> other-language directions, we can often skip loading
    # the big target dict by pre-checking against the (small, cached) English
    # list. Load it once if English is configured.
    en_wordset = None
    if 'en' in codes:
        en_path = resolve_wordlist('en', overrides)
        if en_path:
            en_wordset = load_wordset(en_path)
            wordset_cache[en_path] = en_wordset

    for direction in resolve_directions(codes, overrides):
        # Cheap pre-filter: a direction can only fire if the prompt actually
        # contains characters in its source script. This skips the (possibly
        # multi-MB) wordlist load for directions that can't apply — e.g. the
        # English->Hebrew check never loads he.dic for a Latin-only message that
        # has no Hebrew, and vice versa.
        if not direction['src_re'].search(prompt):
            continue
        # For en -> (he/ar/ru), skip when the message shows no multi-word Latin
        # scramble (ordinary English never loads the big target dictionary).
        if (direction['src'] == 'en' and direction['tgt'] != 'en'
                and en_wordset is not None
                and skippable_latin_direction(prompt, en_wordset)):
            continue
        path = direction['wordlist_path']
        if not path:
            continue          # target language's wordlist not installed — skip
        if path not in wordset_cache:
            wordset_cache[path] = load_wordset(path)
        wordset = wordset_cache[path]
        if not wordset:
            continue
        flagged, decoded, pure = analyze(prompt, direction, wordset)
        if flagged and decoded.strip() and decoded != prompt:
            # Auto-apply only when the mode allows it AND the message is a pure
            # single-language scramble (mixed messages always ask, to be safe).
            auto = permission_mode in auto_modes and pure
            return decoded, direction['desc'], auto
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    prompt = data.get('prompt') or ''
    permission_mode = data.get('permission_mode') or 'default'
    if not prompt.strip():
        return 0

    codes, overrides, auto_modes = load_config()
    res = detect(prompt, codes, overrides, auto_modes, permission_mode)
    if res:
        decoded, desc, auto = res
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": build_context(decoded, desc, auto),
            }
        }
        print(json.dumps(out, ensure_ascii=False))
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
    modes = cfg.get('auto_apply_modes')
    if not isinstance(modes, list):
        modes = DEFAULT_AUTO_APPLY_MODES
    shown = ', '.join(modes) if modes else '(none — always ask)'
    print(f'auto-apply (skip confirmation) in modes: {shown}')
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


def cmd_autoapply(spec=None):
    """Show or set the permission modes where corrections auto-apply (no y/n)."""
    cfg = load_config_raw()
    if spec is None:
        modes = cfg.get('auto_apply_modes')
        if not isinstance(modes, list):
            modes = DEFAULT_AUTO_APPLY_MODES
        print('auto-apply modes:', ', '.join(modes) if modes else '(none — always ask)')
        print('valid modes:', ', '.join(VALID_MODES))
        print('set with: keyoops autoapply <mode[,mode…] | off | default>')
        return 0
    spec = spec.strip().lower()
    if spec in ('off', 'none'):
        modes = []
    elif spec == 'default':
        modes = list(DEFAULT_AUTO_APPLY_MODES)
    else:
        requested = [m.strip() for m in spec.split(',') if m.strip()]
        valid_lower = {m.lower(): m for m in VALID_MODES}
        bad = [m for m in requested if m.lower() not in valid_lower]
        if bad:
            print(f"unknown mode(s): {', '.join(bad)}")
            print('valid modes:', ', '.join(VALID_MODES))
            return 1
        # dedupe, preserve canonical casing
        seen, modes = set(), []
        for m in requested:
            canon = valid_lower[m.lower()]
            if canon not in seen:
                seen.add(canon)
                modes.append(canon)
    cfg['auto_apply_modes'] = modes
    write_config(cfg)
    print('auto-apply modes:', ', '.join(modes) if modes else '(none — always ask)')
    print('Active on your next prompt.')
    return 0


def cmd_selftest():
    """Run built-in cases against the live config: correctness + timing."""
    import time
    codes, overrides, auto_modes = load_config()
    # (label, prompt, expect_flag, target_needed)
    cases = [
        ('normal English', 'can we ship this feature today', False, None),
        ('he->en scramble', 'יקךךם add a button', True, 'en'),
        ('en->he scramble', 'tz nv eurv gfahu', True, 'he'),
        ('real Hebrew', 'שלום חבר מה נשמע', False, None),
        ('single word', 'טקד', True, 'en'),
    ]
    print('keyoops self-test')
    print('languages:', ', '.join(codes),
          '| auto-apply:', ', '.join(auto_modes) or '(none)')
    # warm caches once so timings reflect steady state
    for _, pr, _, _ in cases:
        detect(pr, codes, overrides, auto_modes, 'default')

    print(f"\n{'case':<18}{'result':<8}{'time':>8}   detail")
    print('-' * 58)
    passed = total = 0
    for label, pr, expect, needs in cases:
        if needs and not resolve_wordlist(needs, overrides):
            print(f"{label:<18}{'SKIP':<8}{'—':>8}   needs '{needs}' dictionary")
            continue
        t = time.perf_counter()
        res = detect(pr, codes, overrides, auto_modes, 'default')
        ms = (time.perf_counter() - t) * 1000
        ok = (res is not None) == expect
        total += 1
        passed += ok
        detail = res[0] if res else '(silent)'
        print(f"{label:<18}{'PASS' if ok else 'FAIL':<8}{ms:>6.0f} ms   {detail}")
    print('-' * 58)
    print(f"{passed}/{total} passed  ·  timings are in-process; add ~55-65 ms "
          "Python startup for real per-prompt cost")
    return 0 if passed == total else 1


def cli(argv):
    import argparse
    p = argparse.ArgumentParser(
        prog='keyoops', description='Manage keyoops keyboard-layout settings.')
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('list', help='show configured languages + dictionary status')
    sub.add_parser('selftest', help='run correctness + timing checks')
    a = sub.add_parser('add', help='add a language (auto-downloads its dictionary)')
    a.add_argument('lang', nargs='?', help='language code: ' + ', '.join(LANGUAGES)
                   + ' (omit for a selection menu)')
    r = sub.add_parser('remove', help='remove a language')
    r.add_argument('lang')
    aa = sub.add_parser('autoapply',
                        help='show/set modes that skip confirmation (e.g. '
                             'bypassPermissions,dontAsk | off | default)')
    aa.add_argument('modes', nargs='?')
    args = p.parse_args(argv)
    if args.cmd == 'list':
        return cmd_list()
    if args.cmd == 'selftest':
        return cmd_selftest()
    if args.cmd == 'add':
        return cmd_add(args.lang)
    if args.cmd == 'remove':
        return cmd_remove(args.lang)
    if args.cmd == 'autoapply':
        return cmd_autoapply(args.modes)
    p.print_help()
    return 0


if __name__ == '__main__':
    # Args -> management CLI; no args -> UserPromptSubmit hook (reads stdin).
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    sys.exit(main())
