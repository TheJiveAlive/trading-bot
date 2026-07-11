"""Token-usage tracker. Each Claude workflow pipes its `--output-format json`
result here; we append input/output token counts + cost to
data/token_usage.json so you can see exactly what's eating your subscription.

  claude -p "$(cat prompt)" --output-format json ... > /tmp/c.json
  python -m bot.token_log /tmp/c.json intel
"""
import datetime as dt
import json
import os
import sys

from bot.config import DATA_DIR

LOG = os.path.join(DATA_DIR, "token_usage.json")


def record(json_path, label):
    try:
        with open(json_path) as f:
            res = json.load(f)
    except Exception as e:
        print("token_log: could not read {} ({})".format(json_path, e))
        return
    usage = res.get("usage", {}) if isinstance(res, dict) else {}
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "label": label,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "cost_usd": round(float(res.get("total_cost_usd", 0) or 0), 4)
        if isinstance(res, dict) else 0,
        "duration_ms": res.get("duration_ms", 0) if isinstance(res, dict) else 0,
    }
    data = []
    if os.path.exists(LOG):
        try:
            data = json.load(open(LOG))
        except Exception:
            data = []
    data.append(entry)
    data = data[-500:]   # keep last 500 sessions
    json.dump(data, open(LOG, "w"), indent=2)
    print("token_log: {} in={} out={} cost=${}".format(
        label, entry["input_tokens"], entry["output_tokens"], entry["cost_usd"]))


def summary(days=1):
    if not os.path.exists(LOG):
        return {}
    data = json.load(open(LOG))
    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    recent = [e for e in data if e["ts"] >= cut]
    return {
        "sessions": len(recent),
        "input_tokens": sum(e["input_tokens"] for e in recent),
        "output_tokens": sum(e["output_tokens"] for e in recent),
        "cost_usd": round(sum(e.get("cost_usd", 0) for e in recent), 3),
        "by_label": {lbl: sum(1 for e in recent if e["label"] == lbl)
                     for lbl in set(e["label"] for e in recent)},
    }


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        record(sys.argv[1], sys.argv[2])
    else:
        print(json.dumps(summary(1), indent=2))
