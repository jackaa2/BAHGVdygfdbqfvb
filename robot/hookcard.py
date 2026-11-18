"""TikTok-style hook text: black words on white rounded boxes, one box per line, centered."""
import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Poppins-SemiBold.ttf")
EMOJI = re.compile("[\U00010000-\U0010FFFF☀-➿️‍]")


def wrap(text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if font.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur); cur = word
    if cur:
        lines.append(cur)
    return lines


def make_hook(text, out_path, size=62, max_w=880):
    text = EMOJI.sub("", str(text or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    font = ImageFont.truetype(FONT, size)
    lines = wrap(text, font, max_w)
    if len(lines) > 3:                      # very long hook: shrink to fit 3 lines
        return make_hook(text, out_path, size=int(size * 0.85), max_w=max_w)
    pad_x, pad_y = int(size * 0.42), int(size * 0.20)
    asc, desc = font.getmetrics()
    line_h = asc + desc
    box_h = line_h + 2 * pad_y
    step = box_h - int(size * 0.12)         # boxes touch/overlap slightly, like TikTok
    widths = [int(font.getlength(l)) + 2 * pad_x for l in lines]
    W = max(widths) + 4
    H = step * (len(lines) - 1) + box_h + 4
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.28)
    for i, (l, w) in enumerate(zip(lines, widths)):
        x0 = (W - w) // 2
        y0 = 2 + i * step
        d.rounded_rectangle([x0, y0, x0 + w, y0 + box_h], radius=r, fill=(255, 255, 255, 255))
    for i, (l, w) in enumerate(zip(lines, widths)):
        x0 = (W - w) // 2
        y0 = 2 + i * step
        d.text((x0 + pad_x, y0 + pad_y - int(size * 0.02)), l, font=font, fill=(0, 0, 0, 255))
    img.save(out_path)
    return img.size
