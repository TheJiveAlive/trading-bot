#!/bin/zsh
# Sunday self-review: dump the week's ledger data, run a headless Claude
# review session, then email the review.
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")"

/usr/bin/python3 -m bot.review_dump >> logs/review_cli.log 2>&1

claude -p "$(cat research/review_prompt.md)" \
  --allowedTools "Read,Write,Bash(python3:*),WebSearch,WebFetch" \
  --permission-mode acceptEdits \
  >> logs/review_cli.log 2>&1

/usr/bin/python3 - <<'PY'
import glob, os
os.chdir(os.path.dirname(os.path.abspath("__file__")))
import sys; sys.path.insert(0, ".")
from bot import config, notify
config.load()
reviews = sorted(glob.glob("logs/weekly_review_*.md"))
if reviews:
    with open(reviews[-1]) as f:
        body = f.read()
    notify.send_email("[bot review] " + os.path.basename(reviews[-1]), body)
else:
    notify.send_email("[bot review] FAILED", "no weekly review file was produced")
PY
