"""Pulls YouTube stats from Upload-Post into the sheet (runs at the end of grabs, at most every
ANALYTICS_EVERY_HOURS): channel totals + 30-day daily views on the Analytics tab, and views / likes /
comments / link for every Short on the Posts tab. Marks clips "Posted" on the Control Panel once live."""
import datetime as dt
import os
import sys
import traceback
from zoneinfo import ZoneInfo

import requests

import config as C
from google_api import Google

ET = ZoneInfo("America/New_York")


def parse_et(v):
    """A date-time from the sheet in whatever way it comes back -> datetime (ET), or None."""
    s = str(v or "").strip()
    if not s:
        return None
    try:   # sheet day-number (unformatted)
        f = float(s)
        if 30000 < f < 80000:
            return (dt.datetime(1899, 12, 30) + dt.timedelta(days=f)).replace(tzinfo=ET)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=ET)
        except ValueError:
            continue
    return None
BASE = "https://api.upload-post.com/api"
CHART_ID = 1544922089
MAX_POST_CHECKS = 90          # Upload-Post allows ~100 stat reads per 5 minutes


def find(obj, key):
    """First dict inside obj (any depth) that has `key`."""
    if isinstance(obj, dict):
        if key in obj:
            return obj
        for v in obj.values():
            hit = find(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = find(v, key)
            if hit is not None:
                return hit
    return None


def num(v):
    try:
        return round(float(v))
    except (TypeError, ValueError):
        return ""


def series(ts):
    """reach_timeseries in whatever shape -> {date: value}"""
    out = {}
    if isinstance(ts, dict):
        for k, v in ts.items():
            out[str(k)[:10]] = num(v if not isinstance(v, dict) else v.get("value"))
    elif isinstance(ts, list):
        for p in ts:
            if isinstance(p, dict):
                d = p.get("date") or p.get("day") or p.get("timestamp")
                v = p.get("value", p.get("views", p.get("count")))
                if d:
                    out[str(d)[:10]] = num(v)
            elif isinstance(p, (list, tuple)) and len(p) >= 2:
                out[str(p[0])[:10]] = num(p[1])
    return out


def main():
    key = os.environ.get("UPLOAD_POST_KEY")
    if not (C.POSTING_ENABLED and key):
        print("Analytics: posting not set up yet"); return
    sheet = os.environ["SHEET_ID"]
    g = Google()
    now = dt.datetime.now(ET)
    stamp = (g.get_values(sheet, f"'{C.ANALYTICS_TAB}'!A2") or [[""]])[0]
    stamp = stamp[0] if stamp else ""
    if not os.environ.get("FORCE_ANALYTICS"):
        last = parse_et(stamp.split("Updated: ")[1][:16]) if "Updated: " in stamp else None
        if last and now - last < dt.timedelta(hours=C.ANALYTICS_EVERY_HOURS):
            print("Analytics: refreshed recently, skipping"); return
    H = {"Authorization": f"Apikey {key}"}
    problems = []

    # ---- channel totals + daily views ----
    rows, daily = [], {}
    for a in sorted(C.CHANNELS):
        user = C.UPLOAD_POST_USERS.get(a)
        yt = {}
        if user:
            try:
                r = requests.get(f"{BASE}/analytics/{user}", params={"platforms": "youtube"}, headers=H, timeout=60)
                if r.ok:
                    yt = find(r.json(), "followers") or find(r.json(), "views") or {}
                else:
                    problems.append(f"ch{a} {r.status_code}")
            except requests.RequestException as e:
                problems.append(f"ch{a} {e}")
        wt = yt.get("watch_time_minutes")
        rows.append([num(yt.get("followers")), num(yt.get("views")), num(yt.get("likes")), num(yt.get("comments")),
                     round(float(wt) / 60, 1) if isinstance(wt, (int, float)) else "",
                     num(yt.get("average_view_duration_seconds"))])
        for d, v in series(yt.get("reach_timeseries")).items():
            daily.setdefault(d, {})[a] = v
    g.update_values(sheet, f"'{C.ANALYTICS_TAB}'!C5:H9", rows)
    days = sorted(daily)[-30:]
    table = [[d] + [daily[d].get(a, "") for a in sorted(C.CHANNELS)] for d in days]
    table += [[""] * 6] * (30 - len(table))
    g.update_values(sheet, f"'{C.ANALYTICS_TAB}'!A28:F57", table)
    if days:   # (re)attach the 5 channel lines to the chart now that there is data
        gid = g.sheet_gid(sheet, C.ANALYTICS_TAB)
        src = lambda c: {"sourceRange": {"sources": [{"sheetId": gid, "startRowIndex": 26, "endRowIndex": 57,
                                                      "startColumnIndex": c, "endColumnIndex": c + 1}]}}
        try:
            g.batch_update(sheet, [{"updateChartSpec": {"chartId": CHART_ID, "spec": {
                "title": "Daily views per channel (30 days)",
                "basicChart": {"chartType": "LINE", "legendPosition": "BOTTOM_LEGEND", "headerCount": 1,
                               "domains": [{"domain": src(0)}],
                               "series": [{"series": src(c), "targetAxis": "LEFT_AXIS"} for c in range(1, 6)]}}}}])
        except Exception as e:
            problems.append(f"chart: {e}")

    # ---- every Short we booked: link + views/likes/comments ----
    posts = g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:N")
    cutoff = now - dt.timedelta(days=14)
    live_clips, checked = set(), 0
    for i, p in enumerate(posts):
        p = p + [""] * (14 - len(p))
        rid = str(p[12]).strip()
        if not rid or checked >= MAX_POST_CHECKS:
            continue
        booked = parse_et(p[0]) or now
        if booked < cutoff and p[9] != "":
            continue   # older than 2 weeks: keep the last numbers
        checked += 1
        try:
            r = requests.get(f"{BASE}/uploadposts/post-analytics/{rid}", params={"platform": "youtube"},
                             headers=H, timeout=60)
            if not r.ok:
                continue
            j = r.json()
        except (requests.RequestException, ValueError):
            continue
        hit = find(j, "post_metrics") or {}
        m = hit.get("post_metrics") or {}
        url = hit.get("post_url") or (find(j, "post_url") or {}).get("post_url") or ""
        g.update_values(sheet, f"'{C.POSTS_TAB}'!I{i + 2}:L{i + 2}",
                        [[url, num(m.get("views")), num(m.get("likes")), num(m.get("comments"))]])
        g.update_values(sheet, f"'{C.POSTS_TAB}'!N{i + 2}", [[now.strftime("%Y-%m-%d %H:%M")]])
        if url:
            live_clips.add(str(p[3]).strip())

    # ---- Control Panel: Scheduled -> Posted once YouTube has it ----
    if live_clips:
        head = [str(h).strip() for h in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]]
        ci, si = head.index("Clip ID"), head.index("Status")
        panel = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:Z")
        col = chr(65 + si) if si < 26 else None
        for n, r in enumerate(panel):
            if len(r) > max(ci, si) and str(r[ci]).strip() in live_clips and str(r[si]).strip() == "Scheduled":
                g.update_values(sheet, f"'{C.PANEL_TAB}'!{col}{C.HEADER_ROWS + 1 + n}", [["Posted"]])

    note = f"Updated: {now:%Y-%m-%d %H:%M} ET · {checked} Shorts checked"
    if problems:
        note += " · ⚠️ " + "; ".join(problems)[:200]
    g.update_values(sheet, f"'{C.ANALYTICS_TAB}'!A2", [[note]])
    print(note)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
