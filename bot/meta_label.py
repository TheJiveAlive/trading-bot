"""Back-fill outcomes into meta_features — completes the meta-label pipeline.

Every buy banks its market-state feature vector (scan._capture_meta_features).
This job joins each unresolved row to the position's eventual exit and stamps
outcome_pct, building the labeled training set for a future meta-model (the
signal-filter from Lopez de Prado's meta-labeling). Runs in the nightly
learning compute. Training itself stays GATED until ~150 labeled rows exist.
"""
import sqlite3
import os

from bot.config import DATA_DIR


def backfill():
    con = sqlite3.connect(os.path.join(DATA_DIR, "ledger.db"))
    try:
        rows = con.execute(
            "SELECT rowid, ts, ticker FROM meta_features WHERE resolved=0").fetchall()
    except sqlite3.OperationalError:
        con.close()
        return 0, 0
    resolved = 0
    for rowid, ts, tkr in rows:
        # the first SELL after the feature snapshot closes the episode
        sell = con.execute(
            "SELECT price FROM trades WHERE ticker=? AND side='sell' AND ts>? "
            "ORDER BY id LIMIT 1", (tkr, ts)).fetchone()
        buy = con.execute(
            "SELECT price FROM trades WHERE ticker=? AND side='buy' AND ts<=? "
            "ORDER BY id DESC LIMIT 1", (tkr, ts)).fetchone()
        if sell and buy and buy[0]:
            pct = (sell[0] / buy[0] - 1) * 100
            con.execute("UPDATE meta_features SET outcome_pct=?, resolved=1 "
                        "WHERE rowid=?", (round(pct, 2), rowid))
            resolved += 1
    con.commit()
    n_labeled = con.execute(
        "SELECT COUNT(*) FROM meta_features WHERE resolved=1").fetchone()[0]
    con.close()
    return resolved, n_labeled


if __name__ == "__main__":
    r, total = backfill()
    print("meta-label: {} newly resolved, {} labeled total "
          "(meta-model trains at ~150)".format(r, total))
