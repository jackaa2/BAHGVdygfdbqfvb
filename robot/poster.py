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
R_ID, R_CH, R_NAME, R_HOOK, R_WATCH, R_STREAMER, R_POST, R_BAD, R_ADDED, R_STATUS, R_LIVE, R_FILE, R_BATCH = range(13)
NCOL = 13
WAITING = "👀 In the next batch reel"


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


def redo_clip(g, sheet, head, rows, clip_id, file_id):
    """👎 clip: back for new hooks + a new video (it shows up again in a later batch)."""
    set_panel(g, sheet, head, rows, clip_id, {
        "🎯 TOP TEXT": "", "Hook 1": "", "Hook 2": "", "Hook 3": "", "Hook 4": "", "Hook 5": "",
        "🚀 SEND": False, "Status": "Waiting for Hook", "Edited Files": ""})
    if file_id:
        try:
            g.trash(file_id)
        except Exception:
            pass
    print(f"REDO {clip_id}")


def delete_rows(g, sheet, idx):
    if not idx:
        return
    gid = g.sheet_gid(sheet, C.REVIEW_TAB)
    g.batch_update(sheet, [{"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS",
                                                          "startIndex": C.REVIEW_HEADER_ROW + i,
                                                          "endIndex": C.REVIEW_HEADER_ROW + 1 + i}}}
                           for i in sorted(set(idx), reverse=True)])


def read_review(g, sheet):
    return [r + [""] * (NCOL - len(r)) for r in
            (g.get_values(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW + 1}:M", formulas=True) or [])]


def is_header(r):
    return str(r[R_ID]).startswith("BATCH ")


def backfill(g, sheet, review):
    """Finished clips that aren't on the Review tab yet get added (waiting for the next batch)."""
    from channels import channel_hooks, add_review_rows, review_row
    head, rows = panel(g, sheet)
    if any(h not in head for h in ("Clip ID", "Status", "Streamer", "🎯 TOP TEXT")):
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
            add.append(review_row(cid, a, hooks.get(a, cell(r, "🎯 TOP TEXT")), cell(r, "Streamer"), fid))
            if C.POST_MODE != "all":
                turn += 1
                break
    if add:
        add_review_rows(g, sheet, add)
        print(f"Review: added {len(add)} finished video(s)")
    return bool(add)


def being_made(head, rows):
    if "Status" not in head or "✅ YOUR DECISION" not in head:
        return 0
    si, di = head.index("Status"), head.index("✅ YOUR DECISION")
    return sum(1 for r in rows if len(r) > max(si, di) and str(r[di]).strip() == "Approve"
               and str(r[si]).strip() in ("Pending", "Waiting for Hook"))


def make_batch(g, sheet, review, now):
    """Loose finished videos -> one batch with a numbered review reel. Waits until the robot has finished
    the clips it's still making (or the oldest one has waited BATCH_MAX_WAIT_MIN), so a batch is complete."""
    loose = [i for i, r in enumerate(review) if not is_header(r) and not str(r[R_BATCH]).strip()
             and not str(r[R_STATUS]).startswith("📅")]
    if not loose:
        return False
    head, rows = panel(g, sheet)
    ages = [now - (parse_et(review[i][R_ADDED]) or now - dt.timedelta(days=1)) for i in loose]
    oldest = max(ages)
    if oldest < dt.timedelta(minutes=C.BATCH_MAX_WAIT_MIN) and (being_made(head, rows) or len(loose) < C.BATCH_MIN_CLIPS):
        print(f"Batch: {len(loose)} video(s) waiting for more before making a reel")
        return False
    loose = loose[:C.BATCH_MAX_CLIPS]
    loose.sort(key=lambda i: (int(review[i][R_CH] or 0), i))   # organised by channel: Ch1 first ... Ch5 last
    bid = now.strftime("%m%d-%H%M")
    reel_fid = ""
    try:
        from reel import make_reel
        with tempfile.TemporaryDirectory() as tmp:
            items = []
            for n, i in enumerate(loose, 1):
                r = review[i]
                p = g.download(str(r[R_FILE]).strip(), os.path.join(tmp, f"{n}.mp4"))
                items.append((p, n, f"Ch{r[R_CH]} · {r[R_STREAMER]}"))
            out = make_reel(items, os.path.join(tmp, f"REEL_{bid}.mp4"))
            folder = g.ensure_folder(C.ROOT_FOLDER[0], "🎬 Review reels")
            reel_fid = g.upload(out, f"REEL_{bid}.mp4", folder)
    except Exception as e:
        print(f"reel failed ({e}) - batch made anyway, use each clip's ▶ watch link")
    watch = (f'=HYPERLINK("https://drive.google.com/file/d/{reel_fid}/view","▶ WATCH REEL")' if reel_fid
             else "reel failed - use the ▶ watch links")
    header = [f"BATCH {bid}", "", f"🎬 BATCH {now:%a %-I:%M %p} · {len(loose)} clips", watch, "", "",
              False, "", now.strftime("%Y-%m-%d %H:%M"),
              "👀 Watch the reel · 👎 any bad ones · then tick ✅ POST ALL", "", reel_fid, bid]
    clips = []
    for n, i in enumerate(loose, 1):
        r = list(review[i])
        r[R_NAME] = f"#{n} · Ch{r[R_CH]} · {C.CHANNELS.get(int(r[R_CH]), '')}"
        r[R_POST], r[R_BAD], r[R_BATCH], r[R_STATUS] = False, False, bid, "👀 In the reel above"
        clips.append(r)
    delete_rows(g, sheet, loose)
    where = g.append_rows(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW}:M", [header] + clips)
    m = re.search(r"![A-Z]+(\d+):[A-Z]+(\d+)", where or "")
    if m:
        first, last = int(m.group(1)), int(m.group(2))
        gid = g.sheet_gid(sheet, C.REVIEW_TAB)
        g.batch_update(sheet, [
            {"setDataValidation": {"range": {"sheetId": gid, "startRowIndex": first - 1, "endRowIndex": first,
                                             "startColumnIndex": R_POST, "endColumnIndex": R_POST + 1},
                                   "rule": {"condition": {"type": "BOOLEAN"}}}},
            {"setDataValidation": {"range": {"sheetId": gid, "startRowIndex": first, "endRowIndex": last,
                                             "startColumnIndex": R_BAD, "endColumnIndex": R_BAD + 1},
                                   "rule": {"condition": {"type": "BOOLEAN"}}}},
            {"setDataValidation": {"range": {"sheetId": gid, "startRowIndex": first, "endRowIndex": last,
                                             "startColumnIndex": R_POST, "endColumnIndex": R_POST + 1},
                                   "rule": {"condition": {"type": "BOOLEAN"}}}},
        ])
    print(f"Batch {bid}: {len(loose)} clip(s), reel {'ok' if reel_fid else 'FAILED'}")
    return True


def main():
    sheet = os.environ["SHEET_ID"]
    g = Google()
    now = dt.datetime.now(ET)
    review = read_review(g, sheet)

    # clips the week-old clean-up already removed can't be posted any more: take them off Review
    head0, rows0 = panel(g, sheet)
    if "Clip ID" in head0:
        ci = head0.index("Clip ID")
        alive = {str(r[ci]).strip() for r in rows0 if len(r) > ci}
        gone = [i for i, r in enumerate(review) if not is_header(r) and str(r[R_ID]).strip() not in alive
                and not str(r[R_STATUS]).startswith("📅")]
        if gone and alive:
            delete_rows(g, sheet, gone)
            print(f"Review: removed {len(gone)} expired video(s)")
            review = read_review(g, sheet)
    if backfill(g, sheet, review):
        review = read_review(g, sheet)
    if make_batch(g, sheet, review, now):
        review = read_review(g, sheet)

    key = os.environ.get("UPLOAD_POST_KEY")
    posting = C.POSTING_ENABLED and key

    # ---- batches you approved (✅ POST ALL) ----
    booked = {a: set() for a in C.CHANNELS}
    clip_times = {}
    for p in g.get_values(sheet, f"'{C.POSTS_TAB}'!B2:H") or []:
        try:
            t = parse_et(p[6])
            if t:
                booked[int(p[0])].add(t)
                clip_times.setdefault(str(p[2]).strip(), []).append(t)
        except (ValueError, IndexError, KeyError):
            pass
    first = now + dt.timedelta(minutes=15)

    def next_slot(a, after):
        """Fixed timetable: every POST_EVERY_HOURS, channels staggered (ch1 :00, ch2 +36 min, ...)."""
        step = C.POST_EVERY_HOURS * 60
        offset = (a - 1) * step // len(C.CHANNELS)
        t = after.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(minutes=offset)
        while t < after or t in booked[a]:
            t += dt.timedelta(minutes=step)
        return t

    head, rows = panel(g, sheet)
    drop = []
    with tempfile.TemporaryDirectory() as tmp:
        for hi, h in enumerate(review):
            if not is_header(h) or str(h[R_STATUS]).startswith("✅"):
                continue
            auto = (C.AUTO_POST_AFTER_HOURS and parse_et(h[R_ADDED]) and
                    now - parse_et(h[R_ADDED]) > dt.timedelta(hours=C.AUTO_POST_AFTER_HOURS))
            all_ = bool(ticked(h[R_POST]) or auto)
            bid0 = str(h[R_BATCH]).strip()
            singles = [r for r in review if not is_header(r) and str(r[R_BATCH]).strip() == bid0
                       and ticked(r[R_POST]) and not str(r[R_STATUS]).startswith("📅")]
            if not (all_ or singles):
                continue
            if not posting:
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!J{hi + C.REVIEW_HEADER_ROW + 1}",
                                [["⚠️ Posting isn't switched on yet"]])
                continue
            bid = str(h[R_BATCH]).strip()
            done = remade = failed = 0
            for i, r in enumerate(review):
                if is_header(r) or str(r[R_BATCH]).strip() != bid or str(r[R_STATUS]).startswith("📅"):
                    continue
                clip_id, a, rn = str(r[R_ID]).strip(), int(r[R_CH]), i + C.REVIEW_HEADER_ROW + 1
                if not all_ and not ticked(r[R_POST]):
                    continue          # only the ones you ticked one by one
                if ticked(r[R_BAD]) and not ticked(r[R_POST]):
                    redo_clip(g, sheet, head, rows, clip_id, str(r[R_FILE]).strip())
                    drop.append(i); remade += 1
                    continue
                user = C.UPLOAD_POST_USERS.get(a)
                slot = next_slot(a, first)
                spread = dt.timedelta(hours=C.SAME_CLIP_GAP_HOURS)
                for _ in range(50):   # same clip never close to itself on another channel
                    clash = [t for t in clip_times.get(clip_id, []) if abs(t - slot) < spread]
                    if not clash:
                        break
                    slot = next_slot(a, max(clash) + spread)
                hook = str(r[R_HOOK]).strip() or f"{r[R_STREAMER]} in GTA 6"
                try:
                    path = g.download(str(r[R_FILE]).strip(), os.path.join(tmp, f"{clip_id}_A{a}.mp4"))
                    with open(path, "rb") as f:
                        resp = requests.post(API, headers={"Authorization": f"Apikey {key}",
                                                           "Idempotency-Key": f"{clip_id}-A{a}-{r[R_FILE]}"},
                                             data={"user": user, "platform[]": "youtube",
                                                   "title": (hook + " #shorts")[:100],
                                                   "description": f"🎥 {r[R_STREAMER]} live on stream\n{C.POST_HASHTAGS}",
                                                   "privacyStatus": C.POST_PRIVACY,
                                                   "scheduled_date": slot.strftime("%Y-%m-%dT%H:%M:00"),
                                                   "timezone": "America/New_York"},
                                             files={"video": (os.path.basename(path), f, "video/mp4")}, timeout=600)
                    os.remove(path)
                except Exception as e:
                    resp = None
                    err = str(e)[:100]
                if resp is None or resp.status_code >= 300:
                    msg = f"⚠️ {err if resp is None else f'Upload-Post said {resp.status_code}: {resp.text[:90]}'}"
                    g.update_values(sheet, f"'{C.REVIEW_TAB}'!J{rn}", [[msg]])
                    print(f"{clip_id} ch{a}: {msg}"); failed += 1
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
                done += 1
                print(f"{clip_id} -> channel {a} at {slot:%a %I:%M %p}")
            note = f"✅ {done} booked" + (f" · {remade} remade" if remade else "") + \
                   (f" · ⚠️ {failed} failed (tick POST ALL again to retry)" if failed else "") + \
                   (" · auto-posted" if auto and not ticked(h[R_POST]) else "")
            if failed:
                note = note.replace("✅", "⏳", 1)
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!G{hi + C.REVIEW_HEADER_ROW + 1}", [[False]])
            if not all_:   # only some clips posted one by one: the batch stays open for the rest
                note = f"👀 {done} posted one by one · tick ✅ on the rest, or ✅ POST ALL here"
            g.update_values(sheet, f"'{C.REVIEW_TAB}'!J{hi + C.REVIEW_HEADER_ROW + 1}", [[note]])
    delete_rows(g, sheet, drop)

    # ---- tidy: a batch leaves Review a day after its last post went live (📒 Posts keeps everything) ----
    review = read_review(g, sheet)
    old = []
    for hi, h in enumerate(review):
        if not is_header(h):
            continue
        bid = str(h[R_BATCH]).strip()
        mine = [i for i, r in enumerate(review) if not is_header(r) and str(r[R_BATCH]).strip() == bid]
        lives = [parse_et(review[i][R_LIVE]) for i in mine]
        if not str(h[R_STATUS]).startswith("✅") and not (mine and all(lives)):
            continue
        if all(lives) and (not lives or now - max(lives) > dt.timedelta(days=1)):
            old += [hi] + mine
            if str(h[R_FILE]).strip():
                try:
                    g.trash(str(h[R_FILE]).strip())
                except Exception:
                    pass
    delete_rows(g, sheet, old)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
