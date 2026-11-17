"""Hourly: pull the best new GTA 6 clips, save raw MP4s to Drive 01_Raw/<date>/, log rows in the Control Panel.

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
from google_api import Google, folder_ids_from_panel
from sources import Twitch, kick_clips, slug_from_link

ET = ZoneInfo("America/New_York")


def main():
    sheet = os.environ.get("SHEET_ID") or C.SHEET_ID_FALLBACK
    g = Google()
    now_et = dt.datetime.now(ET)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=C.LOOKBACK_HOURS)
    errors, grabbed = [], 0

    # --- what's already logged (dedupe by clip link, column H) ---
    panel = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:H", formulas=True)
    known = set()
    for row in panel:
        if len(row) > 7:
            m = re.search(r'https?://[^"\s]+', str(row[7]))
            if m:
                known.add(m.group(0))
    today_prefix = now_et.strftime("%m%d")
    today_count = sum(1 for row in panel if row and str(row[0]).startswith(today_prefix))

    # --- Drive folders (written into row 2 by the sheet add-on) ---
    row2 = g.get_values(sheet, f"'{C.PANEL_TAB}'!D2:M2", formulas=True)
    folders = folder_ids_from_panel(row2[0] if row2 else [])
    raw_root = folders.get("01 Raw")
    if not raw_root:
        raise RuntimeError("Drive folders not found. Run 🎬 Clip Hub > First-time setup in the sheet first.")
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
    gta = tw.game_ids(C.GAME_NAMES)
    for gid in gta:
        cands += [dict(c, min=C.MIN_VIEWS_CATEGORY) for c in tw.clips(since, game_id=gid, first=100)]
    for login, uid in tw.user_ids(sorted(tw_logins)).items():
        try:
            cands += [dict(c, min=C.MIN_VIEWS_TRACKED) for c in tw.clips(since, broadcaster_id=uid, first=20)]
        except Exception as e:
            errors.append(f"Twitch {login}: {e}")
    for slug in sorted(kick_slugs):
        clips, err = kick_clips(slug, since)
        if err:
            errors.append(err)
        cands += [dict(c, min=C.MIN_VIEWS_TRACKED) for c in clips]

    # --- filter, dedupe, best first ---
    seen, picks = set(), []
    for c in sorted(cands, key=lambda c: c["views"], reverse=True):
        if c["url"] in known or c["url"] in seen:
            continue
        if c["views"] < c["min"] or not (C.MIN_SECONDS <= c["seconds"] <= C.MAX_SECONDS):
            continue
        if c["platform"] == "Twitch" and c["language"] and c["language"].split("-")[0] not in C.LANGUAGES:
            continue
        seen.add(c["url"]); picks.append(c)
        if len(picks) >= C.MAX_NEW_CLIPS_PER_RUN:
            break

    # --- download + upload + log ---
    rows = []
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
            drive_link = f'=HYPERLINK("https://drive.google.com/file/d/{fid}/view","▶ raw file")'
            watch = f'=HYPERLINK("{c["url"]}","▶ watch")'
            rows.append([clip_id, now_et.strftime("%Y-%m-%d %H:%M"), c["streamer"], c["platform"],
                         c["title"], c["views"], c["seconds"], watch, drive_link] + [""] * 17 + ["Raw"])
            grabbed += 1

    if rows:
        # write directly under the last filled Clip ID (checkbox columns make "append" jump to the bottom)
        ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")
        last = max([i for i, r in enumerate(ids) if r and str(r[0]).strip()], default=-1)
        start = C.HEADER_ROWS + 1 + last + 1
        g.update_values(sheet, f"'{C.PANEL_TAB}'!A{start}", rows)

    # --- health line (Control Panel O1:T1) ---
    status = "OK" if not errors else f"{len(errors)} issue(s): " + " | ".join(errors[:3])
    g.update_values(sheet, f"'{C.PANEL_TAB}'!O1:R1", [[
        "🤖 ROBOT", now_et.strftime("Last run %a %I:%M %p"), f"Grabbed {grabbed}", status[:400]]])
    print(f"Grabbed {grabbed} clip(s). {status}")


REQUIRED = ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "SHEET_ID"]

if __name__ == "__main__":
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        print("Setup not finished yet, skipping this run. Missing secrets: " + ", ".join(missing))
        sys.exit(0)
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
