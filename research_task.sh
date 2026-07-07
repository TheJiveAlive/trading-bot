#!/bin/zsh
# Daily research: headless Claude session researches the market and writes
# data/research.json for the bot, then the summary is emailed.
[ "$(date +%u)" -gt 5 ] && exit 0  # market closed at weekends
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")"

claude -p "$(cat research/research_prompt.md)" \
  --allowedTools "WebSearch,WebFetch,Read,Write,Edit" \
  --permission-mode acceptEdits \
  >> logs/research_cli.log 2>&1

# If the bot repo has a GitHub remote (cloud mode), sync research to it so the
# cloud scans consume today's research.json
if git remote get-url origin > /dev/null 2>&1; then
  git pull -q --rebase origin main 2>/dev/null || true
  git add data/research.json 2>/dev/null
  git commit -q -m "daily research $(date '+%Y-%m-%d')" 2>/dev/null && \
    git push -q origin main 2>/dev/null || true
fi

# Email the fresh research summary (skips silently if secrets.json not set up)
/usr/bin/python3 - <<'PY'
import json, os
os.chdir(os.path.dirname(os.path.abspath("__file__")))
import sys; sys.path.insert(0, ".")
from bot import config, notify
config.load()
try:
    with open("data/research.json") as f:
        r = json.load(f)
    body = json.dumps(r, indent=2)
    notify.send_email("[bot research] {} regime: {}".format(
        r.get("date", "?"), r.get("market_regime", "?")), body)
except FileNotFoundError:
    notify.send_email("[bot research] FAILED", "research.json was not produced today")
PY
