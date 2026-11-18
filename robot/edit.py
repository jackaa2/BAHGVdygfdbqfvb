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
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import config as C
from google_api import Google
from render import FONTS_DIR, render
from speaker import keep_streamer
from styles import HOOK_COLORS, HOOK_FOR

ET = ZoneInfo("America/New_York")
PREVIEWS = os.environ.get("PREVIEW_DIR")
if PREVIEWS:
    os.makedirs(PREVIEWS, exist_ok=True)
NEEDED = {"id": "Clip ID", "decision": "✅ YOUR DECISION", "status": "Status", "raw": "Raw File",
          "edited": "Edited Files", "notes": "Notes", "h1": "Hook 1", "h2": "Hook 2", "h3": "Hook 3",
          "streamer": "Streamer", "platform": "Platform", "title": "Clip Title", "top": "🎯 TOP TEXT", "send": "🚀 SEND"}
OPTIONAL = {"cut": "✂️ CUT"}


def col_letter(i):  # 0-based -> A1 letter
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def static_caption(hook, title):
    """Text shown above the clip: the hook if one was written, otherwise the clip's own title."""
    t = (hook or "").strip().lstrip("'")   # the hook picked in 🎯 TOP TEXT; never the raw Twitch title
    if t.lower() == "(no top text)":
        return ""
    t = re.sub(r"\s+", " ", t)
    if len(re.sub(r"[^A-Za-z]", "", t)) < 3:   # junk titles like "???" or "10k" -> no static caption
        return ""
    return t[:70]


def parse_time(t):
    """'0:05', '1:02', '5', '5.5', '5s' -> seconds; '' or junk -> None"""
    t = str(t or "").strip().lower().rstrip("s").lstrip("'")
    if not t:
        return None
    try:
        if ":" in t:
            m, sec = t.split(":", 1)
            return int(m) * 60 + float(sec)
        return float(t)
    except ValueError:
        return None


def best_window(words, dur, length):
    """Start time of the `length`-second stretch with the most talking (clips are cut to 25 s)."""
    if dur <= length:
        return 0.0
    best, best_n, t = 0.0, -1, 0.0
    while t + length <= dur + 0.01:
        n = sum(1 for w in words if w["start"] >= t and w["end"] <= t + length)
        if n > best_n:
            best, best_n = t, n
        t += 0.5
    # start a little before the first word so it doesn't cut in mid-sentence
    first = [w["start"] for w in words if w["start"] >= best]
    if first and first[0] - best > 0.6:
        best = min(first[0] - 0.3, dur - length)
    return max(best, 0.0)


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
                return TTFont(dst)["name"].getDebugName(1) or "Titan One"
    except Exception as e:
        print(f"brand font skipped: {e}")
    return "Titan One"


_model = None


def transcribe(path):
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel(C.WHISPER_MODEL, device="cpu", compute_type="int8")
    # decode with ffmpeg ourselves (avoids PyAV version issues): 16 kHz mono float32
    import numpy as np
    res = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True)
    if res.returncode != 0:      # no audio track -> no captions
        return []
    pcm = res.stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    if audio.size < 16000:
        return []
    segs, _ = _model.transcribe(audio, word_timestamps=True, vad_filter=True, language="en",
                                condition_on_previous_text=False)
    seglist = []
    for sg in segs:
        ws = [{"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
              for w in (sg.words or []) if w.word.strip()]
        if ws:
            seglist.append({"start": float(sg.start), "end": float(sg.end), "text": sg.text.strip(), "words": ws,
                            "no_speech_prob": float(sg.no_speech_prob), "avg_logprob": float(sg.avg_logprob)})
    if C.STREAMER_ONLY_CAPTIONS:
        seglist = keep_streamer(audio, seglist)
    return [w for sg in seglist for w in sg["words"]]


def main():
    sheet = os.environ["SHEET_ID"]
    g = Google()
    head = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]
    col = {k: head.index(v) for k, v in {**NEEDED, **OPTIONAL}.items() if v in head}
    missing = [NEEDED[k] for k in NEEDED if k not in col]
    if missing:
        raise RuntimeError(f"Control Panel is missing column(s): {', '.join(missing)}")
    last = col_letter(len(head) - 1)
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:{last}", formulas=True)

    def cell(r, k):
        return str(r[col[k]]).strip() if k in col and len(r) > col[k] else ""

    def put(rownum, k, value, clip_id=None):
        # rows can move while we work (e.g. the delete-rejected button), so find the clip's row again
        if clip_id:
            ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")
            hits = [C.HEADER_ROWS + 1 + i for i, r in enumerate(ids) if r and str(r[0]).strip() == clip_id]
            if not hits:
                print(f"{clip_id}: row is gone, skipping sheet update"); return
            rownum = hits[0]
        g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col[k])}{rownum}", [[value]])

    sample = (os.environ.get("SAMPLE_ID") or "").strip()
    if sample:
        return make_sample(g, sheet, rows, cell, sample)

    todo = []
    for i, r in enumerate(rows):
        if (cell(r, "id") and cell(r, "decision") == "Approve" and cell(r, "status") != "Ready to Post"
                and cell(r, "top") and not cell(r, "top").startswith("⚠️ Claude") and cell(r, "send").upper() == "TRUE"):  # only after 🚀 SEND is ticked
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
            put(rownum, "status", "Pending", clip_id)
            try:
                fid = file_id(cell(r, "raw"))
                if not fid:
                    raise RuntimeError("no raw file link")
                src = g.download(fid, os.path.join(tmp, clip_id + "_raw.mp4"))
                print(f"   {clip_id} raw: {describe(src)}")
                words = transcribe(src)
                from render import probe
                dur = probe(src)[2]
                parts = re.split(r"\s*[-–]\s*", cell(r, "cut").lstrip("'")) if cell(r, "cut") else []
                cut_a, cut_b = (parse_time(parts[0]), parse_time(parts[1])) if len(parts) == 2 else (None, None)
                manual = cut_a is not None or cut_b is not None
                if manual:  # your ✂️ START / END from the sheet
                    a0 = max(0.0, min(cut_a or 0.0, max(dur - 1, 0)))
                    b0 = min(cut_b if cut_b is not None else dur, dur)
                    if b0 <= a0 + 0.5:
                        raise RuntimeError(f"✂️ CUT ({cell(r, 'cut')}): end must be after start")
                    window, clip_len = a0, min(b0 - a0, C.MAX_CLIP_SECONDS)
                else:
                    window, clip_len = best_window(words, dur, C.MAX_CLIP_SECONDS), C.MAX_CLIP_SECONDS
                hooks = {1: cell(r, "h1"), 2: cell(r, "h2"), 3: cell(r, "h3")}
                made = 0

                # YouTube A1-A5 + TikTok T1-T5 (TikTok N = YouTube N, only the watermark differs)
                from render import WM_DIR
                jobs = [(a, f"A{a}", C.ACCOUNT_FOLDERS[a], f"{clip_id}_A{a}.mp4") for a in sorted(C.CHANNELS)]
                jobs += [(t, f"T{t}", C.TIKTOK_FOLDERS[t], f"{clip_id}_TT{t}.mp4") for t in sorted(C.TIKTOK_FOLDERS)
                         if os.path.exists(os.path.join(WM_DIR, f"T{t}.png"))]

                def one(job):
                    a, wm_name, folder, name = job
                    st_ = accts[a]
                    out = os.path.join(tmp, name)
                    render(src, out, a, words, static_caption(cell(r, "top"), "") if C.SHOW_HOOK else "", "#FFFFFF",
                           hook_font, st_["handle"] if C.SHOW_WATERMARK else "", st_["spot"], st_["zoom"],
                           window if manual else min(window + st_["trim"], max(dur - 3, 0)), tmp,
                           platform=cell(r, "platform") or "Twitch", streamer=cell(r, "streamer"),
                           max_len=clip_len, wm_name=wm_name)
                    if PREVIEWS:
                        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "3", "-i", out, "-frames:v", "1",
                                        "-vf", "scale=360:640", os.path.join(PREVIEWS, name.replace(".mp4", ".jpg"))])
                    return folder, name, out

                with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2)) as pool:
                    for folder, name, out in pool.map(one, jobs):
                        old = g.find_child(folder, name, folder=False)
                        if old:
                            g.trash(old)  # re-edit replaces the older version (old one goes to Drive trash)
                        g.upload(out, name, folder)
                        os.remove(out)
                        made += 1
                if PREVIEWS and os.environ.get("PREVIEW_UPLOAD") == "yes":
                    try:
                        sheet_img = os.path.join(PREVIEWS, f"{clip_id}_preview.jpg")
                        ins = sum([["-i", os.path.join(PREVIEWS, f"{clip_id}_A{a}.jpg")] for a in range(1, 7)], [])
                        subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", "hstack=6",
                                        sheet_img], check=True)
                        pv = g.ensure_folder(C.ROOT_FOLDER[0], "_previews (test)")
                        g.upload(sheet_img, f"{clip_id}_preview.jpg", pv, mime="image/jpeg")
                    except Exception as e:
                        print(f"preview upload failed: {e}")
                put(rownum, "edited", '=HYPERLINK("https://drive.google.com/drive/folders/'
                    f'{C.FOLDERS["ready"][0]}","✅ {made} versions")', clip_id)
                put(rownum, "status", "Ready to Post", clip_id)
                try:
                    g.touch(fid)  # raw is kept 1 more day from now, then the clean-up deletes it
                except Exception as e:
                    print(f"{clip_id}: could not mark raw: {e}")
                if C.DELETE_RAW_AFTER_EDIT and made == len(jobs):
                    try:
                        g.delete(fid)  # all 6 versions are safely in the account folders
                        put(rownum, "raw", "🗑 used (versions made)", clip_id)
                    except Exception as e:
                        print(f"{clip_id}: could not delete raw: {e}")
                print(f"{clip_id}: {made} versions, {len(words)} caption words")
            except Exception as e:
                traceback.print_exc()
                msg = e.stderr[-300:] if isinstance(e, subprocess.CalledProcessError) else str(e)
                tries = re.findall(r"Edit failed \(try (\d+)\)", cell(r, "notes"))
                n = int(tries[-1]) + 1 if tries else 1
                put(rownum, "status", "Pending", clip_id)
                put(rownum, "notes", clip_id=clip_id, value=f"⚠ Edit failed (try {n}) {dt.datetime.now(ET):%a %I:%M %p}: {msg[:250]}")


def describe(path):
    """One line about the raw video (helps when a clip misbehaves)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,start_time,duration,nb_frames,time_base:format=start_time,duration,size",
                        "-of", "compact=p=0:nk=0", path], capture_output=True, text=True)
    return " || ".join(r.stdout.split("\n")).strip()


def make_sample(g, sheet, rows, cell, clip_id):
    """TEST: one YouTube channel-1 version of a clip, saved as a GitHub artifact.
    Touches nothing in the sheet or the channel folders."""
    r = next((r for r in rows if cell(r, "id") == clip_id), None)
    if not r:
        raise RuntimeError(f"sample: clip {clip_id} not in the sheet")
    out_dir = os.environ.get("SAMPLE_DIR") or "."
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = g.download(file_id(cell(r, "raw")), os.path.join(tmp, "raw.mp4"))
        print("   raw:", describe(src))
        words = transcribe(src)
        from render import probe
        dur = probe(src)[2]
        top = cell(r, "top")
        if not top or top.startswith("⚠️ Claude"):
            top = cell(r, "h1") or "Sample hook 🔔"
        hook_font = brand_font(g, tmp)
        st_ = account_settings(g, sheet)[1]
        out = os.path.join(out_dir, f"SAMPLE_{clip_id}.mp4")
        render(src, out, 1, words, static_caption(top, ""), "#FFFFFF", hook_font, "", st_["spot"], st_["zoom"],
               best_window(words, dur, C.MAX_CLIP_SECONDS), tmp, platform=cell(r, "platform") or "Twitch",
               streamer=cell(r, "streamer"), max_len=C.MAX_CLIP_SECONDS, wm_name="A1")
        pv = g.ensure_folder(C.ROOT_FOLDER[0], "_previews (test)")
        old = g.find_child(pv, os.path.basename(out), folder=False)
        if old:
            g.trash(old)
        fid = g.upload(out, os.path.basename(out), pv)
        print(f"sample made: https://drive.google.com/file/d/{fid}/view")


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
