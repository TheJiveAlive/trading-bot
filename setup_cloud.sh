#!/bin/zsh
# One-time cloud deployment: code + execution on GitHub Actions, dashboard on
# GitHub Pages. Prerequisites (interactive, do these yourself first):
#   1. Install GitHub CLI:  brew install gh   OR   curl -sS https://webi.sh/gh | sh
#   2. Log in:              gh auth login
# Then run:                 ./setup_cloud.sh
set -e
export PATH="$HOME/.local/bin:$HOME/.local/opt/gh/bin:/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")"

gh auth status > /dev/null || { echo "run 'gh auth login' first"; exit 1 }
USER=$(gh api user -q .login)
BOT_REPO="$USER/trading-bot"
DASH_REPO="$USER/trading-bot-dashboard"

echo "==> 1/6 pushing bot code + state to private repo $BOT_REPO"
git add -A
git commit -q -m "cloud deployment" || true
gh repo create trading-bot --private --source . --push 2>/dev/null || {
  git remote add origin "https://github.com/$BOT_REPO.git" 2>/dev/null || true
  git push -u origin main
}

echo "==> 2/6 setting email secrets from local data/secrets.json"
python3 - <<PY | while IFS='=' read -r k v; do gh secret set "$k" -R "$BOT_REPO" -b "$v"; done
import json
s = json.load(open("data/secrets.json"))
print("SMTP_USER=" + s["smtp_user"])
print("SMTP_APP_PASSWORD=" + s["smtp_app_password"])
print("EMAIL_TO=" + s["email_to"])
PY

echo "==> 3/6 creating public dashboard repo $DASH_REPO with Pages"
(cd publish && gh repo create trading-bot-dashboard --public --source . --push 2>/dev/null || {
  git remote add origin "https://github.com/$DASH_REPO.git" 2>/dev/null || true
  git push -u origin main
})
gh api "repos/$DASH_REPO/pages" -X POST \
  -f "source[branch]=main" -f "source[path]=/" 2>/dev/null || true

echo "==> 4/6 deploy key so Actions can push the dashboard"
ssh-keygen -t ed25519 -N "" -q -f /tmp/dash_deploy_key
gh repo deploy-key add /tmp/dash_deploy_key.pub -R "$DASH_REPO" \
  --allow-write --title "actions-dashboard-push"
gh secret set DASHBOARD_DEPLOY_KEY -R "$BOT_REPO" < /tmp/dash_deploy_key
gh variable set DASHBOARD_REPO -R "$BOT_REPO" -b "$DASH_REPO"
rm -f /tmp/dash_deploy_key /tmp/dash_deploy_key.pub

echo "==> 5/6 disabling LOCAL scan schedule (cloud takes over — no double trading)"
launchctl bootout "gui/$(id -u)/com.josh.tradingbot.scan" 2>/dev/null || true

echo "==> 6/6 triggering a first cloud scan"
gh workflow run trading-scan -R "$BOT_REPO" || true

echo ""
echo "DONE."
echo "  dashboard (live in ~2 min): https://$USER.github.io/trading-bot-dashboard/"
echo "  bot runs & logs:            https://github.com/$BOT_REPO/actions"
echo "  local research task still runs daily on this Mac and pushes to the repo."
