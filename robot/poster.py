"""Posts finished videos to the YouTube channels through Upload-Post, one Short every POST_EVERY_HOURS
per channel. Off until POSTING_ENABLED = True and the UPLOAD_POST_KEY secret is set.

For each clip that is "Ready to Post" and not scheduled yet, every channel that should get it
(see POST_MODE) gets its own version (its own hook + watermark) scheduled into that channel's
next free slot. The schedule is written to the sheet's "📅 Scheduled" column."""
import datetime as dt
import os
import re
import sys
import tempfile
import traceback
from zoneinfo import ZoneInfo

import requests

import config as C
from google_api import Google

ET = ZoneInfo("America/New_York")
API = "https://api.upload-post.com/api/upload"
SCHED_HEAD = "📅 Scheduled"


def col_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_sched(text):
    """'A1 11/18 15:00 · A3 11/18 18:00' -> {1: datetime, 3: datetime}"""
    out = {}
    for a, md, hm in re.findall(r"A(\d) (\d+/\d+) (\d+:\d\d)", text or ""):
        m, d = map(int, md.split("/"))
        h, mi = map(int, hm.split(":"))
        now = dt.datetime.now(ET)
        y = now.year - (1 if m > now.month + 6 else 0)
        out[int(a)] = dt.datetime(y, m, d, h, mi, tzinfo=ET)
    return out


def channels_for(clip_index):
    if C.POST_MODE == "all":
        return sorted(C.CHANNELS)
    chans = sorted(C.CHANNELS)
    return [chans[clip_index % len(chans)]]  # "split": clips take turns across the channels


def main():
    if not C.POSTING_ENABLED:
        print("Posting is off (POSTING_ENABLED = False)"); return
    key = os.environ.get("UPLOAD_POST_KEY")
    if not key:
        print("No UPLOAD_POST_KEY secret yet - posting skipped"); return
    sheet = os.environ["SHEET_ID"]
    g = Google()
    head = [str(h).strip() for h in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]]
    need = {"id": "Clip ID", "status": "Status", "streamer": "Streamer", "platform": "Platform", "top": "🎯 TOP TEXT",
            "h1": "Hook 1", "h2": "Hook 2", "h3": "Hook 3", "h4": "Hook 4", "h5": "Hook 5", "sched": SCHED_HEAD}
    col = {k: head.index(v) for k, v in need.items() if v in head}
    if "sched" not in col:
        raise RuntimeError(f"Control Panel needs a '{SCHED_HEAD}' column")
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:Z", formulas=True)
    cell = lambda r, k: str(r[col[k]]).strip() if k in col and len(r) > col[k] else ""

    # each channel's last booked slot (so posts stay POST_EVERY_HOURS apart)
    now = dt.datetime.now(ET)
    last = {a: None for a in C.CHANNELS}
    already = 0
    for r in rows:
        for a, t in parse_sched(cell(r, "sched")).items():
            if a in last and (last[a] is None or t > last[a]):
                last[a] = t
        if cell(r, "sched"):
            already += 1
    gap = dt.timedelta(hours=C.POST_EVERY_HOURS)
    first = now + dt.timedelta(minutes=15)

    from channels import channel_hooks
    todo = [(i, r) for i, r in enumerate(rows) if cell(r, "status") == "Ready to Post" and not cell(r, "sched")]
    print(f"{len(todo)} clip(s) to schedule")
    with tempfile.TemporaryDirectory() as tmp:
        for n, (i, r) in enumerate(todo):
            clip_id = cell(r, "id")
            hooks = channel_hooks(cell(r, "top"), [cell(r, k) for k in ("h1", "h2", "h3", "h4", "h5")])
            booked = []
            for a in channels_for(already + n):
                slot = max(first, last[a] + gap) if last[a] else first
                name = f"{clip_id}_A{a}.mp4"
                fid = g.find_child(C.ACCOUNT_FOLDERS[a], name, folder=False)
                if not fid:
                    print(f"{clip_id}: {name} not found in channel {a} folder"); continue
                path = g.download(fid, os.path.join(tmp, name))
                title = (hooks.get(a) or f"{cell(r, 'streamer')} in GTA 6").strip()
                title = (title + " #shorts")[:100]
                desc = (f"🎥 {cell(r, 'streamer')} on {cell(r, 'platform') or 'Twitch'}\n"
                        f"{C.POST_HASHTAGS}")
                with open(path, "rb") as f:
                    resp = requests.post(API, headers={"Authorization": f"Apikey {key}",
                                                       "Idempotency-Key": f"{clip_id}-A{a}"},
                                         data={"user": C.UPLOAD_POST_USERS[a], "platform[]": "youtube",
                                               "title": title, "description": desc,
                                               "privacyStatus": C.POST_PRIVACY,
                                               "scheduled_date": slot.strftime("%Y-%m-%dT%H:%M:00"),
                                               "timezone": "America/New_York"},
                                         files={"video": (name, f, "video/mp4")}, timeout=600)
                os.remove(path)
                if resp.status_code >= 300:
                    print(f"{clip_id} -> channel {a}: Upload-Post said {resp.status_code}: {resp.text[:200]}")
                    continue
                last[a] = slot
                booked.append(f"A{a} {slot.month}/{slot.day} {slot:%H:%M}")
                print(f"{clip_id} -> channel {a} at {slot:%a %I:%M %p}")
            if booked:
                rn = C.HEADER_ROWS + 1 + i
                g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col['sched'])}{rn}", [[" · ".join(booked)]])
                g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col['status'])}{rn}", [["Scheduled"]])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
