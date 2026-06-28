# netdoctor — hero demo: a full health check of github.com
# Render with:  vhs assets/hero.tape   (run from the repo root)
Output assets/hero.gif

Set Shell "bash"
Set FontSize 15
Set Width 940
Set Height 1240
Set Padding 18
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set BorderRadius 8
Set TypingSpeed 55ms

# --- hidden setup: clean prompt + activate the venv, then clear ---
Hide
Type `export PS1="$ "`
Enter
Type "source .venv/bin/activate && clear"
Enter
Sleep 1s
Show

# --- the demo ---
Type "netdoctor github.com"
Sleep 700ms
Enter
Sleep 14s
