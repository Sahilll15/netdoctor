# netdoctor — live mtr-style path monitor demo
# Render with:  vhs assets/mtr.tape   (run from the repo root)
Output assets/mtr.gif

Set Shell "bash"
Set FontSize 14
Set Width 1040
Set Height 470
Set Padding 18
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set BorderRadius 8
Set TypingSpeed 55ms

Hide
Type `export PS1="$ "`
Enter
Type "source .venv/bin/activate && clear"
Enter
Sleep 1s
Show

Type "netdoctor github.com --mtr --interval 1 --max-runs 2"
Sleep 700ms
Enter
Sleep 21s
