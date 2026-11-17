"""Turn one raw clip into a vertical 1080x1920 channel version: blurred background, clip in the middle,
hook on top, word-by-word captions, small watermark. All done with ffmpeg + an .ass subtitle file."""
import os
import re
import subprocess

from styles import CAPTION_STYLES, PICTURE

W, H = 1080, 1920
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def ass_color(hex_rgb, alpha=0):
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


EMOJI = re.compile("[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F\u200D]")


def ass_text(s):
    s = EMOJI.sub("", str(s or "")).strip()
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def fmt_t(t):
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def chunk_words(words, n):
    """Group words into on-screen lines of n words; break early on long pauses or punctuation."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 0
        if len(cur) >= n or gap > 0.6 or re.search(r"[.!?]$", w["word"]):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words, acct, hook, hook_color, hook_font, handle, spot, duration, video_box):
    """video_box = (top_y, bottom_y) of the clip on the 1080x1920 canvas."""
    st = CAPTION_STYLES[acct]
    top, bottom = video_box
    border_style = 3 if st["box"] else 1
    back = ass_color("#000000", 0x40) if st["box"] else ass_color("#000000", 0x60)
    outline_col = ass_color("#000000", 0x50) if st["box"] else ass_color(st["outline"])
    hook_size = 104 if len(hook or "") < 28 else 88 if len(hook or "") < 50 else 74
    hook_y = max(top - 50, 260)

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{st['font']},{st['size']},{ass_color(st['text'])},{ass_color(st['active'])},"
        f"{outline_col},{back},0,0,0,0,100,100,1,{st['tilt']},{border_style},{st['border']},{st['shadow']},"
        f"5,70,70,0,1",
        f"Style: Hook,{hook_font},{hook_size},{ass_color(hook_color)},{ass_color(hook_color)},"
        f"{ass_color('#000000')},{ass_color('#000000', 0x70)},0,0,0,0,100,100,1,0,1,8,4,2,80,80,0,1",
        f"Style: Mark,Anton,40,{ass_color('#FFFFFF', 0x70)},{ass_color('#FFFFFF')},"
        f"{ass_color('#000000', 0xA0)},{ass_color('#000000', 0xFF)},0,0,0,0,100,100,1,0,1,2,0,7,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    end_all = fmt_t(duration + 1)

    # hook (whole clip), bottom-aligned just above the video
    if hook:
        lines.append(f"Dialogue: 2,0:00:00.00,{end_all},Hook,,0,0,0,,{{\\pos({W // 2},{hook_y})}}"
                     f"{{\\fad(150,0)}}{ass_text(hook)}")

    # watermark (whole clip), inside the video area
    if handle:
        pad = 28
        s = (spot or "").lower()
        if "right" in s:
            x, an = W - pad, 9
        else:
            x, an = pad, 7
        if "lower" in s or "bottom" in s:
            y, an = bottom - 70, (3 if an == 9 else 1)
        elif "mid" in s:
            y, an = (top + bottom) // 2, (6 if an == 9 else 4)
        else:
            y = top + pad
        lines.append(f"Dialogue: 1,0:00:00.00,{end_all},Mark,,0,0,0,,{{\\an{an}\\pos({x},{y})}}{ass_text(handle)}")

    # word-by-word captions
    cap_y = min(st["y"], H - 260)
    cap_y = max(cap_y, bottom + 120) if bottom + 120 < H - 240 else bottom - 140
    for ci, chunk in enumerate(chunk_words(words, st["words"])):
        for wi, w in enumerate(chunk):
            start = w["start"]
            end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else max(w["end"], start + 0.25)
            parts = []
            for k, x in enumerate(chunk):
                t = ass_text(x["word"].strip())
                if st["upper"]:
                    t = t.upper()
                if k == wi:
                    col = st["active"]
                    if st.get("alternate"):
                        col = st["active"] if ci % 2 else st["text"]
                    p = st["pop"]
                    parts.append(f"{{\\c{ass_color(col)}\\fscx{p}\\fscy{p}\\t(0,90,\\fscx100\\fscy100)}}{t}"
                                 f"{{\\c{ass_color(st['text'])}\\fscx100\\fscy100}}")
                else:
                    parts.append(t)
            glow = ""
            if st.get("glow"):
                glow_line = (f"Dialogue: 0,{fmt_t(start)},{fmt_t(end)},Cap,,0,0,0,,"
                             f"{{\\pos({W // 2},{cap_y})\\blur8\\bord14\\3c{ass_color(st['glow'])}"
                             f"\\1a&HFF&}}{' '.join(ass_text(x['word'].strip()).upper() for x in chunk)}")
                lines.append(glow_line)
            lines.append(f"Dialogue: 1,{fmt_t(start)},{fmt_t(end)},Cap,,0,0,0,,{{\\pos({W // 2},{cap_y})}}"
                         + " ".join(parts))
    return "\n".join(lines) + "\n"


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "default=nw=1", path],
                         capture_output=True, text=True, check=True).stdout
    d = dict(l.split("=", 1) for l in out.strip().splitlines() if "=" in l)
    return int(d["width"]), int(d["height"]), float(d["duration"])


def video_box(src_w, src_h, zoom, y_shift):
    fg_w = int(round(W * zoom / 2) * 2)
    fg_h = int(round(fg_w * src_h / src_w / 2) * 2)
    fg_h = min(fg_h, H)
    top = (H - fg_h) // 2 + y_shift
    return fg_w, fg_h, top, top + fg_h


def render(src, out, acct, words, hook, hook_color, hook_font, handle, spot, zoom, trim, workdir):
    src_w, src_h, dur = probe(src)
    pic = PICTURE[acct]
    fg_w, fg_h, top, bottom = video_box(src_w, src_h, zoom, pic["y_shift"])
    trim = max(0.0, min(trim, max(dur - 3, 0)))
    shifted = [dict(w, start=w["start"] - trim, end=w["end"] - trim) for w in words if w["end"] > trim]
    ass_path = os.path.join(workdir, f"a{acct}.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_ass(shifted, acct, hook, hook_color, hook_font, handle, spot, dur - trim, (top, bottom)))

    vf = (
        f"[0:v]split=2[a][b];"
        f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=12:2,"
        f"scale={W}:{H},eq=brightness={pic['blur_dim']}:saturation=1.2[bg];"
        f"[b]scale={fg_w}:{fg_h},crop=min({W}\\,iw):ih,eq=saturation={pic['sat']}:brightness={pic['bright']}[fg];"
        f"[bg][fg]overlay=(W-w)/2:{top},setsar=1,"
        f"ass={ass_path}:fontsdir={FONTS_DIR}[v]"
    )
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{trim:.2f}", "-i", src,
           "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-map_metadata", "-1",
           "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
    return out
