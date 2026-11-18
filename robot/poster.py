"""Posting, with a human check in between.

Finished videos wait on the 🎬 Review tab. For each row:
  ✅ POST IT ticked               -> uploaded to that channel through Upload-Post, booked into the channel's
                                    next free slot (one Short every POST_EVERY_HOURS), logged on 📒 Posts
  🔁 REDO + ⚠️ CONFIRM REDO ticked -> the clip goes back: new hooks from Claude, new videos, back to Review
Off until POSTING_ENABLED = True and the UPLOAD_POST_KEY secret is set (redo works either way)."""
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
# Review tab columns (0-based)
R_ID, R_CH, R_NAME, R_HOOK, R_WATCH, R_STREAMER, R_POST, R_REDO, R_SURE, R_STATUS, R_LIVE, R_FILE = range(12)


def col_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def ticked(v):
    return str(v).strip().upper() == "TRUE"


def panel(g, sheet):
    head = [str(h).strip() for h in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]]
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:Z", formulas=True)
    return head, rows


def set_panel(g, sheet, head, rows, clip_id, values):
    """values: {header: value} for the Control Panel row of clip_id"""
    ci = head.index("Clip ID")
    for n, r in enumerate(rows):
        if len(r) > ci and str(r[ci]).strip() == clip_id:
            for h, v in values.items():
                if h in head:
                    g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(head.index(h))}{C.HEADER_ROWS + 1 + n}", [[v]])
            return True
    return False


def do_redos(g, sheet, review):
    """Clips with REDO + CONFIRM REDO ticked go back for new hooks + new videos."""
    redo = {str(r[R_ID]).strip() for r in review if len(r) > R_SURE and ticked(r[R_REDO]) and ticked(r[R_SURE])
            and not str(r[R_STATUS]).startswith("📅")}
    if not redo:
        return review
    head, rows = panel(g, sheet)
    for clip_id in redo:
        ok = set_panel(g, sheet, head, rows, clip_id, {
            "🎯 TOP TEXT": "", "Hook 1": "", "Hook 2": "", "Hook 3": "", "Hook 4": "", "Hook 5": "",
            "🚀 SEND": False, "Status": "Waiting for Hook", "Edited Files": ""})
        for r in review:   # old videos go to the Drive trash
            if str(r[R_ID]).strip() == clip_id and len(r) > R_FILE and r[R_FILE]:
                try:
                    g.trash(str(r[R_FILE]).strip())
                except Exception:
                    pass
        print(f"REDO {clip_id}: {'sent back for new hooks + videos' if ok else 'not on the Control Panel any more'}")
    # drop those rows from Review (bottom up so row numbers stay right)
    gid = g.sheet_gid(sheet, C.REVIEW_TAB)
    idx = [i for i, r in enumerate(review) if str(r[R_ID]).strip() in redo]
    g.batch_update(sheet, [{"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS",
                                                          "startIndex": 1 + i, "endIndex": 2 + i}}}
                           for i in sorted(idx, reverse=True)])
    return [r for i, r in enumerate(review) if i not in set(idx)]


def tidy(g, sheet, review, now):
    """Rows already scheduled and live for a day leave the Review tab (the Posts tab keeps them forever)."""
    gid = g.sheet_gid(sheet, C.REVIEW_TAB)
    old = []
    for i, r in enumerate(review):
        if len(r) > R_LIVE and str(r[R_STATUS]).startswith("📅"):
            try:
                live = dt.datetime.strptime(str(r[R_LIVE])[:16], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
                if now - live > dt.timedelta(days=1):
                    old.append(i)
            except ValueError:
                pass
    if old:
        g.batch_update(sheet, [{"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS",
                                                              "startIndex": 1 + i, "endIndex": 2 + i}}}
                               for i in sorted(old, reverse=True)])


def main():
    sheet = os.environ["SHEET_ID"]
    g = Google()
    review = [r + [""] * (12 - len(r)) for r in (g.get_values(sheet, f"'{C.REVIEW_TAB}'!A2:L", formulas=True) or [])]
    review = do_redos(g, sheet, review)

    key = os.environ.get("UPLOAD_POST_KEY")
    if not (C.POSTING_ENABLED and key):
        print("Posting is off (needs POSTING_ENABLED = True and the UPLOAD_POST_KEY secret)"); return
    now = dt.datetime.now(ET)

    # each channel's latest booked slot, from the permanent Posts log
    last = {a: None for a in C.CHANNELS}
    for p in g.get_values(sheet, f"'{C.POSTS_TAB}'!B2:H") or []:
        try:
            a = int(p[0]); t = dt.datetime.strptime(str(p[6])[:16], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
            if a in last and (last[a] is None or t > last[a]):
                last[a] = t
        except (ValueError, IndexError):
            pass
    gap, first = dt.timedelta(hours=C.POST_EVERY_HOURS), now + dt.timedelta(minutes=15)

    head, rows = panel(g, sheet)
    todo = [(i, r) for i, r in enumerate(review) if ticked(r[R_POST]) and not ticked(r[R_REDO])
            and not str(r[R_STATUS]).startswith("📅") and str(r[R_FILE]).strip()]
    print(f"{len(todo)} approved video(s) to schedule")
    with tempfile.TemporaryDirectory() as tmp:
        for i, r in todo:
            clip_id, a = str(r[R_ID]).strip(), int(r[R_CH])
            user = C.UPLOAD_POST_USERS.get(a)
            rn = i + 2
            if not user:
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!J{rn}", [[f"⚠️ No Upload-Post profile set for channel {a}"]])
                continue
            slot = max(first, last[a] + gap) if last[a] else first
            path = g.download(str(r[R_FILE]).strip(), os.path.join(tmp, f"{clip_id}_A{a}.mp4"))
            hook = str(r[R_HOOK]).strip() or f"{r[R_STREAMER]} in GTA 6"
            title = (hook + " #shorts")[:100]
            desc = f"🎥 {r[R_STREAMER]} live on stream\n{C.POST_HASHTAGS}"
            try:
                with open(path, "rb") as f:
                    resp = requests.post(API, headers={"Authorization": f"Apikey {key}",
                                                       "Idempotency-Key": f"{clip_id}-A{a}-{r[R_FILE]}"},
                                         data={"user": user, "platform[]": "youtube", "title": title,
                                               "description": desc, "privacyStatus": C.POST_PRIVACY,
                                               "scheduled_date": slot.strftime("%Y-%m-%dT%H:%M:00"),
                                               "timezone": "America/New_York"},
                                         files={"video": (os.path.basename(path), f, "video/mp4")}, timeout=600)
            finally:
                os.remove(path)
            if resp.status_code >= 300:
                msg = f"⚠️ Upload-Post said {resp.status_code}: {resp.text[:120]}"
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!J{rn}", [[msg]])
                print(f"{clip_id} ch{a}: {msg}")
                continue
            try:
                body = resp.json()
            except ValueError:
                body = {}
            rid = body.get("request_id") or body.get("job_id") or ""
            g.append_rows(sheet, f"'{C.POSTS_TAB}'!A:N", [[
                now.strftime("%Y-%m-%d %H:%M"), a, C.CHANNELS[a], clip_id, r[R_STREAMER], "", hook,
                slot.strftime("%Y-%m-%d %H:%M"), "", "", "", "", rid, ""]])
            g.update_values(sheet, f"'{C.REVIEW_TAB}'!J{rn}:K{rn}",
                            [[f"📅 Scheduled {slot:%a %-I:%M %p}", slot.strftime("%Y-%m-%d %H:%M")]])
            set_panel(g, sheet, head, rows, clip_id, {"Status": "Scheduled"})
            last[a] = slot
            print(f"{clip_id} -> channel {a} at {slot:%a %I:%M %p}")
    tidy(g, sheet, g.get_values(sheet, f"'{C.REVIEW_TAB}'!A2:L") or [], now)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
