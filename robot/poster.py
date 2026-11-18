"""Posting, with a human check in between.

Finished videos wait on the 🎬 Review tab. For each row:
  ✅ POST IT ticked               -> uploaded to that channel through Upload-Post, booked into the channel's
                                    next free slot (one Short every POST_EVERY_HOURS), logged on 📒 Posts
  🔁 REDO + ⚠️ CONFIRM REDO ticked -> the clip goes back: new hooks from Claude, new videos, back to Review
Off until POSTING_ENABLED = True and the UPLOAD_POST_KEY secret is set (redo works either way)."""
import datetime as dt
import json
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
R_ID, R_CH, R_NAME, R_HOOK, R_WATCH, R_STREAMER, R_POST, R_SURE, R_BAD, R_REDO, R_STATUS, R_LIVE, R_FILE, R_BATCH, \
    R_ADDED = range(15)
NCOL = 15
L = lambda i: chr(65 + i)        # column letter
WAITING = "👀 In the next batch reel"


def col_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def ticked(v):
    return str(v).strip().upper() == "TRUE"


def bad_reason(v):
    v = str(v).strip()
    return "" if v.upper() in ("", "FALSE") else ("Hook is bad" if v.upper() == "TRUE" else v)


def panel(g, sheet):
    head = [str(h).strip() for h in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]]
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:Z", formulas=True)
    return head, rows


def set_panel(g, sheet, head, rows, clip_id, values):
    """values: {header: value} for the Control Panel row of clip_id. Finds the row fresh every time
    (the grabber re-sorts that sheet, so an older row number could point at a different clip)."""
    ci = head.index("Clip ID")
    ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(ci)}{C.HEADER_ROWS + 1}:{col_letter(ci)}") or []
    for n, r in enumerate(ids):
        if r and str(r[0]).strip() == clip_id:
            for h, v in values.items():
                if h in head:
                    g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(head.index(h))}{C.HEADER_ROWS + 1 + n}", [[v]])
            return True
    return False


def title_and_tags(hook, streamer, clip_id):
    """Title = the hook on that video + tags, under YouTube's 100 characters.
    The hook always stays whole; tags are added best-first (TAG_BANK order) and the worst ones are the
    ones that don't make it. Only if the hook can't fit next to #GTA6 #shorts does the hook get shortened."""
    bank = [t if t.startswith("#") else "#" + t for t in (C.TAG_BANK or []) if t.strip()]
    core = ["#GTA6", "#shorts"]
    ranked = list(dict.fromkeys(core + bank))          # best first, no repeats
    LIMIT = 95                                         # a little under 100: emojis can count double
    room = LIMIT - sum(len(t) + 1 for t in core)
    title = hook.strip()
    if len(title) > room:                              # last resort: shorten the hook at a word break
        cut = title[:room].rsplit(" ", 1)[0].rstrip(" ,.-!?")
        title = cut if len(cut) >= room // 2 else title[:room].rstrip()
    for t in ranked:
        if len(title) + 1 + len(t) <= LIMIT:
            title += " " + t
    streamer_tag = "#" + "".join(ch for ch in streamer if ch.isalnum())
    desc_tags = " ".join(dict.fromkeys(ranked[:2] + [streamer_tag] + ranked[2:17]))
    desc = f"🎥 {streamer} live on stream\n\n{desc_tags}"
    yt_tags = ",".join(t.lstrip("#") for t in dict.fromkeys(ranked[:2] + [streamer_tag] + ranked[2:]))[:480]
    return title, desc, yt_tags


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


def wrong_channels(key):
    """Channels whose Upload-Post profile is connected to a DIFFERENT one of our YouTube channels."""
    norm = lambda x: re.sub(r"[^a-z0-9]", "", str(x).lower())
    try:
        r = requests.get("https://api.upload-post.com/api/uploadposts/users",
                         headers={"Authorization": f"Apikey {key}"}, timeout=60)
        profiles = {p.get("username"): p for p in (r.json().get("profiles") or []) if isinstance(p, dict)}
    except Exception as e:
        print(f"channel check skipped: {e}")
        return {}
    bad = {}
    for a, user in C.UPLOAD_POST_USERS.items():
        yt = (profiles.get(user) or {}).get("social_accounts", {}).get("youtube")
        if not isinstance(yt, dict):
            continue
        blob = norm(json.dumps(yt))
        shown = {k: v for k, v in yt.items() if re.search(r"name|handle|title|user|channel", k, re.I)
                 and isinstance(v, (str, int))}
        print(f"ch{a} -> Upload-Post '{user}' -> YouTube {shown}")
        mine = any(norm(k) and norm(k) in blob for k in C.YT_IDENTITY.get(a, []))
        other = [b for b, keys in C.YT_IDENTITY.items() if b != a
                 and any(len(norm(k)) > 8 and norm(k) in blob for k in keys)]
        if other and not mine:
            bad[a] = other[0]
            print(f"⚠️ ch{a} profile '{user}' looks connected to channel {other[0]} - not posting there")
    return bad


def handle_bad(g, sheet, review, now):
    """👎 + a reason -> fix it right away; the new video comes back into the same row (⏳ until then)."""
    head, rows = panel(g, sheet)
    hx = {h: i for i, h in enumerate(head)}
    cell = lambda r, h: str(r[hx[h]]).strip() if h in hx and len(r) > hx[h] else ""
    by_id = {cell(r, "Clip ID"): r for r in rows}
    taken = {str(r[R_LIVE]).replace("swap:", "").strip() for r in review
             if not is_header(r) and str(r[R_LIVE]).startswith("swap:")}   # already coming in for another row
    changed = False
    for i, r in enumerate(review):
        if is_header(r):
            continue
        rn = i + C.REVIEW_HEADER_ROW + 1
        reason, status = bad_reason(r[R_BAD]), str(r[R_STATUS])
        clip_id, a = str(r[R_ID]).strip(), int(r[R_CH] or 0)
        if status.startswith("⏳") and str(r[R_LIVE]).startswith("swap:"):
            # still waiting: if Claude threw out the remake / the replacement, find another clip
            pend = str(r[R_LIVE]).replace("swap:", "").strip() or clip_id
            p = by_id.get(pend)
            if p is None or cell(p, "✅ YOUR DECISION") == "Reject":
                reason = reason or "Boring / not funny"
                status = ""                       # fall through to a (new) swap
            else:
                continue
        if not reason or status.startswith(("📅", "⏳ Remaking", "⏳ Swapping")):
            continue
        if not ticked(r[R_REDO]) and not status.startswith("⏳"):
            continue      # picked a reason but hasn't ticked 🔁 REDO yet
            continue
        swap = reason in C.BAD_SWAP or status == ""
        old_hook = str(r[R_HOOK]).strip()
        try:
            g.append_rows(sheet, f"'{C.FEEDBACK_TAB}'!A:F", [[now.strftime("%Y-%m-%d %H:%M"), clip_id, a,
                                                             str(r[R_STREAMER]), old_hook, reason]])
        except Exception:
            pass
        if str(r[R_FILE]).strip():
            try:
                g.trash(str(r[R_FILE]).strip())
            except Exception:
                pass
        if not swap:
            note = f"🤖 AUTO redo ch{a}: {reason}" + (f" | old: {old_hook}" if reason == "Hook is bad" else "")
            set_panel(g, sheet, head, rows, clip_id, {
                "🎯 TOP TEXT": "", "Hook 1": "", "Hook 2": "", "Hook 3": "", "Hook 4": "", "Hook 5": "",
                "🚀 SEND": False, "Status": "Waiting for Hook", "Edited Files": "", "Notes": note,
                "✅ YOUR DECISION": "Approve"})
            msg, pend = f"⏳ Remaking ({reason})…", clip_id
        else:
            if clip_id in by_id and cell(by_id[clip_id], "✅ YOUR DECISION") != "Reject":
                set_panel(g, sheet, head, rows, clip_id, {"✅ YOUR DECISION": "Reject",
                                                          "Notes": f"🤖 swapped out: {reason}"})
            cand = replacement(g, sheet, head, rows, cell, now, exclude={clip_id} | taken,
                               not_streamer=str(r[R_STREAMER]).strip().lower() if reason == "Duplicate clip" else "")
            if not cand:
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{rn}",
                                [["⚠️ No new clip to swap in yet - will retry every 30 min"]])
                continue
            set_panel(g, sheet, head, rows, cand, {"✅ YOUR DECISION": "Approve", "Status": "Waiting for Hook",
                                                   "Notes": f"🤖 AUTO swap {clip_id} ch{a}"})
            by_id.get(cand, [""] * len(head))
            taken.add(cand)
            msg, pend = f"⏳ Swapping in a new clip ({reason})…", cand
        g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{rn}:{L(R_LIVE)}{rn}", [[msg, f"swap:{pend}"]])
        print(f"👎 {clip_id} ch{a}: {reason} -> {'swap for ' + pend if swap else 'remake'}")
        changed = True
    if changed and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:   # the workflow starts the hook writer right away
            f.write("fix=yes\n")
    return changed


def replacement(g, sheet, head, rows, cell, now, exclude=(), not_streamer=""):
    """Best new clip from the last 24 h nobody has decided on yet (most views first)."""
    import re as _re
    nsfw = _re.compile(r"(?i)(🔞|18\+|nud|naked|strip|lap ?dance|boob|flash|goon|horny|gya+t)")
    best = None
    for r in rows:
        cid = cell(r, "Clip ID")
        if (not cid or cid in exclude or cell(r, "Status") != "New" or cell(r, "✅ YOUR DECISION")
                or cell(r, "Notes") or nsfw.search(cell(r, "Clip Title"))
                or (not_streamer and cell(r, "Streamer").lower() == not_streamer)):
            continue
        try:
            v = float(cell(r, "Views").replace(",", "") or 0)
        except ValueError:
            v = 0
        if best is None or v > best[0]:
            best = (v, cid)
    return best[1] if best else None


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
            (g.get_values(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW + 1}:O", formulas=True) or [])]


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
        if (not cid or cell(r, "Status") != "Ready to Post" or cid in on_review or cid in booked
                or cell(r, "✅ YOUR DECISION") == "Reject"):        # 👎 swapped-out clips never come back
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
    if C.DAILY_BATCH_HOUR is not None:
        # one shift a day: everything made since yesterday goes into ONE reel, built before your review time
        made_today = any(is_header(r) and str(r[R_BATCH]).startswith(now.strftime("%m%d-")) for r in review)
        rush = os.environ.get("FORCE_BATCH") == "yes" and not being_made(head, rows)
        if (now.hour < C.DAILY_BATCH_HOUR or made_today) and not rush:
            print(f"Batch: {len(loose)} video(s) waiting for the daily reel ({C.DAILY_BATCH_HOUR}:00 ET)")
            return False
    elif oldest < dt.timedelta(minutes=C.BATCH_MAX_WAIT_MIN) and (being_made(head, rows) or len(loose) < C.BATCH_MIN_CLIPS):
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
    header = [f"BATCH {bid}", "", f"🎬 {now:%a %b %-d} · {len(loose)} clips for the next 24h", watch, "", "",
              False, False, "", "",
              "👀 Watch the reel · 👎 bad ones · tick ✅ + ☑ on this row to POST ALL", "", reel_fid, bid,
              now.strftime("%Y-%m-%d %H:%M")]
    clips = []
    for n, i in enumerate(loose, 1):
        r = list(review[i])
        r[R_NAME] = f"#{n} · Ch{r[R_CH]} · {C.CHANNELS.get(int(r[R_CH]), '')}"
        r[R_POST], r[R_SURE], r[R_BAD], r[R_BATCH], r[R_STATUS] = False, False, bad_reason(r[R_BAD]), bid, "👀 In the reel above"
        r[R_REDO] = ticked(r[R_REDO])
        clips.append(r)
    delete_rows(g, sheet, loose)
    where = g.append_rows(sheet, f"'{C.REVIEW_TAB}'!A{C.REVIEW_HEADER_ROW}:O", [header] + clips)
    m = re.search(r"![A-Z]+(\d+):[A-Z]+(\d+)", where or "")
    if m:
        first, last = int(m.group(1)), int(m.group(2))
        gid = g.sheet_gid(sheet, C.REVIEW_TAB)
        from channels import review_boxes
        box = lambda r0, r1, c0, c1: {"setDataValidation": {
            "range": {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1},
            "rule": {"condition": {"type": "BOOLEAN"}}}}
        g.batch_update(sheet, [box(first - 1, first, R_POST, R_SURE + 1)]      # batch row: ✅ POST ALL + ☑ CONFIRM
                       + review_boxes(gid, first, last))                       # each clip: ✅ + ☑ + 👎 dropdown
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
                and not str(r[R_STATUS]).startswith(("📅", "⏳"))]
        if gone and alive:
            delete_rows(g, sheet, gone)
            print(f"Review: removed {len(gone)} expired video(s)")
            review = read_review(g, sheet)
    if backfill(g, sheet, review):
        review = read_review(g, sheet)
    if make_batch(g, sheet, review, now):
        review = read_review(g, sheet)

    try:
        if handle_bad(g, sheet, review, now):
            review = read_review(g, sheet)
    except Exception as e:
        print(f"👎 handling problem: {e}")

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
    try:   # 🧠 hours where our Shorts flop get skipped
        from learn import quiet_hours
        quiet = quiet_hours(g, sheet)
        if quiet:
            print(f"Learned quiet hours (skipped): {sorted(quiet)}")
    except Exception as e:
        print(f"learn: {e}"); quiet = set()

    def next_slot(a, after):
        """One post every POST_EVERY_HOURS per channel, channels staggered, and each slot nudged by a
        random few minutes (e.g. 9:23, 12:41, 3:07) so it doesn't look robotic. Never two channels within
        SLOT_MIN_APART_MIN minutes of each other."""
        import random
        step = C.POST_EVERY_HOURS * 60
        offset = (a - 1) * step // len(C.CHANNELS)
        base = after.replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1) \
            + dt.timedelta(minutes=offset)
        everyone = [t for ts in booked.values() for t in ts]
        while True:
            base += dt.timedelta(minutes=step)
            if any(abs(t - base) < dt.timedelta(minutes=step / 2) for t in booked[a]):
                continue                                     # this channel already has that slot
            j = random.Random(f"{a}-{base:%Y%m%d%H%M}").randint(-C.SLOT_JITTER_MIN, C.SLOT_JITTER_MIN)
            t = base + dt.timedelta(minutes=j)
            for _ in range(20):                              # keep clear of every other channel's posts
                if all(abs(t - o) >= dt.timedelta(minutes=C.SLOT_MIN_APART_MIN) for o in everyone):
                    break
                t += dt.timedelta(minutes=C.SLOT_MIN_APART_MIN)
            if t >= after and t.hour not in quiet:
                return t

    # 🚫 never the same video twice on one channel: by our clip ID and by the original Twitch/Kick clip
    clip_log = g.get_values(sheet, f"'{C.CLIP_LOG_TAB}'!A2:C") or []
    src_of = {str(x[0]).strip(): str(x[1]).strip().lower() for x in clip_log if len(x) > 1 and x[1]}
    link_of = {str(x[0]).strip(): str(x[2]).strip() for x in clip_log if len(x) > 2 and x[2]}
    on_channel = set()
    for p in g.get_values(sheet, f"'{C.POSTS_TAB}'!B2:D") or []:
        if len(p) > 2:
            cid = str(p[2]).strip()
            on_channel.add((cid, str(p[0]).strip()))
            if src_of.get(cid):
                on_channel.add((src_of[cid], str(p[0]).strip()))

    wrong = wrong_channels(key) if posting else {}

    head, rows = panel(g, sheet)
    drop = []
    with tempfile.TemporaryDirectory() as tmp:
        for hi, h in enumerate(review):
            if not is_header(h) or str(h[R_STATUS]).startswith("✅"):
                continue
            auto = (C.AUTO_POST_AFTER_HOURS and parse_et(h[R_ADDED]) and
                    now - parse_et(h[R_ADDED]) > dt.timedelta(hours=C.AUTO_POST_AFTER_HOURS))
            all_ = bool((ticked(h[R_POST]) and ticked(h[R_SURE])) or auto)
            bid0 = str(h[R_BATCH]).strip()
            singles = [r for r in review if not is_header(r) and str(r[R_BATCH]).strip() == bid0
                       and ticked(r[R_POST]) and ticked(r[R_SURE]) and not str(r[R_STATUS]).startswith("📅")]
            if not (all_ or singles):
                continue
            if not posting:
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{hi + C.REVIEW_HEADER_ROW + 1}",
                                [["⚠️ Posting isn't switched on yet"]])
                continue
            bid = str(h[R_BATCH]).strip()
            done = remade = failed = dupes = unconfirmed = 0
            for i, r in enumerate(review):
                if is_header(r) or str(r[R_BATCH]).strip() != bid or str(r[R_STATUS]).startswith(("📅", "🚫")):
                    continue
                clip_id, a, rn = str(r[R_ID]).strip(), int(r[R_CH]), i + C.REVIEW_HEADER_ROW + 1
                one = ticked(r[R_POST]) and ticked(r[R_SURE])
                if not all_ and not one:
                    continue          # only the ones you ticked (✅ + ☑) one by one
                if bad_reason(r[R_BAD]) and not ticked(r[R_REDO]) and not str(r[R_STATUS]).startswith("⏳"):
                    unconfirmed += 1  # 👎 picked but 🔁 not ticked yet: nothing happens to it
                    continue
                if bad_reason(r[R_BAD]) or str(r[R_STATUS]).startswith("⏳"):
                    remade += 1       # 👎 / being remade: never posts the old video
                    continue
                if not one and str(r[R_STATUS]).startswith("👀 New version"):
                    remade += 1       # a fixed video needs its own ✅ + ☑ (you haven't seen it yet)
                    continue
                if (clip_id, str(a)) in on_channel or (src_of.get(clip_id), str(a)) in on_channel:
                    g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{rn}:{L(R_LIVE)}{rn}",
                                    [[f"🚫 Already posted on Ch{a} - skipped", ""]])
                    print(f"{clip_id} ch{a}: already on that channel, skipped")
                    dupes += 1
                    continue
                if a in wrong:
                    g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{rn}",
                                    [[f"⚠️ Upload-Post Ch{a} is linked to the wrong YouTube channel - fix, then re-tick"]])
                    failed += 1
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
                title, desc, tags = title_and_tags(hook, str(r[R_STREAMER]).strip(), clip_id)
                try:
                    path = g.download(str(r[R_FILE]).strip(), os.path.join(tmp, f"{clip_id}_A{a}.mp4"))
                    with open(path, "rb") as f:
                        resp = requests.post(API, headers={"Authorization": f"Apikey {key}",
                                                           "Idempotency-Key": f"{clip_id}-A{a}-{r[R_FILE]}"},
                                             data={"user": user, "platform[]": "youtube",
                                                   "title": title, "description": desc, "tags": tags,
                                                   # upload now as private + YouTube's own schedule, so it shows
                                                   # in YouTube Studio as "Scheduled" right away and goes public at `slot`
                                                   "privacyStatus": "private",
                                                   "youtube_publish_at": slot.isoformat()},
                                             files={"video": (os.path.basename(path), f, "video/mp4")}, timeout=600)
                    os.remove(path)
                except Exception as e:
                    resp = None
                    err = str(e)[:100]
                if resp is None or resp.status_code >= 300:
                    msg = f"⚠️ {err if resp is None else f'Upload-Post said {resp.status_code}: {resp.text[:90]}'}"
                    g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{rn}", [[msg]])
                    print(f"{clip_id} ch{a}: {msg}"); failed += 1
                    continue
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                rid = body.get("request_id") or body.get("job_id") or ""
                g.append_rows(sheet, f"'{C.POSTS_TAB}'!A:N", [[
                    now.strftime("%Y-%m-%d %H:%M"), a, C.CHANNELS[a], clip_id, r[R_STREAMER],
                    (f'=HYPERLINK("{link_of[clip_id]}","original")' if clip_id in link_of else ""), hook,
                    slot.strftime("%Y-%m-%d %H:%M"), "", "", "", "", rid, ""]])
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{rn}:{L(R_LIVE)}{rn}",
                                [[f"📅 Scheduled {slot:%a %-I:%M %p}", slot.strftime("%Y-%m-%d %H:%M")]])
                set_panel(g, sheet, head, rows, clip_id, {"Status": "Scheduled"})
                on_channel.add((clip_id, str(a)))
                if src_of.get(clip_id):
                    on_channel.add((src_of[clip_id], str(a)))
                try:   # 🧾 Clip log: which channel + when
                    ids = [str(x[0]).strip() if x else "" for x in clip_log]
                    if clip_id in ids:
                        n = ids.index(clip_id) + 2
                        prev = (g.get_values(sheet, f"'{C.CLIP_LOG_TAB}'!F{n}") or [[""]])
                        prev = str(prev[0][0]).strip() if prev and prev[0] else ""
                        g.update_values(sheet, f"'{C.CLIP_LOG_TAB}'!F{n}",
                                        [[(prev + " · " if prev else "") + f"Ch{a} {slot:%m/%d %-I:%M %p}"]])
                except Exception as e:
                    print(f"clip log: {e}")
                booked[a].add(slot)
                clip_times.setdefault(clip_id, []).append(slot)
                done += 1
                print(f"{clip_id} -> channel {a} at {slot:%a %I:%M %p}")
            note = f"✅ {done} booked" + (f" · {remade} being remade (✅ + ☑ them when ready)" if remade else "") + \
                   (f" · ⚠️ {failed} failed (tick ✅ + ☑ again to retry)" if failed else "") + \
                   (f" · 🚫 {dupes} already on that channel" if dupes else "") + \
                   (f" · 👎 {unconfirmed} waiting for 🔁 REDO tick" if unconfirmed else "") + \
                   (" · auto-posted" if auto and not ticked(h[R_POST]) else "")
            if failed:
                note = note.replace("✅", "⏳", 1)
                g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_POST)}{hi + C.REVIEW_HEADER_ROW + 1}:{L(R_SURE)}{hi + C.REVIEW_HEADER_ROW + 1}", [[False, False]])
            if (remade or unconfirmed) and all_:
                note = note.replace("✅", "⏳", 1)
            if not all_:   # only some clips posted one by one: the batch stays open for the rest
                note = f"👀 {done} posted one by one · ✅ + ☑ the rest, or ✅ + ☑ here to POST ALL"
            g.update_values(sheet, f"'{C.REVIEW_TAB}'!{L(R_STATUS)}{hi + C.REVIEW_HEADER_ROW + 1}", [[note]])
    delete_rows(g, sheet, drop)

    # ---- tidy: once EVERY clip in a batch is booked (or remade), the batch leaves Review right away,
    #      ready for the next one (📒 Posts keeps the full record). Anything not posted stays. ----
    review = read_review(g, sheet)
    old = []
    for hi, h in enumerate(review):
        if not is_header(h):
            continue
        bid = str(h[R_BATCH]).strip()
        mine = [i for i, r in enumerate(review) if not is_header(r) and str(r[R_BATCH]).strip() == bid]
        if all(str(review[i][R_STATUS]).startswith(("📅", "🚫")) for i in mine):   # all booked (or none left)
            old += [hi] + mine
            if str(h[R_FILE]).strip():
                try:
                    g.trash(str(h[R_FILE]).strip())
                except Exception:
                    pass
            print(f"Batch {bid}: all posted - cleared from Review")
    delete_rows(g, sheet, old)

    # ---- keep each batch organised: grouped by channel, then by the time it goes live ----
    review = read_review(g, sheet)
    gid = g.sheet_gid(sheet, C.REVIEW_TAB)
    sorts = []
    for hi, h in enumerate(review):
        if not is_header(h):
            continue
        bid = str(h[R_BATCH]).strip()
        mine = [i for i, r in enumerate(review) if not is_header(r) and str(r[R_BATCH]).strip() == bid]
        if len(mine) > 1 and mine == list(range(mine[0], mine[-1] + 1)):
            sorts.append({"sortRange": {
                "range": {"sheetId": gid, "startRowIndex": C.REVIEW_HEADER_ROW + mine[0],
                          "endRowIndex": C.REVIEW_HEADER_ROW + mine[-1] + 1, "startColumnIndex": 0,
                          "endColumnIndex": NCOL},
                "sortSpecs": [{"dimensionIndex": R_CH, "sortOrder": "ASCENDING"},
                              {"dimensionIndex": R_LIVE, "sortOrder": "ASCENDING"}]}})
    if sorts:
        g.batch_update(sheet, sorts)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
