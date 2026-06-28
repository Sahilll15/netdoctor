# netdoctor — live dashboard demo: watch a fleet of hosts
# Render with:  vhs assets/watch.tape   (run from the repo root)
Output assets/watch.gif

Set Shell "bash"
Set FontSize 14
Set Width 1180
Set Height 300
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

Type "netdoctor github.com 1.1.1.1 --watch --interval 2 --max-runs 4"
Sleep 700ms
Enter
Sleep 17s
