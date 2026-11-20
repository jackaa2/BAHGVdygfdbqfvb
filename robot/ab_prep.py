"""🧪 Start the no-hook test now: every 3rd Short still waiting to upload (slot 8 h+ away) gets re-made
WITHOUT the hook card. Posts col Q = variant, file id cleared so the uploader picks the new file by name."""
import datetime as dt
import os
import re
from zoneinfo import ZoneInfo

import config as C
from google_api import Google

ET = ZoneInfo("America/New_York")
sheet = os.environ["SHEET_ID"]
g = Google()
now = dt.datetime.now(ET).replace(tzinfo=None)
posts = g.get_values(sheet, f"'{C.POSTS_TAB}'!A2:Q") or []
head = [str(h).strip() for h in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS}:Z{C.HEADER_ROWS}")[0]]
hx = {h: i for i, h in enumerate(head)}
ids = [str(x[0]).strip() if x else "" for x in g.get_values(sheet, f"'{C.PANEL_TAB}'!A{C.HEADER_ROWS + 1}:A") or []]
col = lambda h: chr(65 + hx[h])
data, k, per = {}, {}, {}
for i, p in enumerate(posts):
    p = p + [""] * (17 - len(p))
    a, cid = int(p[1] or 0), str(p[3]).strip()
    try:
        t = dt.datetime.strptime(str(p[7]).strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        continue
    data[f"'{C.POSTS_TAB}'!Q{i + 2}"] = [[p[16] or "hook"]]
    if not str(p[8]).startswith("🕒") or str(p[12]).strip() or t - now < dt.timedelta(hours=8) or cid not in ids:
        continue
    k[a] = k.get(a, 0) + 1
    if k[a] % 3 != 2:          # every 3rd one per channel
        continue
    rn = C.HEADER_ROWS + 1 + ids.index(cid)
    data[f"'{C.PANEL_TAB}'!{col('Status')}{rn}"] = [["Pending"]]
    data[f"'{C.PANEL_TAB}'!{col('Notes')}{rn}"] = [[f"🤖 AUTO fill ch{a} nohook requeue"]]
    data[f"'{C.PANEL_TAB}'!{col('🚀 SEND')}{rn}"] = [[True]]
    data[f"'{C.POSTS_TAB}'!P{i + 2}"] = [[""]]
    data[f"'{C.POSTS_TAB}'!Q{i + 2}"] = [["no-hook"]]
    per[a] = per.get(a, 0) + 1
    print(f"no-hook: {cid} ch{a} (goes live {t:%a %-I:%M %p})")
g.update_many(sheet, data)
print(f"Re-making without hook: {per}")
