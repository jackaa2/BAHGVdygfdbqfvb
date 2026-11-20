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
        if t is None or now - t < dt.timedelta(hours=24):
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


def trust(g, sheet):
    """How much your reviews agree with the robot: of the last clips YOU reviewed, how many you approved
    (📒 Posts made by you) vs marked 👎 (🗒 Feedback). Autopilot posts don't count."""
    events = []
    for p in g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:O") or []:
        p = p + [""] * (15 - len(p))
        if str(p[14]).strip() != "autopilot" and p[0]:
            events.append((str(p[0])[:16], 1))
    for f in g.get_values(sheet, f"'{C.FEEDBACK_TAB}'!A2:F") or []:
        if f and f[0]:
            events.append((str(f[0])[:16], 0))
    events.sort()
    last = events[-C.AUTOPILOT_WINDOW:]
    n = len(last)
    rate = (sum(v for _, v in last) / n) if n else 0.0
    return n, rate


def autopilot(g, sheet):
    """Returns (on, why). Mode is the 🤖 dropdown on the Review tab:
    OFF = always wait for you · EARN IT = turns on by itself once your reviews show the robot is good enough · ON."""
    try:
        mode = str((g.get_values(sheet, f"'{C.REVIEW_TAB}'!{C.AUTOPILOT_CELL}") or [[""]])[0][0]).upper()
    except Exception:
        mode = ""
    n, rate = trust(g, sheet)
    stats = f"{rate:.0%} approved of your last {n} reviews"
    if "OFF" in mode:
        return False, f"off · {stats}"
    if mode.endswith(" ON") or mode == "ON" or "ALWAYS" in mode:
        return True, f"on · {stats}"
    if n >= C.AUTOPILOT_MIN_REVIEWS and rate >= C.AUTOPILOT_MIN_APPROVAL:
        return True, f"earned · {stats}"
    need = max(0, C.AUTOPILOT_MIN_REVIEWS - n)
    return False, (f"learning · {stats} · needs {C.AUTOPILOT_MIN_APPROVAL:.0%}"
                   + (f" over {need} more reviews" if need else ""))
