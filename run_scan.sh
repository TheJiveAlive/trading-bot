#!/bin/zsh
# Scheduler wrapper: runs one scan cycle and appends output to logs/cron.log
[ "$(date +%u)" -gt 5 ] && exit 0  # market closed at weekends
cd "$(dirname "$0")"
/usr/bin/python3 run.py scan >> logs/cron.log 2>&1

# publish dashboard to GitHub Pages (no-op until the remote is configured)
if [ -d publish/.git ] && git -C publish remote get-url origin > /dev/null 2>&1; then
  git -C publish add -A
  git -C publish commit -q -m "dashboard update $(date '+%Y-%m-%d %H:%M')" 2>/dev/null
  git -C publish push -q origin main >> logs/cron.log 2>&1
fi
