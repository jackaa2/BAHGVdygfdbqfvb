"""One-off: pick the most-viewed fresh GTA 6 clips right now, N per channel, and send them to Claude + editing.
Learned streamer boost applies (once there's data). Each pick is tagged for its channel so the render lands there."""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import config as C
from google_api import Google
from grab import NSFW_TITLE, col_a1

ET = ZoneInfo("America/New_York")


def main():
    per = int(os.environ.get("RUSH_PER_CHANNEL") or 5)
    hours = int(os.environ.get("RUSH_HOURS") or 24)
    sheet = os.environ["SHEET_ID"]
    g = Google()
    now = dt.datetime.now(ET)
    head = [str(h).strip() for h in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]]
    hx = {h: i for i, h in enumerate(head)}
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:Z", formulas=True)
    cell = lambda r, h: str(r[hx[h]]).strip() if h in hx and len(r) > hx[h] else ""
    try:
        from learn import streamer_boost
        boost = streamer_boost(g, sheet)
    except Exception:
        boost = {}

    def grabbed(v):
        try:
            return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(v))).replace(tzinfo=ET)
        except ValueError:
            try:
                return dt.datetime.strptime(v[:16], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
            except ValueError:
                return None

    # top up: count this rush's picks that are still alive (Claude may have thrown some out)
    have, per_streamer = {a: 0 for a in C.CHANNELS}, {}
    if os.environ.get("RUSH_TOP_UP") == "yes":
        import re
        for r in rows:
            m = re.match(r"🤖 AUTO rush ch(\d)", cell(r, "Notes"))
            if m and cell(r, "✅ YOUR DECISION") != "Reject":
                have[int(m.group(1))] = have.get(int(m.group(1)), 0) + 1
                st = cell(r, "Streamer").lower()
                per_streamer[st] = per_streamer.get(st, 0) + 1
    need = {a: max(0, per - have[a]) for a in C.CHANNELS}
    only = [int(x) for x in (os.environ.get("RUSH_CHANNELS") or "").replace(" ", "").split(",") if x]
    if only:
        need = {a: (n if a in only else 0) for a, n in need.items()}

    cands = []
    for i, r in enumerate(rows):
        if (not cell(r, "Clip ID") or cell(r, "Status") != "New" or cell(r, "✅ YOUR DECISION")
                or cell(r, "Notes") or NSFW_TITLE.search(cell(r, "Clip Title"))):
            continue
        t = grabbed(cell(r, "Grabbed (ET)"))
        if not t or now - t > dt.timedelta(hours=hours):
            continue
        try:
            v = float(cell(r, "Views").replace(",", "") or 0)
        except ValueError:
            v = 0
        cands.append((v * boost.get(cell(r, "Streamer").lower(), 1.0), i))
    cands.sort(reverse=True)

    order = [a for a in sorted(C.CHANNELS)]
    picks, k = [], 0
    for score, i in cands:
        s = cell(rows[i], "Streamer").lower()
        if per_streamer.get(s, 0) >= 4:      # spread it out: max 4 clips per streamer in one rush
            continue
        open_ = [a for a in order if need[a] > 0]
        if not open_:
            break
        a = open_[k % len(open_)]
        k += 1
        need[a] -= 1
        per_streamer[s] = per_streamer.get(s, 0) + 1
        picks.append((i, a, score))
    import time
    for i, a, score in picks:
        time.sleep(1.5)       # stay under Google's per-minute write limit
        rn = C.HEADER_ROWS + 1 + i
        for h, v in (("✅ YOUR DECISION", "Approve"), ("Status", "Waiting for Hook"),
                     ("Notes", f"🤖 AUTO rush ch{a} {now:%m/%d %-I%p}")):
            g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_a1(hx[h])}{rn}", [[v]])
        print(f"rush ch{a}: {cell(rows[i], 'Clip ID')} ({cell(rows[i], 'Streamer')}, {cell(rows[i], 'Views')} views)")
    print(f"Rush: {len(picks)} clip(s) sent to Claude; still short: { {a: n for a, n in need.items() if n} }")
    if picks and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("picked=yes\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
