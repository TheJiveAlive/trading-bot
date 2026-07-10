"""Naive news scoring: recent headline volume plus keyword sentiment."""
import datetime as dt

POSITIVE = ("beat", "beats", "surge", "soars", "upgrade", "upgraded", "record",
            "wins", "win", "approval", "approved", "partnership", "contract",
            "raises guidance", "buyback", "acquire", "expands", "growth")
NEGATIVE = ("miss", "misses", "plunge", "plunges", "downgrade", "downgraded",
            "investigation", "lawsuit", "probe", "recall", "offering",
            "dilution", "bankruptcy", "delisting", "cuts guidance", "layoffs")

# Catalyst TAXONOMY — the "training markers" through news. Each headline is
# tagged with its event type so the learning loop can correlate catalyst type
# with trade outcome (e.g. do M&A-driven entries beat analyst-upgrade ones?).
CATALYST_TYPES = {
    "ma": ("acquire", "acquisition", "merger", "takeover", "buyout", "acquires", "to acquire"),
    "earnings_beat": ("beat", "beats", "tops estimates", "record revenue", "record profit"),
    "guidance_up": ("raises guidance", "raises outlook", "raised forecast", "lifts guidance"),
    "analyst_upgrade": ("upgrade", "upgraded", "price target raised", "initiated buy", "outperform"),
    "contract_win": ("contract", "awarded", "wins deal", "selected by", "purchase order"),
    "partnership": ("partnership", "collaboration", "joint venture", "teams up", "agreement with"),
    "regulatory_approval": ("fda approval", "approved", "clearance", "authorization", "designation"),
    "product_launch": ("launch", "unveils", "introduces", "rollout"),
    "insider_buy": ("insider buy", "director buys", "ceo buys", "insider purchase"),
    # negative catalysts (tagged so we can learn to avoid them)
    "offering": ("offering", "dilution", "priced", "registered direct", "atm program"),
    "legal": ("lawsuit", "investigation", "probe", "sec charges", "class action"),
    "downgrade": ("downgrade", "downgraded", "price target cut", "sell rating"),
    "guidance_cut": ("cuts guidance", "lowers outlook", "warns", "profit warning"),
    "delisting": ("delisting", "delisted", "noncompliance", "reverse split"),
}


def classify_catalyst(news_items, window_hours=72):
    """Return the dominant catalyst type from recent headlines, or None.
    This is a training MARKER, not a score — it labels the *kind* of news so
    the learning loop can measure which catalyst types actually pay off."""
    now = dt.datetime.now(dt.timezone.utc)
    hits = {}
    for item in news_items or []:
        title, when = _title_and_date(item)
        if not title:
            continue
        if when and (now - when).total_seconds() > window_hours * 3600:
            continue
        low = title.lower()
        for cat, kws in CATALYST_TYPES.items():
            if any(k in low for k in kws):
                hits[cat] = hits.get(cat, 0) + 1
    if not hits:
        return None
    # prefer the most-mentioned; ties broken by taxonomy order (positive first)
    order = list(CATALYST_TYPES)
    return max(hits, key=lambda c: (hits[c], -order.index(c)))


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
