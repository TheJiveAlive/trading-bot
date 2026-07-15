#!/bin/bash
# Box-native exit loop for the stock bot (optiplex, every 5 min via
# rh-exits.timer). Exists because GitHub's */5 scheduled cron for prices.yml
# actually fired 2-4x/DAY under free-tier throttling (verified 2026-07-15:
# Jul-14 3 runs, Jul-13 2 runs) — stops were only being checked a couple of
# times a day. The box's systemd clock is ours: exits now check every 5 min
# of US market hours regardless of GitHub's scheduler mood. CI's own exits
# step stays as a rarely-firing backup; double-run risk is the same class
# the CI already tolerates between scan.yml and prices.yml overlap.
set -euo pipefail
cd "$HOME/rh"

# US market-hours guard (mirrors prices.yml)
H=$(TZ=America/New_York date +%H); M=$(TZ=America/New_York date +%M)
DOW=$(TZ=America/New_York date +%u)
if [ "$DOW" -gt 5 ] || [ "$H" -lt 9 ] || [ "$H" -ge 16 ] || { [ "$H" -eq 9 ] && [ "$M" -lt 30 ]; }; then
  exit 0
fi

# fresh code + state (same -X theirs posture as boxwatch sync_repo)
git pull --rebase -X theirs -q origin main || true

# broker/API secrets live outside the repo on the box
install -m 600 "$HOME/.bot/secrets.json" data/secrets.json

./venv/bin/python3 run.py exits >> logs/box_exits.log 2>&1 || true

# NOTE (2026-07-15): do NOT delete data/secrets.json here — that pattern
# belongs to EPHEMERAL GitHub runners. On the box this file is the SHARED
# runtime copy used by the session loop, agents and monitors; deleting it
# every 5 min took T212/Alpaca dark mid-session. Vault stays the source.
git add -A data dashboard.html radar.html history.html 2>/dev/null || true
if ! git diff --cached --quiet; then
  git -c user.name=trading-bot -c user.email=trading-bot@users.noreply.github.com \
    commit -q -m "box exits $(date -u '+%Y-%m-%d %H:%M') UTC"
  for i in 1 2 3; do
    git pull --rebase -X theirs -q origin main && git push -q && break
    sleep 3
  done
fi
