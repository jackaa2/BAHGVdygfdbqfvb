"""What the robot learns from YouTube results on 📒 Posts (only Shorts live 2+ days count, so numbers are fair).

- streamer_boost: streamers whose Shorts beat our average get picked more often (x0.5 .. x2)
- quiet_hours:    hours of the day (ET) where our Shorts clearly flop get skipped when booking times
Hooks are learned separately (screen.learned_style)."""
import datetime as dt
from zoneinfo import ZoneInfo

import config as C

ET = ZoneInfo("America/New_York")


def _posts(g, sheet):
    out = []
    now = dt.datetime.now(ET)
    for p in g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:J") or []:
        p = p + [""] * (10 - len(p))
        try:
            views = float(str(p[9]).replace(",", ""))
        except ValueError:
            continue
        t = None
        for fmt in ("%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
            try:
                t = dt.datetime.strptime(str(p[7]).strip(), fmt).replace(tzinfo=ET)
                break
            except ValueError:
                pass
        if t is None or now - t < dt.timedelta(hours=48):
            continue
        out.append({"streamer": str(p[4]).strip().lower(), "hour": t.hour, "views": views})
    return out


def streamer_boost(g, sheet):
    posts = _posts(g, sheet)
    if len(posts) < C.LEARN_MIN_POSTS:
        return {}
    avg = sum(p["views"] for p in posts) / len(posts) or 1
    by = {}
    for p in posts:
        by.setdefault(p["streamer"], []).append(p["views"])
    return {s: max(0.5, min(2.0, (sum(v) / len(v)) / avg)) for s, v in by.items() if len(v) >= 3}


def quiet_hours(g, sheet):
    posts = _posts(g, sheet)
    if len(posts) < C.LEARN_MIN_POSTS * 2:
        return set()
    avg = sum(p["views"] for p in posts) / len(posts) or 1
    by = {}
    for p in posts:
        by.setdefault(p["hour"], []).append(p["views"])
    flops = sorted((sum(v) / len(v), h) for h, v in by.items() if len(v) >= 6 and sum(v) / len(v) < 0.4 * avg)
    return {h for _, h in flops[:C.MAX_QUIET_HOURS]}
