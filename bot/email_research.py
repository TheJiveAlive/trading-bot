"""Format data/research.json into a branded markdown email.

The daily-research workflow used to dump raw JSON into a plain-text email;
this renders the same content as the branded dark card used by the review /
learnings reports (via notify.send_email markdown=True).
"""
import json


def _regime_badge(regime):
    r = (regime or "").lower()
    icon = {"risk_on": "🟢", "risk_off": "🔴", "neutral": "🟡"}.get(r, "⚪")
    return "{} **{}**".format(icon, (regime or "unknown").replace("_", " ").upper())


def build(research):
    """(subject, markdown) from a research dict. Tolerant of missing keys."""
    date = research.get("date", "")
    regime = research.get("market_regime", "")
    lines = []

    lines.append("## Daily market research — {}".format(date))
    lines.append("")
    lines.append("**Regime:** {}".format(_regime_badge(regime)))
    reason = research.get("regime_reason")
    if reason:
        lines.append("")
        lines.append(reason)

    bias = research.get("sector_bias") or {}
    if bias:
        lines.append("")
        lines.append("### Sector bias")
        for sec, val in sorted(bias.items(), key=lambda kv: -kv[1]):
            arrow = "▲" if val > 0 else ("▼" if val < 0 else "—")
            lines.append("- {} **{}** — {:+.1f}".format(arrow, sec, val))

    watch = research.get("watchlist") or []
    if watch:
        lines.append("")
        lines.append("### Watchlist")
        for w in watch:
            if isinstance(w, dict):
                tk = w.get("ticker", "?")
                note = w.get("note", "")
                lines.append("- **{}** — {}".format(tk, note))
            else:
                lines.append("- **{}**".format(w))

    avoid = research.get("avoid") or []
    if avoid:
        lines.append("")
        lines.append("### Avoid")
        for a in avoid:
            if isinstance(a, dict):
                lines.append("- **{}** — {}".format(a.get("ticker", "?"), a.get("note", "")))
            else:
                lines.append("- {}".format(a))

    notes = research.get("notes")
    if notes:
        lines.append("")
        lines.append("### Notes")
        lines.append(notes if isinstance(notes, str) else json.dumps(notes))

    regime_short = (regime or "").replace("_", " ")
    subject = "[bot research] {} — {}".format(date or "daily", regime_short or "market brief")
    return subject, "\n".join(lines)


def main():
    from bot import config, notify
    config.load()
    try:
        research = json.load(open("data/research.json"))
        subject, md = build(research)
    except Exception as e:
        subject, md = "[bot research] FAILED to produce research.json", "Error: {}".format(e)
    notify.send_email(subject, md, markdown=True)


if __name__ == "__main__":
    main()
