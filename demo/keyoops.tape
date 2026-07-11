# VHS tape for the keyoops demo GIF.  Render from the repo root:
#   vhs demo/keyoops.tape
Output demo/keyoops.gif

Set Shell bash
Set FontSize 18
Set Width 1120
Set Height 760
Set Padding 28
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms

Hide
Type "export PATH=$PWD/demo:$PATH" Enter
Type "clear" Enter
Show

Sleep 700ms
Type "# keyoops — catches wrong-keyboard-layout typing" Sleep 400ms Enter
Sleep 900ms

# English intended, but the keyboard was on Hebrew
Type "demo.py 'tz nv eurv gfahu'" Enter
Sleep 2600ms

# Hebrew intended (incl. the loanword 'test'), typed on an English layout
Type "demo.py 'sjp, t, vyxy vzv?'" Enter
Sleep 2600ms

# Real English is left alone
Type "demo.py 'can we ship this feature today'" Enter
Sleep 2400ms

# Built-in correctness + timing checks
Type "keyoops selftest" Enter
Sleep 4200ms

Type "# github.com/shannoga/keyoops" Sleep 400ms Enter
Sleep 2000ms
