"""The 6 channel looks. Every channel gets its own caption style, so no two uploads look copy-pasted.

Colors are normal hex (#RRGGBB). Fonts live in robot/fonts (free Google fonts).
A font file dropped into Drive "0 - Brand Kit" is used for the HOOK text on every channel
(e.g. a GTA-style font you own the rights to).
"""

# Same look on every channel: Titan One, white with black outline. The word being spoken turns into the
# GTA 6 sunset gradient (orange -> pink -> purple). Channels still differ in words-per-line + position.
FONT = "Titan One"
GRADIENT = ["#FFC24A", "#FFA94D", "#FF8A5C", "#FF6B78", "#FF5596", "#E04FB4", "#B84DD6", "#9447F0"]

_base = dict(font=FONT, size=96, upper=True, text="#FFFFFF", outline="#000000", border=7, shadow=3, pop=112)
CAPTION_MIDDLE = True   # captions sit in the middle of the post (over the lower half of the clip)
CAPTION_STYLES = {
    1: dict(_base, name="3 words",      words=3, y=1060),
    2: dict(_base, name="2 words",      words=2, y=1020),
    3: dict(_base, name="3 words",      words=3, y=1100),
    4: dict(_base, name="2 words",      words=2, y=1080),
    5: dict(_base, name="1 big word",   words=1, y=1040, size=118),
    6: dict(_base, name="3 words",      words=3, y=1000),
}
CREDIT_Y = 1640          # top of the "[logo] streamer" credit pill

# Small picture differences per channel (on top of Account Styles tab: zoom, watermark spot, trim).
PICTURE = {
    1: dict(y_shift=0,   sat=1.00, bright=0.00, blur_dim=-0.18),
    2: dict(y_shift=-40, sat=1.08, bright=0.01, blur_dim=-0.22),
    3: dict(y_shift=30,  sat=0.96, bright=0.00, blur_dim=-0.15),
    4: dict(y_shift=-20, sat=1.04, bright=-0.01, blur_dim=-0.25),
    5: dict(y_shift=50,  sat=1.10, bright=0.02, blur_dim=-0.12),
    6: dict(y_shift=-60, sat=1.02, bright=0.00, blur_dim=-0.20),
}

# Which of the 3 hooks each channel uses (Hook 1-3 columns in the Control Panel).
HOOK_FOR = {1: 1, 2: 2, 3: 3, 4: 1, 5: 2, 6: 3}

HOOK_COLORS = {"yellow": "#FFE14D", "white": "#FFFFFF", "cyan": "#2EE6FF", "pink": "#FF4FA3",
               "green": "#7CFF6B", "orange": "#FF9A3C", "red": "#FF4D4D", "purple": "#B66BFF"}
