"""The 6 channel looks. Every channel gets its own caption style, so no two uploads look copy-pasted.

Colors are normal hex (#RRGGBB). Fonts live in robot/fonts (free Google fonts).
A font file dropped into Drive "0 - Brand Kit" is used for the HOOK text on every channel
(e.g. a GTA-style font you own the rights to).
"""

CAPTION_STYLES = {
    1: dict(name="Vice Pop",          font="Anton",         size=104, upper=True,  words=3,
            text="#FFFFFF", active="#FFE14D", outline="#000000", border=7, shadow=3,
            box=False, pop=118, tilt=0,   y=1390),
    2: dict(name="Neon Pink",         font="Bebas Neue",    size=124, upper=True,  words=2,
            text="#FFFFFF", active="#FF4FA3", outline="#3A0A2A", border=6, shadow=0,
            box=False, pop=112, tilt=0,   y=1410, glow="#FF4FA3"),
    3: dict(name="Cyan Wave",         font="Archivo Black", size=82,  upper=True,  words=3,
            text="#FFFFFF", active="#2EE6FF", outline="#06223A", border=7, shadow=2,
            box=False, pop=110, tilt=0,   y=1380),
    4: dict(name="Black Box",         font="Bungee",        size=88,  upper=True,  words=2,
            text="#FFFFFF", active="#FF9A3C", outline="#000000", border=14, shadow=0,
            box=True,  pop=106, tilt=0,   y=1400),
    5: dict(name="One Word Punch",    font="Luckiest Guy",  size=132, upper=True,  words=1,
            text="#FFF35C", active="#7CFF6B", outline="#000000", border=8, shadow=4,
            box=False, pop=125, tilt=0,   y=1360, alternate=True),
    6: dict(name="Sunset Comic",      font="Bangers",       size=116, upper=True,  words=4,
            text="#FFB347", active="#FFFFFF", outline="#4B1D6E", border=7, shadow=3,
            box=False, pop=112, tilt=-3,  y=1395),
}

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
