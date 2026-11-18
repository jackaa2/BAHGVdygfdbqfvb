"""Turn one raw clip into a vertical 1080x1920 channel version: blurred background, clip in the middle,
hook on top, word-by-word captions, small watermark. All done with ffmpeg + an .ass subtitle file."""
import os
import re
import subprocess

from credit import make_credit
from hookcard import make_hook
from styles import CAPTION_MIDDLE, CAPTION_STYLES, CREDIT_Y, GRADIENT, PICTURE

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
    border_style = 1
    back = ass_color("#000000", 0x60)
    outline_col = ass_color(st["outline"])
    hook_size = 92 if len(hook or "") < 26 else 80 if len(hook or "") < 48 else 68
    hook_y = max(top - 45, 300) if bottom < H - 10 else 380   # static caption: just above the clip

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{st['font']},{st['size']},{ass_color(st['text'])},{ass_color(st['text'])},"
        f"{outline_col},{back},0,0,0,0,100,100,1,0,{border_style},{st['border']},{st['shadow']},"
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
    # (hook is drawn as a TikTok-style white box image in render(), not here)

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

    # word-by-word captions: white line + the spoken word in the sunset gradient
    cap_y = min(st["y"], CREDIT_Y - 90)
    if bottom < H - 10 and not CAPTION_MIDDLE:  # captions under the clip, above the credit pill
        cap_y = max(cap_y, bottom + 110) if bottom + 110 < CREDIT_Y - 70 else bottom - 140
    fs, p = st["size"], st["pop"]
    # clean the word list: drop empty words, keep time order, no negative lengths
    clean = []
    for w in sorted(words, key=lambda w: w["start"]):
        t = ass_text(w["word"]).strip()
        if not t or not re.search(r"\w", t):
            continue
        st_ = max(w["start"], clean[-1]["start"] + 0.01) if clean else max(w["start"], 0)
        clean.append({"word": t, "start": st_, "end": max(w["end"], st_ + 0.05)})
    chunks = chunk_words(clean, st["words"])
    # every caption event ends before the next one starts -> never two lines on screen at once
    starts = [w["start"] for c in chunks for w in c] + [duration + 5]
    nxt = {id(w): starts[i + 1] for i, w in enumerate(w for c in chunks for w in c)}
    for chunk in chunks:
        texts = [ass_text(x["word"].strip()) for x in chunk]
        texts = [t.upper() if st["upper"] else t for t in texts]
        # keep the line on one row: shrink if it would be wider than the screen
        est = sum(len(t) for t in texts) * fs * 0.62 + (len(texts) - 1) * fs * 0.3
        sc = min(100, int(940 / est * 100)) if est else 100
        head = f"{{\\an5\\pos({W // 2},{cap_y})\\q2\\fscx{sc}\\fscy{sc}}}"
        h = fs * sc / 100
        for wi, w in enumerate(chunk):
            start = w["start"]
            end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else max(w["end"], start + 0.25)
            end = min(end, nxt[id(w)] - 0.01, duration)
            if end <= start:
                continue
            t0, t1 = fmt_t(start), fmt_t(end)

            def line(show_all=True):
                out = []
                for k, t in enumerate(texts):
                    pop = (f"{{\\fscx{sc * p // 100}\\fscy{sc * p // 100}\\t(0,90,\\fscx{sc}\\fscy{sc})}}"
                           if k == wi else f"{{\\fscx{sc}\\fscy{sc}}}")
                    out.append(f"{pop}{t}")
                return " ".join(out)

            # base: whole line white with black outline
            lines.append(f"Dialogue: 1,{t0},{t1},Cap,,0,0,0,,{head}" + line(True))
            # gradient: same layout, only the spoken word visible, painted in horizontal color bands
            top_y, bot_y = cap_y - h * 0.42, cap_y + h * 0.42
            n = len(GRADIENT)
            for bi, colr in enumerate(GRADIENT):
                y0 = int(top_y + (bot_y - top_y) * bi / n) if bi else 0
                y1 = int(top_y + (bot_y - top_y) * (bi + 1) / n) if bi < n - 1 else H
                words_txt = []
                for k, t in enumerate(texts):
                    pop = (f"\\fscx{sc * p // 100}\\fscy{sc * p // 100}\\t(0,90,\\fscx{sc}\\fscy{sc})"
                           if k == wi else f"\\fscx{sc}\\fscy{sc}")
                    alpha = "\\1a&H00&" if k == wi else "\\1a&HFF&"
                    words_txt.append(f"{{{pop}{alpha}}}{t}")
                lines.append(
                    f"Dialogue: 2,{t0},{t1},Cap,,0,0,0,,{head}{{\\c{ass_color(colr)}\\3a&HFF&\\4a&HFF&"
                    f"\\clip(0,{y0},{W},{y1})}}" + " ".join(words_txt))
    return "\n".join(lines) + "\n"


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "default=nw=1", path],
                         capture_output=True, text=True, check=True).stdout
    d = dict(l.split("=", 1) for l in out.strip().splitlines() if "=" in l)
    return int(d["width"]), int(d["height"]), float(d["duration"])


def video_box(src_w, src_h, zoom, y_shift):
    if src_w / src_h < 1.2:   # vertical or square clip: fill the whole screen
        return W, H, 0, H
    fg_w = int(round(W * zoom / 2) * 2)
    fg_h = int(round(fg_w * src_h / src_w / 2) * 2)
    fg_h = min(fg_h, H)
    top = (H - fg_h) // 2 + y_shift
    return fg_w, fg_h, top, top + fg_h


WM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "watermarks")
WM_BOX = (360, 130)        # every watermark fits inside this box ...
WM_RIGHT, WM_TOP = 40, 56  # ... anchored to the same top-right spot


def watermark_png(acct, workdir):
    """Channel logo scaled to fit the same top-right box on every video (None if no logo)."""
    from PIL import Image
    src = os.path.join(WM_DIR, f"A{acct}.png")
    if not os.path.exists(src):
        return None
    im = Image.open(src).convert("RGBA")
    sc = min(WM_BOX[0] / im.width, WM_BOX[1] / im.height)
    im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.LANCZOS)
    a = im.getchannel("A").point(lambda v: int(v * 0.92))  # tiny bit see-through
    im.putalpha(a)
    out = os.path.join(workdir, f"wm_{acct}.png")
    im.save(out)
    return out, im.size


def render(src, out, acct, words, hook, hook_color, hook_font, handle, spot, zoom, trim, workdir,
           platform="twitch", streamer="", max_len=25.0):
    src_w, src_h, dur = probe(src)
    pic = PICTURE[acct]
    fg_w, fg_h, top, bottom = video_box(src_w, src_h, zoom, pic["y_shift"])
    trim = max(0.0, min(trim, max(dur - 3, 0)))
    length = min(dur - trim, max_len)
    shifted = [dict(w, start=w["start"] - trim, end=min(w["end"] - trim, length))
               for w in words if w["end"] > trim and w["start"] - trim < length - 0.15]
    ass_path = os.path.join(workdir, f"a{acct}.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_ass(shifted, acct, hook, hook_color, hook_font, handle, spot, length, (top, bottom)))
    extra_inputs, overlays = [], []
    if streamer:
        credit_png = os.path.join(workdir, f"credit_{acct}.png")
        make_credit(platform, streamer, credit_png)
        extra_inputs.append(credit_png); overlays.append(("(W-w)/2", str(CREDIT_Y)))
    wm = watermark_png(acct, workdir)
    if wm:
        (wm_path, (ww, wh)) = wm
        extra_inputs.append(wm_path); overlays.append((str(W - WM_RIGHT - ww), str(WM_TOP + (WM_BOX[1] - wh) // 2)))
    if hook:
        hook_png = os.path.join(workdir, f"hook_{acct}.png")
        size = make_hook(hook, hook_png)
        if size:
            hy = max(top - size[1] - 36, 140) if bottom < H - 10 else 300
            extra_inputs.append(hook_png); overlays.append(("(W-w)/2", str(hy)))

    vf = (
        f"[0:v]split=2[a][b];"
        f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=12:2,"
        f"scale={W}:{H},eq=brightness={pic['blur_dim']}:saturation=1.2[bg];"
        + (f"[b]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
           if fg_h >= H else f"[b]scale={fg_w}:{fg_h},crop=min({W}\\,iw):ih,")
        + f"eq=saturation={pic['sat']}:brightness={pic['bright']}[fg];"
        f"[bg][fg]overlay=(W-w)/2:{max(top, 0)},setsar=1,"
        f"ass={ass_path}:fontsdir={FONTS_DIR}[s0]"
    )
    last = "s0"
    for i, (ox, oy) in enumerate(overlays):
        vf += f";[{last}][{i + 1}:v]overlay={ox}:{oy}[s{i + 1}]"
        last = f"s{i + 1}"
    vf += f";[{last}]null[v]"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{trim:.2f}", "-t", f"{length:.2f}",
           "-i", src] + sum([["-loop", "1", "-i", x] for x in extra_inputs], []) + [
           "-filter_complex", vf, "-t", f"{length:.2f}", "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "superfast", "-crf", "23", "-maxrate", "4M", "-bufsize", "8M", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-map_metadata", "-1",
           "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
    return out
