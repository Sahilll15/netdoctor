# netdoctor — scorecard demo: grade a host over many probes
# Render with:  vhs assets/scorecard.tape   (run from the repo root)
Output assets/scorecard.gif

Set Shell "bash"
Set FontSize 15
Set Width 940
Set Height 800
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

Type "netdoctor github.com --no-trace --samples 12"
Sleep 700ms
Enter
# github's latency is variable; 15s comfortably covers a full 12-probe benchmark
# so the recording always ends on the rendered scorecard, not the spinner.
Sleep 15s
