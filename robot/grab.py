"""Hourly: pull the best new GTA 6 clips, save raw MP4s to Drive '1 - New Clips'/<date>/, log rows in the Control Panel.

Raw = exactly what Twitch/Kick serve: no captions, no watermark added.
"""
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
import traceback
from zoneinfo import ZoneInfo

import config as C
from google_api import Google
from sources import Twitch, kick_clips, slug_from_link

ET = ZoneInfo("America/New_York")


def col_a1(i):  # 0-based -> A1 letters
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def trim_formula(cut):
    """✂️ Trim link that keeps working when rows are sorted (reads its own row with ROW())."""
    idc = "INDEX($A:$A,ROW())"
    cc = f"INDEX(${cut}:${cut},ROW())"
    return (f'=IF({idc}="","",HYPERLINK(\'Account Styles\'!L1&"&id="&{idc},'
            f'IF({cc}="","✂️ Trim","✂️ "&{cc})))')


def clip_key(url):
    """Same clip, any URL style -> one key (twitch.tv/x/clip/ID, clips.twitch.tv/ID, kick ?clip=ID)."""
    m = re.search(r"(?:/clip/|clips\.twitch\.tv/|[?&]clip=|/clips/)([-\w]+)", url or "")
    return m.group(1).lower() if m else (url or "").lower()


# clip titles that almost always mean nudity / sexual content -> never grabbed (Claude also checks the video itself)
NSFW_TITLE = re.compile(r"(?i)(🔞|\b18\+|nud(e|ity)|naked|nsfw|strip ?club|stripper|lap ?dance|boob|booba|titt|"
                        r"\bflash(ed|ing)?\b|topless|thong|onlyfans|\bporn|\bsex|goon(er|ing)?|horny|\bthirst|"
                        r"twerk|\bass\b|\bbutt\b|gya+t+|\bstrip\b)")


def is_gta(c, gta_ids):
    if c["platform"] == "Twitch":
        return c.get("game_id") in gta_ids
    return any(n.lower() in str(c.get("game_id", "")).lower() for n in C.GAME_NAMES)


def safe(text):
    """Stop titles like '=)' or '+1' from being treated as formulas."""
    text = str(text or "").replace("\n", " ").strip()
    return "'" + text if text[:1] in "=+-@" else text


def cleanup(g, now_et):
    now = dt.datetime.now(dt.timezone.utc)

    def age_days(f):
        t = max(f.get("createdTime", ""), f.get("modifiedTime", ""))
        return (now - dt.datetime.fromisoformat(t.replace("Z", "+00:00"))).total_seconds() / 86400 if t else 0

    def sweep(folder_id, days, recurse=False):
        n = 0
        for f in g.list_children(folder_id):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                if recurse:
                    n += sweep(f["id"], days, recurse)
                    if not g.list_children(f["id"]) and age_days(f) > 1:
                        g.delete(f["id"])  # empty date folder
                continue
            if f["name"].lower().endswith(".mp4") and age_days(f) > days:
                g.delete(f["id"]); n += 1
        return n

    # robot videos already in the Drive trash (delete button, replaced versions): delete for good
    robot_name = re.compile(r"^\d{4}-.+-\d{3}(_A\d|_TT\d)?(_raw)?\.mp4$")
    n = 0
    for f in g.list_trashed_videos():
        if robot_name.match(f["name"]):
            g.delete(f["id"]); n += 1

    d = C.CLEANUP_DAYS
    n += sweep(C.FOLDERS["rejected"][0], d["rejected"])
    n += sweep(C.FOLDERS["new"][0], d["new"], recurse=True)
    n += sweep(C.FOLDERS["approved"][0], d["approved"])
    n += sweep(C.FOLDERS["hold"][0], d["hold"])
    for fid in list(C.ACCOUNT_FOLDERS.values()) + list(C.TIKTOK_FOLDERS.values()):
        n += sweep(fid, d["ready"])
    return n


AUTO_TAG = "🤖 AUTO"


def auto_pick(g, sheet, now_et):
    """Every 6 hours (12am, 6am, 12pm, 6pm ET) the robot approves the most-viewed undecided clips grabbed in
    the last 6 hours, up to AUTO_PICKS_PER_WINDOW. Claude then screens each one (skips duds) and writes the
    5 channel hooks; skipped ones get replaced on the next grab."""
    hours = C.AUTO_WINDOW_HOURS
    start = now_et.replace(hour=now_et.hour - now_et.hour % hours, minute=0, second=0, microsecond=0)
    tag = f"{AUTO_TAG} {start:%m/%d %-I%p}"
    head = [str(h).strip() for h in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]]
    need = {"id": "Clip ID", "dec": "✅ YOUR DECISION", "notes": "Notes", "views": "Views",
            "grabbed": "Grabbed (ET)", "status": "Status", "top": "🎯 TOP TEXT",
            "streamer": "Streamer", "title": "Clip Title"}
    if any(v not in head for v in need.values()):
        return 0
    try:   # 🧠 streamers whose Shorts do better get picked more
        from learn import streamer_boost
        boost = streamer_boost(g, sheet)
    except Exception as e:
        print(f"learn: {e}"); boost = {}
    ci = {k: head.index(v) for k, v in need.items()}
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:Z", formulas=True)
    cell = lambda r, k: str(r[ci[k]]).strip() if len(r) > ci[k] else ""
    taken = sum(1 for r in rows if cell(r, "notes").startswith(tag) and cell(r, "dec") != "Reject")
    want = C.AUTO_PICKS_PER_WINDOW - taken
    if want <= 0:
        return 0
    since = now_et - dt.timedelta(hours=hours)

    def grabbed_at(v):
        try:   # the sheet keeps dates as day numbers since 1899-12-30
            return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(v))).replace(tzinfo=ET)
        except ValueError:
            try:
                return dt.datetime.strptime(v[:16], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
            except ValueError:
                return None

    def views(r):
        try:
            return float(str(cell(r, "views")).replace(",", ""))
        except ValueError:
            return 0

    cands = []
    for i, r in enumerate(rows):
        if not cell(r, "id") or cell(r, "dec") or cell(r, "notes") or cell(r, "top") or cell(r, "status") != "New":
            continue
        if NSFW_TITLE.search(cell(r, "title")):
            continue
        t = grabbed_at(cell(r, "grabbed"))
        if t and t >= since:
            cands.append((views(r) * boost.get(cell(r, "streamer").lower(), 1.0), i))
    picks = [i for _, i in sorted(cands, reverse=True)[:want]]
    for i in picks:
        rn = C.HEADER_ROWS + 1 + i
        for k, v in (("dec", "Approve"), ("status", "Waiting for Hook"), ("notes", tag)):
            g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_a1(ci[k])}{rn}", [[v]])
    return len(picks)


def cleanup_rows(g, sheet, now_et):
    """Same ages as the Drive clean-up: rejected 1 day, never decided 3 days, everything else 7 days.
    Age comes from the clip ID (MMDD-...)."""
    head = [str(h).strip() for h in (g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}") or [[]])[0]]
    if "Clip ID" not in head or "✅ YOUR DECISION" not in head:
        return 0
    ci, di = head.index("Clip ID"), head.index("✅ YOUR DECISION")
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:Z")
    today = now_et.date()
    old = []
    for i, r in enumerate(rows):
        cid = str(r[ci]).strip() if len(r) > ci else ""
        m = re.match(r"^(\d\d)(\d\d)-", cid)
        if not m:
            continue
        try:
            d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if d > today:
            d = d.replace(year=today.year - 1)   # December clip seen in January
        age = (today - d).days
        dec = str(r[di]).strip() if len(r) > di else ""
        limit = C.CLEANUP_DAYS["rejected"] if dec == "Reject" else 7 if dec == "Approve" else C.CLEANUP_DAYS["new"]
        if age > limit:
            old.append(i)
    if not old:
        return 0
    gid = g.sheet_gid(sheet, C.PANEL_TAB)
    g.batch_update(sheet, [{"deleteDimension": {"range": {
        "sheetId": gid, "dimension": "ROWS", "startIndex": C.HEADER_ROWS + i, "endIndex": C.HEADER_ROWS + i + 1}}}
        for i in sorted(old, reverse=True)])
    return len(old)


def clean_mp4(path):
    """Re-wrap a downloaded clip as a plain MP4 (timestamps from 0, no extra data tracks, fast-start),
    so Google Drive can play it in the trimmer and the editor never chokes on it. Never re-encodes."""
    import shutil
    if not shutil.which("ffmpeg"):
        return False
    out = path + ".clean.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0?",
                        "-c", "copy", "-dn", "-sn", "-avoid_negative_ts", "make_zero", "-reset_timestamps", "1",
                        "-movflags", "+faststart", out], capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 10000:
        print(f"   (clean-up skipped: {r.stderr[-150:]})")
        return False
    os.replace(out, path)
    return True


def fix_raw_files(g):
    """Clean every raw clip already in the sheet (same Drive file, same links)."""
    sheet = os.environ["SHEET_ID"]
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z", formulas=True)
    head = [str(h).strip() for h in rows[0]]
    ri, si, ii = head.index("Raw File"), head.index("Status"), head.index("Clip ID")
    done = 0
    with tempfile.TemporaryDirectory() as tmp:
        for r in rows[1:]:
            raw = str(r[ri]) if len(r) > ri else ""
            m = re.search(r"/d/([-\w]+)", raw)
            st = str(r[si]) if len(r) > si else ""
            if not m or st == "Ready to Post":
                continue
            p = os.path.join(tmp, "raw.mp4")
            try:
                g.download(m.group(1), p)
                if clean_mp4(p):
                    g.update_media(m.group(1), p)
                    done += 1
                    print(f"fixed {r[ii]}")
            except Exception as e:
                print(f"{r[ii]}: {e}")
    print(f"FIX RAW: cleaned {done} clip(s)")


def purge_ids(g, ids):
    """Delete every video (raw + 6 versions) belonging to these clip IDs."""
    n = 0
    for cid in [x.strip() for x in ids.split(",") if x.strip()]:
        safe_id = cid.replace("'", "")
        r = g._req("GET", "https://www.googleapis.com/drive/v3/files", params={
            "q": f"name contains '{safe_id}' and trashed = false and mimeType = 'video/mp4'",
            "fields": "files(id,name)", "pageSize": 50})
        for f in r.json().get("files", []):
            if f["name"].startswith(safe_id):
                g.delete(f["id"]); n += 1
    print(f"PURGE IDS: deleted {n} video(s)")


def purge_all(g):
    """One-off reset: delete every robot-made clip video in the clip folders (and empty date folders)."""
    robot_name = re.compile(r"^\d{4}-.+-\d{3}(_A\d|_TT\d)?(_raw)?\.mp4$")
    n = 0

    def walk(fid):
        nonlocal n
        for f in g.list_children(fid):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                walk(f["id"])
                if re.match(r"^\d{4}-\d\d-\d\d$", f["name"]) and not g.list_children(f["id"]):
                    g.delete(f["id"])
            elif robot_name.match(f["name"]):
                g.delete(f["id"]); n += 1

    for fid, _ in C.FOLDERS.values():
        if fid != C.FOLDERS["brand"][0]:
            walk(fid)
    for fid in list(C.ACCOUNT_FOLDERS.values()) + list(C.TIKTOK_FOLDERS.values()):
        walk(fid)  # channel folders (YouTube + TikTok), in case any sit outside the folders above
    for f in g.list_trashed_videos():
        if robot_name.match(f["name"]):
            g.delete(f["id"]); n += 1
    print(f"PURGE: deleted {n} clip video(s)")


def main():
    sheet = os.environ.get("SHEET_ID") or C.SHEET_ID_FALLBACK
    g = Google()
    now_et = dt.datetime.now(ET)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=C.LOOKBACK_HOURS)
    errors, grabbed = [], 0

    # --- Drive housekeeping: clear names, remove the empty duplicate ---
    try:
        g.rename(*C.ROOT_FOLDER)
        for fid, name in C.FOLDERS.values():
            g.rename(fid, name)
        for t, fid in C.TIKTOK_FOLDERS.items():  # TikTok account folders (fixed IDs, names kept in order)
            g.rename(fid, f"{t} - {C.TIKTOK_CHANNELS[t]}")
        for a, fid in C.ACCOUNT_FOLDERS.items():  # channel folders inside "4 - Ready to Post"
            g.rename(fid, f"{a} - {C.CHANNELS[a]}".replace("|", "-") if a in C.CHANNELS else f"{a} - (not used)")
        for dup in C.DUPLICATE_ROOTS:
            if g.trash_if_no_files(dup):
                print(f"Trashed empty duplicate folder {dup}")
    except Exception as e:
        errors.append(f"folder tidy: {e}")

    # --- what's already logged (dedupe by any clip link anywhere in the row) ---
    panel = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:S", formulas=True)
    known = set()
    for row in panel:
        for cell in row:
            for u in re.findall(r'https?://(?:www\.|clips\.)?(?:twitch\.tv|kick\.com)[^"\s]*', str(cell)):
                known.add(clip_key(u))
    moments = []   # (streamer, when the clip was made): two clips of the same moment = a duplicate

    def when(v):
        try:
            return dt.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            return None

    # 🧾 Clip log: every clip ever grabbed (rows there are never cleaned up) -> never grab it again
    try:
        log = g.get_values(sheet, f"'{C.CLIP_LOG_TAB}'!A2:C") or []
        if not log:   # first run: start the log from what's on the Control Panel now
            seed = []
            for row in panel:
                cid = str(row[0]).strip() if row else ""
                u = re.findall(r'https?://(?:www\.|clips\.)?(?:twitch\.tv|kick\.com)[^"\s]*', " ".join(map(str, row)))
                if cid and u:
                    seed.append([cid, clip_key(u[0]), u[0], "", ""])
            if seed:
                g.append_rows(sheet, f"'{C.CLIP_LOG_TAB}'!A:E", seed)
                log = seed
        for row in g.get_values(sheet, f"'{C.CLIP_LOG_TAB}'!D2:G") or []:
            if len(row) > 3 and row[3]:
                t = when(row[3])
                if t:
                    moments.append((re.sub(r"[^a-z0-9]", "", str(row[0]).lower()), t))
        for row in log:
            if len(row) > 1 and row[1]:
                known.add(str(row[1]).strip().lower())
            if row:
                panel.append([row[0]])   # logged IDs still count, so numbers never repeat
    except Exception as e:
        print(f"clip log: {e}")
    try:  # clips deleted with the 🗑 button are remembered here so they never come back
        for row in g.get_values(sheet, "'Deleted Clips'!A2:B"):
            if len(row) > 1 and row[1]:
                known.add(clip_key(str(row[1])))
            if row:
                panel.append([row[0]])  # deleted IDs still count, so numbers never repeat
    except Exception:
        pass  # tab only exists after the first delete
    today_prefix = now_et.strftime("%m%d")
    # next number = highest number used today + 1 (never reuses an ID, even if rows get deleted)
    nums = [int(m.group(1)) for row in panel if row
            for m in [re.match(rf"{today_prefix}-.*-(\d+)$", str(row[0]).strip())] if m]
    today_count = max(nums, default=0)

    # --- Drive: new clips go into "1 - New Clips/<date>" ---
    raw_root = C.FOLDERS["new"][0]
    day_folder = g.ensure_folder(raw_root, now_et.strftime("%Y-%m-%d"))

    # --- tracked streamers from the Streamers + Links tab ---
    streamers = g.get_values(sheet, f"'{C.STREAMERS_TAB}'!A2:J")
    tw_logins, kick_slugs = set(), set()
    tier_of = {}  # streamer login / name (lowercase, no spaces) -> 1, 2, 3 (T1 = biggest)

    def norm(x):
        return re.sub(r"[^a-z0-9]", "", str(x or "").lower())

    for row in streamers:
        cells = " ".join(str(c) for c in row)
        t = re.match(r"\s*T?(\d)", str(row[0])) if row else None
        tier = int(t.group(1)) if t else 3
        if len(row) > 1 and row[1]:
            tier_of[norm(row[1])] = tier
        for link in re.findall(r"https?://\S+", cells):
            if "twitch.tv/" in link:
                lg = slug_from_link(link, "twitch.tv"); tw_logins.add(lg); tier_of[norm(lg)] = tier
            elif "kick.com/" in link:
                sl = slug_from_link(link, "kick.com"); kick_slugs.add(sl); tier_of[norm(sl)] = tier
    tw_logins.discard(None); kick_slugs.discard(None)

    # --- collect candidates ---
    cands = []
    tw = Twitch()
    test_game = (os.environ.get("TEST_GAME") or "").strip()
    test_kick = (os.environ.get("TEST_KICK") or "").strip().lower() in ("yes", "true", "1")
    test = bool(test_game) or test_kick
    max_new = int(os.environ.get("TEST_MAX") or 5) if test else C.MAX_NEW_CLIPS_PER_RUN
    if test_kick:
        print(f"TEST MODE: Kick clips from the Streamers tab ({len(kick_slugs)} channels), any game, up to {max_new}")
        tw_logins = set()
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    elif test:
        print(f"TEST MODE: category '{test_game}', up to {max_new} clips")
        tw_logins, kick_slugs = set(), set()   # category only, keeps the test clean
    gta = [] if test_kick else tw.game_ids([test_game] if test else C.GAME_NAMES)
    if not gta and not test_kick:
        errors.append(f"category not found: {test_game or C.GAME_NAMES}")
    for gid in gta:
        cands += [dict(c, min=(100 if test else C.MIN_VIEWS_CATEGORY)) for c in tw.clips(since, game_id=gid, first=100, pages=C.CATEGORY_PAGES)]
    for login, uid in tw.user_ids(sorted(tw_logins)).items():
        try:
            cands += [dict(c, min=C.MIN_VIEWS_TRACKED, tracked=True) for c in tw.clips(since, broadcaster_id=uid, first=20)]
        except Exception as e:
            errors.append(f"Twitch {login}: {e}")
    for slug in sorted(kick_slugs):
        clips, err = kick_clips(slug, since, period=("week" if test_kick else "day"))
        if err:
            errors.append(err)
        cands += [dict(c, min=(0 if test_kick else C.MIN_VIEWS_TRACKED), tracked=not test_kick) for c in clips]

    # --- filter, dedupe, best first ---
    seen, picks = set(), []
    why = {"not GTA 6": 0, "already have": 0, "too few views": 0, "wrong length": 0, "not English": 0}
    def rank(c):
        """Top streamers first (T1 like Kai Cenat / xQc, then T2, T3, then everyone else),
        most views first inside each group; clips over 25 s need ~40% more views."""
        tier = tier_of.get(norm(c["streamer"]), 9)
        score = c["views"] * (1.0 if c["seconds"] <= C.PREFERRED_SECONDS else 0.7)
        return (tier, -score)

    for c in sorted(cands, key=rank):
        if c.get("tracked") and not is_gta(c, gta):
            why["not GTA 6"] += 1; continue
        if (C.ONLY_TIERS and not test and tier_of.get(norm(c["streamer"])) not in C.ONLY_TIERS
                and c["views"] < (getattr(C, "POPULAR_ANY_VIEWS", None) or 10 ** 9)):
            why["not T1/T2"] = why.get("not T1/T2", 0) + 1; continue
        if clip_key(c["url"]) in known or clip_key(c["url"]) in seen:
            why["already have"] += 1; continue
        if c["views"] < c["min"]:
            why["too few views"] += 1; continue
        if not (C.MIN_SECONDS <= c["seconds"] <= C.MAX_SECONDS):
            why["wrong length"] += 1; continue
        if c["platform"] == "Twitch" and c["language"] and c["language"].split("-")[0] not in C.LANGUAGES:
            why["not English"] += 1; continue
        if NSFW_TITLE.search(c.get("title") or ""):
            why["nsfw title"] = why.get("nsfw title", 0) + 1; continue
        made = when(c.get("created"))
        if made and any(st == norm(c["streamer"]) and abs((made - t).total_seconds()) < C.SAME_MOMENT_SECONDS
                        for st, t in moments):
            why["same moment"] = why.get("same moment", 0) + 1; continue   # another clipper's copy
        if made:
            moments.append((norm(c["streamer"]), made))
        seen.add(clip_key(c["url"])); picks.append(c)
        if len(picks) >= max_new:
            break

    print(f"Found {len(cands)} candidate clips; skipped {why}")
    for c in [c for c in sorted(cands, key=lambda c: c["views"], reverse=True) if c["language"][:2] == "en"][:8]:
        print(f"   {c['views']:>6} views  {c['seconds']:>3}s  lang={c['language']!r}  {c['streamer']}  {c['url']}")

    header = (g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}") or [[]])[0]
    header = [str(h).strip() for h in header]

    def hcol(name):
        return header.index(name)

    # --- download + upload + log (each row is written as soon as its video is in Drive) ---
    ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")
    last = max([i for i, r in enumerate(ids) if r and str(r[0]).strip()], default=-1)
    next_row = C.HEADER_ROWS + 1 + last + 1
    if picks:
        g.ensure_rows(sheet, C.PANEL_TAB, next_row + len(picks) + 50)
    with tempfile.TemporaryDirectory() as tmp:
        for c in picks:
            today_count += 1
            slug = re.sub(r"[^a-z0-9]", "", c["streamer"].lower()) or "clip"
            clip_id = f"{today_prefix}-{slug}-{today_count:03d}"
            path = os.path.join(tmp, clip_id + ".mp4")
            try:
                subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "mp4/best",
                                "-o", path, c["url"]],
                               check=True, timeout=300, capture_output=True, text=True)
                clean_mp4(path)
                fid = g.upload(path, clip_id + ".mp4", day_folder)
            except subprocess.CalledProcessError as e:
                errors.append(f"{clip_id}: download failed: {(e.stderr or '')[-200:]}"); continue
            except Exception as e:
                errors.append(f"{clip_id}: {e}"); continue
            drive_link = f'=HYPERLINK("https://drive.google.com/file/d/{fid}/view","📄 raw")'
            watch = f'=HYPERLINK("{c["url"]}","▶ watch")'
            # A ID | B Streamer | C Title | D Watch | E Score | F Verdict | G Decision | H By | I Status
            # J Views | K Length | L Platform | M Grabbed | N Raw File | O Edited | P-R Hook 1-3 | S Notes
            # build the row by column NAME, so moving/adding columns in the sheet never breaks this
            vals = {"Clip ID": clip_id, "Streamer": safe(c["streamer"]), "Clip Title": safe(c["title"]),
                    "▶ Watch": watch, "Status": "New", "Views": c["views"], "Length (s)": c["seconds"],
                    "Platform": c["platform"], "Grabbed (ET)": now_et.strftime("%Y-%m-%d %H:%M"),
                    "Raw File": drive_link, "Notes": "🧪 TEST clip (not GTA 6)" if test else "",
                    "Tier": f"T{min(tier_of.get(norm(c['streamer']), 4), 4)}"}
            row = [vals.get(h, "") for h in header]
            if "✂️ TRIM" in header and "✂️ CUT" in header:  # ✂️ Trim link -> trim page (web app URL in Account Styles!L1)
                cut = col_a1(hcol("✂️ CUT"))
                row[hcol("✂️ TRIM")] = trim_formula(cut)
            try:
                ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")  # re-check: rows may have moved
                last = max([i for i, r in enumerate(ids) if r and str(r[0]).strip()], default=-1)
                next_row = C.HEADER_ROWS + 1 + last + 1
                row = [x.replace("{r}", str(next_row)) if isinstance(x, str) else x for x in row]
                g.update_values(sheet, f"'{C.PANEL_TAB}'!A{next_row}", [row])
                grabbed += 1
                try:
                    g.append_rows(sheet, f"'{C.CLIP_LOG_TAB}'!A:G", [[clip_id, clip_key(c["url"]), c["url"],
                                                                     safe(c["streamer"]),
                                                                     now_et.strftime("%Y-%m-%d %H:%M"), "",
                                                                     "'" + str(c.get("created") or "")]])
                except Exception as e:
                    print(f"clip log: {e}")
                try:  # Approve/Reject dropdown only on rows that have a clip
                    gid = g.sheet_gid(sheet, C.PANEL_TAB)
                    g.batch_update(sheet, [{"setDataValidation": {
                        "range": {"sheetId": gid, "startRowIndex": next_row - 1, "endRowIndex": next_row,
                                  "startColumnIndex": hcol("✅ YOUR DECISION"), "endColumnIndex": hcol("✅ YOUR DECISION") + 1},
                        "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                            {"userEnteredValue": v} for v in ("Approve", "Reject")]},
                            "showCustomUi": True, "strict": True}}},
                        {"setDataValidation": {
                        "range": {"sheetId": gid, "startRowIndex": next_row - 1, "endRowIndex": next_row,
                                  "startColumnIndex": hcol("🚀 SEND"), "endColumnIndex": hcol("🚀 SEND") + 1},
                        "rule": {"condition": {"type": "BOOLEAN"}}}}])
                except Exception as e:
                    errors.append(f"{clip_id}: dropdown: {e}")
            except Exception as e:
                errors.append(f"{clip_id}: saved to Drive but sheet write failed: {e}")

    # --- keep the list sorted: T1 first, then T2, T3, others; most views first inside each tier ---
    if grabbed and "Tier" in header and "Views" in header:
        try:
            ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")
            last = max([i for i, r in enumerate(ids) if r and str(r[0]).strip()], default=-1)
            if last > 0:
                gid = g.sheet_gid(sheet, C.PANEL_TAB)
                g.batch_update(sheet, [{"sortRange": {
                    "range": {"sheetId": gid, "startRowIndex": C.HEADER_ROWS, "endRowIndex": C.HEADER_ROWS + last + 1,
                              "startColumnIndex": 0, "endColumnIndex": len(header)},
                    "sortSpecs": [{"dimensionIndex": hcol("Tier"), "sortOrder": "ASCENDING"},
                                  {"dimensionIndex": hcol("Views"), "sortOrder": "DESCENDING"}]}}])
        except Exception as e:
            errors.append(f"sort: {e}")

    # --- Drive clean-up: delete old robot files so the free 15 GB never fills up ---
    try:
        removed = cleanup(g, now_et) if C.CLEANUP_ENABLED else 0
        if removed:
            print(f"Clean-up: deleted {removed} old file(s)")
    except Exception as e:
        errors.append(f"clean-up: {e}")

    # --- Auto-pick: the 10 most-viewed new clips of each 6-hour window go straight to Claude + editing ---
    if getattr(C, "AUTO_PICK", False) and not test:
        try:
            n = auto_pick(g, sheet, now_et)
            if n:
                print(f"Auto-pick: approved {n} clip(s) for Claude to screen")
                if os.environ.get("GITHUB_OUTPUT"):
                    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                        f.write(f"auto_picked={n}\n")
        except Exception as e:
            errors.append(f"auto-pick: {e}")

    # --- Sheet clean-up: drop rows whose videos the clean-up has removed, so the sheet stays fast forever ---
    try:
        n = cleanup_rows(g, sheet, now_et)
        if n:
            print(f"Clean-up: removed {n} old row(s) from the sheet")
    except Exception as e:
        errors.append(f"row clean-up: {e}")

    # --- Drive space meter (Control Panel J1:M1) ---
    try:
        used, limit = g.storage()
        u, l = used / 1e9, (limit / 1e9 if limit else 0)
        pct = u / l if l else 0
        color = "#e53935" if pct > 0.85 else "#fb8c00" if pct > 0.6 else "#43a047"
        g.update_values(sheet, f"'{C.PANEL_TAB}'!M1:N1", [[
            f"💾 Drive: {u:.1f} of {l:.0f} GB ({pct:.0%})" if l else f"💾 Drive: {u:.1f} GB used",
            f'=SPARKLINE({pct:.4f},{{"charttype","bar";"max",1;"color1","{color}"}})']])
        if pct > 0.85:
            errors.insert(0, f"DRIVE {pct:.0%} FULL")
    except Exception as e:
        errors.append(f"storage check: {e}")

    # --- health line (Control Panel G1, one cell) ---
    status = "✅ OK" if not errors else f"⚠ {len(errors)} issue(s): " + " | ".join(errors[:3])
    line = (f"🤖 Robot · {now_et.strftime('%a %I:%M %p').replace(' 0', ' ')} · "
            f"{'🧪 TEST ' if test else ''}grabbed {grabbed} · {status}")
    g.update_values(sheet, f"'{C.PANEL_TAB}'!G1", [[line[:400]]])
    print(f"Grabbed {grabbed} clip(s). {status}")


REQUIRED = ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "SHEET_ID"]

if __name__ == "__main__":
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        print("Setup not finished yet, skipping this run. Missing secrets: " + ", ".join(missing))
        sys.exit(0)
    try:
        if os.environ.get("FIX_RAW", "").strip().lower() in ("yes", "true", "1"):
            fix_raw_files(Google())
        elif os.environ.get("PURGE_IDS", "").strip():
            purge_ids(Google(), os.environ["PURGE_IDS"])
            sys.exit(0)
        if os.environ.get("PURGE_ALL", "").strip().lower() == "yes":
            purge_all(Google())
            sys.exit(0)
        main()
    except Exception as e:
        traceback.print_exc()
        try:
            g = Google()
            now = dt.datetime.now(ET).strftime("%a %I:%M %p")
            g.update_values(os.environ.get("SHEET_ID"), f"'{C.PANEL_TAB}'!G1",
                            [[f"🤖 Robot · ❌ FAILED {now} · {str(e)[:300]}"]])
        except Exception:
            pass
        sys.exit(1)
