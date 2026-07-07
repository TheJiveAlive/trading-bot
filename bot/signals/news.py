"""Naive news scoring: recent headline volume plus keyword sentiment."""
import datetime as dt

POSITIVE = ("beat", "beats", "surge", "soars", "upgrade", "upgraded", "record",
            "wins", "win", "approval", "approved", "partnership", "contract",
            "raises guidance", "buyback", "acquire", "expands", "growth")
NEGATIVE = ("miss", "misses", "plunge", "plunges", "downgrade", "downgraded",
            "investigation", "lawsuit", "probe", "recall", "offering",
            "dilution", "bankruptcy", "delisting", "cuts guidance", "layoffs")


def _title_and_date(item):
    content = item.get("content") or {}
    title = content.get("title") or item.get("title") or ""
    pub = content.get("pubDate") or ""
    when = None
    if pub:
        try:
            when = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            pass
    elif item.get("providerPublishTime"):
        when = dt.datetime.fromtimestamp(item["providerPublishTime"], dt.timezone.utc)
    return title, when


def news_score(news_items, window_hours=48):
    """-2..+2 from headlines within the window."""
    now = dt.datetime.now(dt.timezone.utc)
    score, recent = 0.0, 0
    for item in news_items:
        title, when = _title_and_date(item)
        if not title:
            continue
        if when and (now - when).total_seconds() > window_hours * 3600:
            continue
        recent += 1
        low = title.lower()
        score += sum(0.5 for w in POSITIVE if w in low)
        score -= sum(0.7 for w in NEGATIVE if w in low)
    if recent >= 3:
        score += 0.3
    return max(-2.0, min(score, 2.0))
