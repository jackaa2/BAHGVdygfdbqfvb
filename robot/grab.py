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


def clip_key(url):
    """Same clip, any URL style -> one key (twitch.tv/x/clip/ID, clips.twitch.tv/ID, kick ?clip=ID)."""
    m = re.search(r"(?:/clip/|clips\.twitch\.tv/|[?&]clip=|/clips/)([-\w]+)", url or "")
    return m.group(1).lower() if m else (url or "").lower()


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
    robot_name = re.compile(r"^\d{4}-.+-\d{3}(_A\d)?(_raw)?\.mp4$")
    n = 0
    for f in g.list_trashed_videos():
        if robot_name.match(f["name"]):
            g.delete(f["id"]); n += 1

    d = C.CLEANUP_DAYS
    n += sweep(C.FOLDERS["rejected"][0], d["rejected"])
    n += sweep(C.FOLDERS["new"][0], d["new"], recurse=True)
    n += sweep(C.FOLDERS["approved"][0], d["approved"])
    n += sweep(C.FOLDERS["hold"][0], d["hold"])
    for fid in C.ACCOUNT_FOLDERS.values():
        n += sweep(fid, d["ready"])
    return n


def purge_all(g):
    """One-off reset: delete every robot-made clip video in the clip folders (and empty date folders)."""
    robot_name = re.compile(r"^\d{4}-.+-\d{3}(_A\d)?(_raw)?\.mp4$")
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
    for row in streamers:
        cells = " ".join(str(c) for c in row)
        for link in re.findall(r"https?://\S+", cells):
            if "twitch.tv/" in link:
                tw_logins.add(slug_from_link(link, "twitch.tv"))
            elif "kick.com/" in link:
                kick_slugs.add(slug_from_link(link, "kick.com"))
    tw_logins.discard(None); kick_slugs.discard(None)

    # --- collect candidates ---
    cands = []
    tw = Twitch()
    test_game = (os.environ.get("TEST_GAME") or "").strip()
    test = bool(test_game)
    max_new = int(os.environ.get("TEST_MAX") or 5) if test else C.MAX_NEW_CLIPS_PER_RUN
    if test:
        print(f"TEST MODE: category '{test_game}', up to {max_new} clips")
        tw_logins, kick_slugs = set(), set()   # category only, keeps the test clean
    gta = tw.game_ids([test_game] if test else C.GAME_NAMES)
    if not gta:
        errors.append(f"category not found: {test_game or C.GAME_NAMES}")
    for gid in gta:
        cands += [dict(c, min=(100 if test else C.MIN_VIEWS_CATEGORY)) for c in tw.clips(since, game_id=gid, first=100, pages=C.CATEGORY_PAGES)]
    for login, uid in tw.user_ids(sorted(tw_logins)).items():
        try:
            cands += [dict(c, min=C.MIN_VIEWS_TRACKED, tracked=True) for c in tw.clips(since, broadcaster_id=uid, first=20)]
        except Exception as e:
            errors.append(f"Twitch {login}: {e}")
    for slug in sorted(kick_slugs):
        clips, err = kick_clips(slug, since)
        if err:
            errors.append(err)
        cands += [dict(c, min=C.MIN_VIEWS_TRACKED, tracked=True) for c in clips]

    # --- filter, dedupe, best first ---
    seen, picks = set(), []
    why = {"not GTA 6": 0, "already have": 0, "too few views": 0, "wrong length": 0, "not English": 0}
    def rank(c):  # most views first; streamers on our list get a boost; prefer clips <= 25 s
        boost = C.TRACKED_BOOST if c.get("tracked") else 1.0
        return c["views"] * boost * (1.0 if c["seconds"] <= C.PREFERRED_SECONDS else 0.7)

    for c in sorted(cands, key=rank, reverse=True):
        if c.get("tracked") and not is_gta(c, gta):
            why["not GTA 6"] += 1; continue
        if clip_key(c["url"]) in known or clip_key(c["url"]) in seen:
            why["already have"] += 1; continue
        if c["views"] < c["min"]:
            why["too few views"] += 1; continue
        if not (C.MIN_SECONDS <= c["seconds"] <= C.MAX_SECONDS):
            why["wrong length"] += 1; continue
        if c["platform"] == "Twitch" and c["language"] and c["language"].split("-")[0] not in C.LANGUAGES:
            why["not English"] += 1; continue
        seen.add(clip_key(c["url"])); picks.append(c)
        if len(picks) >= max_new:
            break

    print(f"Found {len(cands)} candidate clips; skipped {why}")
    for c in [c for c in sorted(cands, key=lambda c: c["views"], reverse=True) if c["language"][:2] == "en"][:8]:
        print(f"   {c['views']:>6} views  {c['seconds']:>3}s  lang={c['language']!r}  {c['streamer']}  {c['url']}")

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
                fid = g.upload(path, clip_id + ".mp4", day_folder)
            except subprocess.CalledProcessError as e:
                errors.append(f"{clip_id}: download failed: {(e.stderr or '')[-200:]}"); continue
            except Exception as e:
                errors.append(f"{clip_id}: {e}"); continue
            drive_link = f'=HYPERLINK("https://drive.google.com/file/d/{fid}/view","📄 raw")'
            watch = f'=HYPERLINK("{c["url"]}","▶ watch")'
            # A ID | B Streamer | C Title | D Watch | E Score | F Verdict | G Decision | H By | I Status
            # J Views | K Length | L Platform | M Grabbed | N Raw File | O Edited | P-R Hook 1-3 | S Notes
            row = ([clip_id, safe(c["streamer"]), safe(c["title"]), watch, "", "", "", "", "New",
                    c["views"], c["seconds"], c["platform"], now_et.strftime("%Y-%m-%d %H:%M"),
                    drive_link, ""] + [""] * 3 + (["🧪 TEST clip (not GTA 6)"] if test else [""]))
            try:
                ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")  # re-check: rows may have moved
                last = max([i for i, r in enumerate(ids) if r and str(r[0]).strip()], default=-1)
                next_row = C.HEADER_ROWS + 1 + last + 1
                g.update_values(sheet, f"'{C.PANEL_TAB}'!A{next_row}", [row])
                grabbed += 1
            except Exception as e:
                errors.append(f"{clip_id}: saved to Drive but sheet write failed: {e}")

    # --- Drive clean-up: delete old robot files so the free 15 GB never fills up ---
    try:
        removed = cleanup(g, now_et) if C.CLEANUP_ENABLED else 0
        if removed:
            print(f"Clean-up: deleted {removed} old file(s)")
    except Exception as e:
        errors.append(f"clean-up: {e}")

    # --- Drive space meter (Control Panel J1:M1) ---
    try:
        used, limit = g.storage()
        u, l = used / 1e9, (limit / 1e9 if limit else 0)
        pct = u / l if l else 0
        color = "#e53935" if pct > 0.85 else "#fb8c00" if pct > 0.6 else "#43a047"
        g.update_values(sheet, f"'{C.PANEL_TAB}'!K1:L1", [[
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
