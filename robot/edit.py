"""Every 10 min: take clips marked Approve, make 6 channel versions (captions + hook + watermark),
save each into "4 - Ready to Post/Account N", then mark the clip Ready to Post.

Status: New -> Pending (approved) -> Ready to Post. Failures stay Pending with the reason in Notes (3 tries).
"""
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from zoneinfo import ZoneInfo

import config as C
from google_api import Google
from render import FONTS_DIR, render
from styles import HOOK_COLORS, HOOK_FOR

ET = ZoneInfo("America/New_York")
NEEDED = {"id": "Clip ID", "decision": "✅ YOUR DECISION", "status": "Status", "raw": "Raw File",
          "edited": "Edited Files", "notes": "Notes", "h1": "Hook 1", "h2": "Hook 2", "h3": "Hook 3"}


def col_letter(i):  # 0-based -> A1 letter
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def file_id(cell):
    m = re.search(r"(?:/d/|id=)([-\w]{20,})", str(cell))
    return m.group(1) if m else None


def account_settings(g, sheet):
    rows = g.get_values(sheet, f"'{C.STYLES_TAB}'!A2:I7")
    out = {}
    for i in range(1, 7):
        r = (rows[i - 1] if i - 1 < len(rows) else []) + [""] * 9
        handle = r[1].strip()
        zoom = re.findall(r"[\d.]+", r[3])
        trim = re.findall(r"[\d.]+", r[8])
        out[i] = dict(
            handle=handle if handle.startswith("@") else (f"@{handle}" if handle else ""),
            spot=r[2] or "Top-left",
            zoom=max(1.0, min(float(zoom[0]) / 100, 1.3)) if zoom else 1.0,
            hook_color=HOOK_COLORS.get(r[4].strip().lower(), "#FFFFFF"),
            trim=min(float(trim[0]), 2.0) if trim else 0.0,
        )
    return out


def brand_font(g, workdir):
    """Use a .ttf/.otf from Drive '0 - Brand Kit' for hooks, if one is there."""
    try:
        from fontTools.ttLib import TTFont
        for f in g.list_children(C.FOLDERS["brand"][0]):
            if f["name"].lower().endswith((".ttf", ".otf")):
                dst = os.path.join(FONTS_DIR, re.sub(r"[^\w.]", "_", f["name"]))
                g.download(f["id"], dst)
                return TTFont(dst)["name"].getDebugName(1) or "Anton"
    except Exception as e:
        print(f"brand font skipped: {e}")
    return "Anton"


_model = None


def transcribe(path):
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel(C.WHISPER_MODEL, device="cpu", compute_type="int8")
    # decode with ffmpeg ourselves (avoids PyAV version issues): 16 kHz mono float32
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    if audio.size < 16000:
        return []
    segs, _ = _model.transcribe(audio, word_timestamps=True, vad_filter=True, language="en")
    words = []
    for s in segs:
        for w in (s.words or []):
            t = w.word.strip()
            if t:
                words.append({"word": t, "start": float(w.start), "end": float(w.end)})
    return words


def main():
    sheet = os.environ["SHEET_ID"]
    g = Google()
    head = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]
    col = {k: head.index(v) for k, v in NEEDED.items() if v in head}
    missing = [NEEDED[k] for k in NEEDED if k not in col]
    if missing:
        raise RuntimeError(f"Control Panel is missing column(s): {', '.join(missing)}")
    last = col_letter(len(head) - 1)
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:{last}", formulas=True)

    def cell(r, k):
        return str(r[col[k]]).strip() if len(r) > col[k] else ""

    def put(rownum, k, value):
        g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col[k])}{rownum}", [[value]])

    todo = []
    for i, r in enumerate(rows):
        if cell(r, "id") and cell(r, "decision") == "Approve" and cell(r, "status") != "Ready to Post":
            tries = re.findall(r"Edit failed \(try (\d+)\)", cell(r, "notes"))
            if tries and int(tries[-1]) >= 3:
                continue  # gave up after 3 tries; re-pick Approve after fixing to retry
            todo.append((C.HEADER_ROWS + 1 + i, r))
    todo = todo[:C.EDIT_MAX_PER_RUN]
    print(f"{len(todo)} approved clip(s) to edit")
    if not todo:
        return

    accts = account_settings(g, sheet)
    with tempfile.TemporaryDirectory() as tmp:
        hook_font = brand_font(g, tmp)
        for rownum, r in todo:
            clip_id = cell(r, "id")
            put(rownum, "status", "Pending")
            try:
                fid = file_id(cell(r, "raw"))
                if not fid:
                    raise RuntimeError("no raw file link")
                src = g.download(fid, os.path.join(tmp, clip_id + "_raw.mp4"))
                words = transcribe(src)
                hooks = {1: cell(r, "h1"), 2: cell(r, "h2"), 3: cell(r, "h3")}
                made = 0
                for a in range(1, 7):
                    s = accts[a]
                    out = os.path.join(tmp, f"{clip_id}_A{a}.mp4")
                    render(src, out, a, words, hooks[HOOK_FOR[a]], s["hook_color"], hook_font,
                           s["handle"], s["spot"], s["zoom"], s["trim"], tmp)
                    # replace an older version with the same name (re-edits)
                    old = g.find_child(C.ACCOUNT_FOLDERS[a], f"{clip_id}_A{a}.mp4", folder=False)
                    if old:
                        g.trash(old)
                    g.upload(out, f"{clip_id}_A{a}.mp4", C.ACCOUNT_FOLDERS[a])
                    os.remove(out)
                    made += 1
                put(rownum, "edited", '=HYPERLINK("https://drive.google.com/drive/folders/'
                    f'{C.FOLDERS["ready"][0]}","✅ 6 versions")')
                put(rownum, "status", "Ready to Post")
                print(f"{clip_id}: {made} versions, {len(words)} caption words")
            except Exception as e:
                traceback.print_exc()
                msg = e.stderr[-300:] if isinstance(e, subprocess.CalledProcessError) else str(e)
                tries = re.findall(r"Edit failed \(try (\d+)\)", cell(r, "notes"))
                n = int(tries[-1]) + 1 if tries else 1
                put(rownum, "status", "Pending")
                put(rownum, "notes", f"⚠ Edit failed (try {n}) {dt.datetime.now(ET):%a %I:%M %p}: {msg[:250]}")


REQUIRED = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "SHEET_ID"]

if __name__ == "__main__":
    miss = [k for k in REQUIRED if not os.environ.get(k)]
    if miss:
        print("Missing secrets, skipping: " + ", ".join(miss))
        sys.exit(0)
    if not shutil.which("ffmpeg"):
        print("ffmpeg missing"); sys.exit(1)
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
