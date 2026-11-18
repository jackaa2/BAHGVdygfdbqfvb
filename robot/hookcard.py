"""TikTok-style hook text: black words on white rounded boxes, one box per line, centered."""
import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Poppins-SemiBold.ttf")
# one emoji = base symbol + optional variation selector / skin tone + optional ZWJ joins
EMOJI = re.compile("(?:[\U0001F000-\U0001FAFF☀-➿⭐⭕‼⁉])"
                   "(?:️|[\U0001F3FB-\U0001F3FF])*"
                   "(?:‍(?:[\U0001F000-\U0001FAFF☀-➿])(?:️|[\U0001F3FB-\U0001F3FF])*)*")
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "twemoji")
TWEMOJI = "https://raw.githubusercontent.com/jdecked/twemoji/main/assets/72x72/{}.png"


def emoji_img(e):
    """Color emoji image (Twemoji, free CC-BY) or None if it can't be fetched."""
    import urllib.request
    codes = [f"{ord(ch):x}" for ch in e]
    names = ["-".join(codes), "-".join(c for c in codes if c != "fe0f")]
    os.makedirs(CACHE, exist_ok=True)
    bundled = os.path.join(HERE, "assets", "emoji")
    for n in names:  # 1) emojis shipped with the robot (the common ones)
        p = os.path.join(bundled, n + ".png")
        if os.path.exists(p):
            return Image.open(p).convert("RGBA")
    for n in names:  # 2) download anything else (retry once)
        path = os.path.join(CACHE, n + ".png")
        if not os.path.exists(path):
            for _ in range(2):
                try:
                    req = urllib.request.Request(TWEMOJI.format(n), headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as r, open(path, "wb") as f:
                        f.write(r.read())
                    break
                except Exception:
                    if os.path.exists(path):
                        os.remove(path)
            if not os.path.exists(path):
                print(f"emoji not found: {n}")
                continue
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            pass
    return None


def segments(text):
    """Split a line into ('t', text) and ('e', emoji) pieces."""
    out, pos = [], 0
    for m in EMOJI.finditer(text):
        if m.start() > pos:
            out.append(("t", text[pos:m.start()]))
        out.append(("e", m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append(("t", text[pos:]))
    return out


def seg_width(segs, font, size):
    return sum(font.getlength(v) if k == "t" else size * 1.15 for k, v in segs)


def wrap(text, font, max_w, size):
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if seg_width(segments(test), font, size) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur); cur = word
    if cur:
        lines.append(cur)
    return lines


def make_hook(text, out_path, size=62, max_w=880):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return None
    font = ImageFont.truetype(FONT, size)
    lines = wrap(text, font, max_w, size)
    if len(lines) > 3:                      # very long hook: shrink to fit 3 lines
        return make_hook(text, out_path, size=int(size * 0.85), max_w=max_w)
    pad_x, pad_y = int(size * 0.42), int(size * 0.20)
    asc, desc = font.getmetrics()
    line_h = asc + desc
    box_h = line_h + 2 * pad_y
    step = box_h - int(size * 0.12)         # boxes touch/overlap slightly, like TikTok
    widths = [int(seg_width(segments(l), font, size)) + 2 * pad_x for l in lines]
    W = max(widths) + 4
    H = step * (len(lines) - 1) + box_h + 4
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.28)
    for i, (l, w) in enumerate(zip(lines, widths)):
        x0 = (W - w) // 2
        y0 = 2 + i * step
        d.rounded_rectangle([x0, y0, x0 + w, y0 + box_h], radius=r, fill=(255, 255, 255, 255))
    esz = int(size * 1.05)
    for i, (l, w) in enumerate(zip(lines, widths)):
        x = (W - w) // 2 + pad_x
        y0 = 2 + i * step
        for kind, val in segments(l):
            if kind == "t":
                d.text((x, y0 + pad_y - int(size * 0.02)), val, font=font, fill=(0, 0, 0, 255))
                x += font.getlength(val)
            else:
                em = emoji_img(val)
                if em is not None:
                    em = em.resize((esz, esz), Image.LANCZOS)
                    img.alpha_composite(em, (int(x + size * 0.05), int(y0 + (box_h - esz) / 2)))
                x += size * 1.15
    img.save(out_path)
    return img.size
