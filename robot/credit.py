"""Credit pill at the bottom of every version: [Twitch/Kick badge] streamername
Credits the creator on screen (what clip channels do to stay on the right side of the streamer)."""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "TitanOne-Regular.ttf")
BADGE = {
    "twitch": ("#9146FF", os.path.join(HERE, "assets", "twitch_glyph.png")),
    "kick": ("#53FC18", os.path.join(HERE, "assets", "kick_glyph.png")),
}


def make_credit(platform, name, out_path, height=96):
    platform = (platform or "").lower()
    color, glyph_path = BADGE.get(platform, BADGE["twitch"])
    font = ImageFont.truetype(FONT, int(height * 0.48))
    name = (name or "").strip()
    text_w = int(font.getlength(name))
    pad, gap = int(height * 0.14), int(height * 0.22)
    badge = height - 2 * pad
    w = pad + badge + gap + text_w + int(height * 0.42)
    img = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, height - 1], radius=height // 2, fill=(0, 0, 0, 185))
    # platform badge: brand-colored rounded square with the logo glyph
    d.rounded_rectangle([pad, pad, pad + badge, pad + badge], radius=int(badge * 0.28), fill=color)
    glyph = Image.open(glyph_path).convert("RGBA").resize((int(badge * 0.66),) * 2, Image.LANCZOS)
    off = pad + (badge - glyph.width) // 2
    img.alpha_composite(glyph, (off, off))
    # streamer name
    tx = pad + badge + gap
    ty = (height - font.getbbox(name)[3]) // 2 - int(height * 0.02)
    d.text((tx, ty), name, font=font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
    img.save(out_path)
    return img.size
