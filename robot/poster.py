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
                                                          "startIndex": C.REVIEW_HEADER_ROW + i, "endIndex": C.REVIEW_HEADER_ROW + 1 + i}}}
                           for i in sorted(idx, reverse=True)])
    return [r for i, r in enumerate(review) if i not in set(idx)]


def tidy(g, sheet, review, now):
    """Rows already scheduled and live for a day leave the Review tab (the Posts tab keeps them forever)."""
    gid = g.sheet_gid(sheet, C.REVIEW_TAB)
    old = []
    for i, r in enumerate(review):
        if len(r) > R_LIVE and str(r[R_STATUS]).startswith("📅"):
            live = parse_et(r[R_LIVE])
            if live and now - live > dt.timedelta(days=1):
                old.append(i)
    if old:
        g.batch_update(sheet, [{"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS",
                                                              "startIndex": C.REVIEW_HEADER_ROW + i, "endIndex": C.REVIEW_HEADER_ROW + 1 + i}}}
                               for i in sorted(old, reverse=True)])


def backfill(g, sheet, review):
    """Finished clips that aren't on the Review tab yet (e.g. made before it existed) get added."""
    from channels import channel_hooks
    head, rows = panel(g, sheet)
    need = ["Clip ID", "Status", "Streamer", "🎯 TOP TEXT"]
    if any(h not in head for h in need):
        return False
    hx = {h: head.index(h) for h in head}
    cell = lambda r, h: str(r[hx[h]]).strip() if h in hx and len(r) > hx[h] else ""
    on_review = {str(r[R_ID]).strip() for r in review}
    booked = {str(p[0]).strip() for p in (g.get_values(sheet, f"'{C.POSTS_TAB}'!D2:D") or []) if p}
    turn = len(booked) + len(review)
    add = []
    for r in rows:
        cid = cell(r, "Clip ID")
        if not cid or cell(r, "Status") != "Ready to Post" or cid in on_review or cid in booked:
            continue
        hooks = channel_hooks(cell(r, "🎯 TOP TEXT"), [cell(r, f"Hook {k}") for k in range(1, 6)])
        chans = sorted(C.CHANNELS) if C.POST_MODE == "all" else \
            [sorted(C.CHANNELS)[(turn + k) % len(C.CHANNELS)] for k in range(len(C.CHANNELS))]
        for a in chans:
            fid = g.find_child(C.ACCOUNT_FOLDERS[a], f"{cid}_A{a}.mp4", folder=False)
            if not fid:
                continue
            add.append([cid, a, C.CHANNELS[a], hooks.get(a, cell(r, "🎯 TOP TEXT")),
                        f'=HYPERLINK("https://drive.google.com/file/d/{fid}/view","▶ watch")', cell(r, "Streamer"),
                        False, False, False, "👀 Watch it, then tick POST IT", "", fid])
            if C.POST_MODE != "all":
                turn += 1
                break
    if add:
        from channels import add_review_rows
        add_review_rows(g, sheet, add)
        print(f"Review: added {len(add)} finished video(s)")
    return bool(add)


def main():
    sheet = os.environ["SHEET_ID"]
    g = Google()
    review = [r + [""] * (12 - len(r)) for r in (g.get_values(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW + 1}:L", formulas=True) or [])]
    review = do_redos(g, sheet, review)
    # videos whose clip the week-old clean-up already removed can't be posted any more: take them off Review
    head0, rows0 = panel(g, sheet)
    if "Clip ID" in head0 and rows0:
        alive = {str(r[head0.index("Clip ID")]).strip() for r in rows0 if len(r) > head0.index("Clip ID")}
        gone = [i for i, r in enumerate(review) if str(r[R_ID]).strip() not in alive
                and not str(r[R_STATUS]).startswith("📅")]
        if gone:
            gid = g.sheet_gid(sheet, C.REVIEW_TAB)
            g.batch_update(sheet, [{"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS",
                "startIndex": C.REVIEW_HEADER_ROW + i, "endIndex": C.REVIEW_HEADER_ROW + 1 + i}}}
                for i in sorted(gone, reverse=True)])
            review = [r for i, r in enumerate(review) if i not in set(gone)]
            print(f"Review: removed {len(gone)} expired video(s)")
    if backfill(g, sheet, review):
        review = [r + [""] * (12 - len(r)) for r in (g.get_values(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW + 1}:L", formulas=True) or [])]

    key = os.environ.get("UPLOAD_POST_KEY")
    if not (C.POSTING_ENABLED and key):
        print("Posting is off (needs POSTING_ENABLED = True and the UPLOAD_POST_KEY secret)"); return
    now = dt.datetime.now(ET)

    # each channel's latest booked slot, from the permanent Posts log
    last = {a: None for a in C.CHANNELS}
    clip_times = {}   # clip -> every time it's already booked (on any channel)
    for p in g.get_values(sheet, f"'{C.POSTS_TAB}'!B2:H") or []:
        try:
            a = int(p[0]); t = parse_et(p[6])
            if t is None:
                continue
            if a in last and (last[a] is None or t > last[a]):
                last[a] = t
            clip_times.setdefault(str(p[2]).strip(), []).append(t)
        except (ValueError, IndexError):
            pass
    gap, first = dt.timedelta(hours=C.POST_EVERY_HOURS), now + dt.timedelta(minutes=15)
    booked = {a: set() for a in C.CHANNELS}
    for p in g.get_values(sheet, f"'{C.POSTS_TAB}'!B2:H") or []:
        try:
            t = parse_et(p[6])
            if t:
                booked[int(p[0])].add(t)
        except (ValueError, IndexError, KeyError):
            pass

    def next_slot(a, after):
        """Fixed timetable: every POST_EVERY_HOURS, each channel offset a little so they don't all post
        at the same minute (ch1 :00, ch2 +36 min, ch3 +72 ...). First free slot after `after`."""
        step = C.POST_EVERY_HOURS * 60
        offset = (a - 1) * step // len(C.CHANNELS)
        day0 = after.replace(hour=0, minute=0, second=0, microsecond=0)
        t = day0 + dt.timedelta(minutes=offset)
        while t < after or t in booked[a]:
            t += dt.timedelta(minutes=step)
        return t

    head, rows = panel(g, sheet)
    todo = [(i, r) for i, r in enumerate(review) if ticked(r[R_POST]) and not ticked(r[R_REDO])
            and not str(r[R_STATUS]).startswith("📅") and str(r[R_FILE]).strip()]
    print(f"{len(todo)} approved video(s) to schedule")
    with tempfile.TemporaryDirectory() as tmp:
        for i, r in todo:
            clip_id, a = str(r[R_ID]).strip(), int(r[R_CH])
            user = C.UPLOAD_POST_USERS.get(a)
            rn = i + C.REVIEW_HEADER_ROW + 1
            if not user:
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!J{rn}", [[f"⚠️ No Upload-Post profile set for channel {a}"]])
                continue
            slot = next_slot(a, first)
            # the same clip never goes out on two channels close together (so YouTube doesn't see
            # copies of each other): keep it SAME_CLIP_GAP_HOURS away from its other bookings
            spread = dt.timedelta(hours=C.SAME_CLIP_GAP_HOURS)
            for _ in range(50):
                clash = [t for t in clip_times.get(clip_id, []) if abs(t - slot) < spread]
                if not clash:
                    break
                slot = next_slot(a, max(clash) + spread)
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
            booked[a].add(slot)
            clip_times.setdefault(clip_id, []).append(slot)
            print(f"{clip_id} -> channel {a} at {slot:%a %I:%M %p}")
    tidy(g, sheet, g.get_values(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW + 1}:L") or [], now)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
