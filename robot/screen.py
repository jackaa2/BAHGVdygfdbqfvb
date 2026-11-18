"""Claude hook writer: for every new clip without hooks, Claude looks at 4 frames + reads what's said and
writes 3 hooks (Hook 1-3). The 🎯 TOP TEXT cell gets a dropdown of those 3 (+ "(no top text)");
you pick one before you can approve."""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback

import requests

import config as C
from google_api import Google

API = "https://api.anthropic.com/v1/messages"
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]   # fast + cheap first, fallback second
MAX_PER_RUN = 25

PROMPT = """You screen clips for a faceless GTA 6 streamer-clips channel (TikTok, YouTube Shorts, Reels, X).
The best posts are funny, shocking or hype streamer moments, ideally about GTA 6, that hook in the first second.

Clip info:
- Streamer: {streamer} ({platform})
- Clip title: {title}
- Views so far: {views}
- Length: {seconds}s
- What's said (auto transcript, may be messy): {transcript}

The images are 4 frames from the clip, in order.

Reply with ONLY this JSON, nothing else:
{{"hooks": ["<hook 1>", "<hook 2>", "<hook 3>"]}}

Hook rules: 3 different on-screen top lines for the post, each max 45 characters, punchy, curiosity or
reaction style (e.g. "Kai was NOT ready for this", "Speed broke the game in 5 seconds"), use the streamer's
name when it helps, no emojis, no hashtags, no quotes, nothing false about what happens in the clip.
Make the 3 hooks different angles (reaction, curiosity, bold claim). Keep them clean: nothing hateful or sexual."""


def frames(path, tmp, n=4):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=nw=1:nk=1", path], capture_output=True, text=True).stdout or 0)
    out = []
    for i in range(n):
        t = max(dur * (i + 0.5) / n, 0)
        f = os.path.join(tmp, f"f{i}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                        "-vf", "scale=512:-2", "-q:v", "5", f], capture_output=True)
        if os.path.exists(f):
            out.append(base64.b64encode(open(f, "rb").read()).decode())
    return out


def transcript(path):
    try:
        from faster_whisper import WhisperModel
        import numpy as np
        global _wm
        if "_wm" not in globals():
            _wm = WhisperModel("base.en", device="cpu", compute_type="int8")
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f",
                              "f32le", "-"], capture_output=True)
        if pcm.returncode != 0:
            return "(no audio)"
        audio = np.frombuffer(pcm.stdout, dtype=np.float32)
        segs, _ = _wm.transcribe(audio, vad_filter=True, language="en")
        text = " ".join(s.text.strip() for s in segs)
        return text[:1500] or "(no speech)"
    except Exception as e:
        return f"(transcript unavailable: {e})"


def ask_claude(key, prompt, imgs):
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
               for b in imgs] + [{"type": "text", "text": prompt}]
    last = None
    for model in MODELS:
        r = requests.post(API, timeout=120, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 400, "messages": [{"role": "user", "content": content}]})
        if r.status_code == 200:
            text = "".join(b.get("text", "") for b in r.json().get("content", []))
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0))
        last = f"{model}: {r.status_code} {r.text[:200]}"
        if r.status_code in (401, 403):
            break  # bad key: no point trying another model
    raise RuntimeError(last)


def col_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("No ANTHROPIC_API_KEY, screener skipped"); return
    sheet = os.environ["SHEET_ID"]
    g = Google()
    head = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]
    need = {"id": "Clip ID", "streamer": "Streamer", "title": "Clip Title", "top": "🎯 TOP TEXT",
            "views": "Views",
            "secs": "Length (s)", "platform": "Platform", "raw": "Raw File",
            "h1": "Hook 1", "h2": "Hook 2", "h3": "Hook 3"}
    col = {k: head.index(v) for k, v in need.items() if v in head}
    missing = [need[k] for k in need if k not in col]
    if missing:
        raise RuntimeError(f"missing columns: {missing}")
    rows = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:{col_letter(len(head) - 1)}", formulas=True)

    def cell(r, k):
        return str(r[col[k]]).strip() if len(r) > col[k] else ""

    todo = [r for r in rows if cell(r, "id") and not (cell(r, "h1") or cell(r, "h2") or cell(r, "h3"))][:MAX_PER_RUN]
    gid = g.sheet_gid(sheet, C.PANEL_TAB)
    print(f"{len(todo)} clip(s) to screen")
    done = 0
    with tempfile.TemporaryDirectory() as tmp:
        for r in todo:
            clip_id = cell(r, "id")
            try:
                m = re.search(r"(?:/d/|id=)([-\w]{20,})", cell(r, "raw"))
                if not m:
                    continue
                path = g.download(m.group(1), os.path.join(tmp, "clip.mp4"))
                imgs = frames(path, tmp)
                prompt = PROMPT.format(streamer=cell(r, "streamer"), platform=cell(r, "platform"),
                                       title=cell(r, "title").lstrip("'"), views=cell(r, "views"),
                                       seconds=cell(r, "secs"), transcript=transcript(path))
                res = ask_claude(key, prompt, imgs)
                hooks = [re.sub(r'["#]', "", str(h)).strip()[:60] for h in (res.get("hooks") or [])][:3]
                hooks = [h for h in hooks if h]
                if not hooks:
                    raise RuntimeError("Claude returned no hooks")
                # find the row again right before writing (rows can move)
                ids = g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A")
                hit = [C.HEADER_ROWS + 1 + i for i, x in enumerate(ids) if x and str(x[0]).strip() == clip_id]
                if not hit:
                    continue
                rn = hit[0]
                g.update_values(sheet, f"'{C.PANEL_TAB}'!{col_letter(col['h1'])}{rn}:"
                                       f"{col_letter(col['h3'])}{rn}", [hooks + [""] * (3 - len(hooks))])
                # dropdown in 🎯 TOP TEXT with these hooks (typing your own text is allowed too)
                g.batch_update(sheet, [{"setDataValidation": {
                    "range": {"sheetId": gid, "startRowIndex": rn - 1, "endRowIndex": rn,
                              "startColumnIndex": col["top"], "endColumnIndex": col["top"] + 1},
                    "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                        {"userEnteredValue": h} for h in hooks + ["(no top text)"]]},
                        "showCustomUi": True, "strict": False}}}])
                print(f"{clip_id}: {hooks}")
                done += 1
                os.remove(path)
            except Exception as e:
                traceback.print_exc()
                print(f"{clip_id}: screening failed: {e}")
    print(f"Wrote hooks for {done} clip(s)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
