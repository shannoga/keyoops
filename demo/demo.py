#!/usr/bin/env python3
"""Pretty-print keyoops detection for the demo GIF: `demo.py "<scramble>" ...`."""
import sys
import os
import importlib.util

_base = os.path.dirname(os.path.abspath(__file__))
_script = os.path.join(_base, '..', 'plugins', 'keyoops', 'scripts', 'keyoops.py')
_spec = importlib.util.spec_from_file_location('keyoops', _script)
k = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k)

BOLD, DIM, CYAN, GREEN, RST = '\033[1m', '\033[2m', '\033[36m', '\033[32m', '\033[0m'


def display(s):
    """VHS/ttyd have no bidi, so a Hebrew string lays out left-to-right and reads
    backwards. For the GIF only, reverse RTL strings so they display correctly."""
    if any('֐' <= c <= '׿' for c in s):
        return s[::-1]
    return s


for scramble in sys.argv[1:]:
    res = k.detect(scramble, ['en', 'he'], {}, [], 'default')
    print(f"  {DIM}you typed{RST}   {display(scramble)}")
    if res:
        print(f"  {CYAN}keyoops{RST}     wrong layout — did you mean:")
        print(f"              {BOLD}{GREEN}{display(res[0])}{RST}")
    else:
        print(f"  {CYAN}keyoops{RST}     {DIM}(looks fine — left alone){RST}")
    print()
