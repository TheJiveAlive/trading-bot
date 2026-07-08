"""Reddit/WSB buzz via ApeWisdom (aggregated mentions across investing subs).

Buzz is double-edged for small caps: building interest is confirmation, but a
parabolic mention spike on a cheap stock with no insider support is classic
pump-and-dump shape — that becomes a hard veto in the confluence gate.
"""
import requests

URL = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{}"


def fetch_mentions(pages=2, ttl_min=25):
    """{ticker: {rank, mentions, mentions_prev, upvotes}} or {} on failure.
    Cached ttl_min minutes — Reddit buzz moves slowly and this spares the API
    on frequent dashboard refreshes."""
    import json, os, time
    from bot.config import CACHE_DIR
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "reddit_mentions.json")
    if os.path.exists(cache):
        try:
            with open(cache) as f:
                blob = json.load(f)
            if time.time() - blob["at"] < ttl_min * 60:
                return blob["data"]
        except Exception:
            pass
    out = {}
    try:
        for p in range(1, pages + 1):
            r = requests.get(URL.format(p), timeout=20)
            if r.status_code != 200:
                break
            for row in r.json().get("results", []):
                t = (row.get("ticker") or "").upper()
                if t:
                    out[t] = {
                        "rank": row.get("rank"),
                        "mentions": int(row.get("mentions") or 0),
                        "mentions_prev": int(row.get("mentions_24h_ago") or 0),
                        "upvotes": int(row.get("upvotes") or 0),
                    }
    except Exception:
        pass
    if out:
        try:
            with open(cache, "w") as f:
                json.dump({"at": time.time(), "data": out}, f)
        except Exception:
            pass
    return out


def buzz_accel(info):
    return info["mentions"] / max(info["mentions_prev"], 1)


def reddit_score(info):
    """-0.5..+1.0. Building interest good, parabolic hype bad."""
    if not info or info["mentions"] < 10:
        return 0.0
    score = 0.5
    if (info.get("rank") or 999) <= 25:
        score += 0.25
    accel = buzz_accel(info)
    if 1.5 <= accel <= 4:
        score += 0.25   # interest building at a believable pace
    elif accel > 6:
        score = -0.5    # parabolic: late to someone else's party
    return score


def pump_risk(info, price, n_insiders):
    """True when the shape screams pump: cheap stock, exploding mentions,
    no insider conviction behind it."""
    if not info or price is None:
        return False
    return (price < 5.0 and info["mentions"] >= 30
            and buzz_accel(info) > 4 and n_insiders < 2)
