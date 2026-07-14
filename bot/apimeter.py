"""Tiny API call meter: count(api) buckets calls per UTC day into
data/api_calls.json so quota headroom is a measured number, not a guess.
Fail-silent — metering must never break a data fetch."""
import datetime as dt
import json
import os

from bot.config import DATA_DIR

PATH = os.path.join(DATA_DIR, "api_calls.json")


def count(api):
    try:
        day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        d = {}
        if os.path.exists(PATH):
            d = json.load(open(PATH))
        d.setdefault(day, {})[api] = d.get(day, {}).get(api, 0) + 1
        # keep a rolling week
        for k in [k for k in d if k < (dt.datetime.now(dt.timezone.utc)
                  - dt.timedelta(days=7)).strftime("%Y-%m-%d")]:
            del d[k]
        json.dump(d, open(PATH, "w"))
    except Exception:
        pass
